from __future__ import annotations

import os
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import build_upstream_runtime
import windows_runtime
from validate_runtime_dependencies import validate_pe_dependencies

SECTION_RVA = 0x1000
SECTION_OFFSET = 0x400
MACHINES = {"x64": 0x8664, "arm64": 0xAA64}
RUNTIME = (14, 51, 36247, 0)


def make_pe(path, *, arch="x64", linker=(14, 51), imports=None, delay_imports=None,
            exports=(), file_version=None):
    """Write a PE32+ DLL whose one section holds only the requested tables."""
    section = bytearray()

    def add(data, align=8):
        section.extend(b"\0" * (-len(section) % align))
        rva = SECTION_RVA + len(section)
        section.extend(data)
        return rva

    def thunks(symbols):
        names = [add(struct.pack("<H", 0) + symbol.encode() + b"\0", 2) for symbol in symbols]
        return add(b"".join(struct.pack("<Q", rva) for rva in names) + bytes(8))

    directories = [(0, 0)] * 16
    descriptors = b""
    for dll, symbols in (imports or {}).items():
        table = thunks(symbols)
        descriptors += struct.pack("<IIIII", table, 0, 0, add(dll.encode() + b"\0", 2), table)
    if descriptors:
        directories[1] = (add(descriptors + bytes(20), 4), len(descriptors) + 20)
    descriptors = b""
    for dll, symbols in (delay_imports or {}).items():
        table = thunks(symbols)
        name = add(dll.encode() + b"\0", 2)
        descriptors += struct.pack("<IIIIIIII", 1, name, add(bytes(8)), table, table, 0, 0, 0)
    if descriptors:
        directories[13] = (add(descriptors + bytes(32), 4), len(descriptors) + 32)
    if exports:
        names = [add(symbol.encode() + b"\0", 2) for symbol in exports]
        functions = add(b"".join(struct.pack("<I", SECTION_RVA) for _ in exports), 4)
        name_table = add(b"".join(struct.pack("<I", rva) for rva in names), 4)
        ordinals = add(b"".join(struct.pack("<H", index) for index in range(len(exports))), 2)
        directory = struct.pack("<IIHHIIIIIII", 0, 0, 0, 0, names[0], 1, len(exports), len(exports),
                                functions, name_table, ordinals)
        directories[0] = (add(directory, 4), 40)
    if file_version:
        major, minor, build_number, revision = file_version
        blob = add(b"VS_VERSION_INFO\0" + struct.pack("<IIII", 0xFEEF04BD, 0x10000,
                                                      major << 16 | minor, build_number << 16 | revision), 4)
        level = struct.pack("<IIHHHH", 0, 0, 0, 0, 0, 1)
        tree = (level + struct.pack("<II", 16, 0x80000000 | 24)
                + level + struct.pack("<II", 1, 0x80000000 | 48)
                + level + struct.pack("<II", 0x409, 72)
                + struct.pack("<IIII", blob, 36, 0, 0))
        directories[2] = (add(tree, 4), len(tree))

    header = bytearray(SECTION_OFFSET)
    header[0:2] = b"MZ"
    struct.pack_into("<I", header, 0x3C, 0x40)
    header[0x40:0x44] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", header, 0x44, MACHINES[arch], 1, 0, 0, 0, 240, 0x2022)
    optional = 0x58
    struct.pack_into("<HBB", header, optional, 0x20B, *linker)
    struct.pack_into("<Q", header, optional + 24, 0x180000000)
    struct.pack_into("<I", header, optional + 108, 16)
    for index, (rva, size) in enumerate(directories):
        struct.pack_into("<II", header, optional + 112 + 8 * index, rva, size)
    struct.pack_into("<8sIIII", header, optional + 240, b".rdata", len(section), SECTION_RVA,
                     len(section), SECTION_OFFSET)
    Path(path).write_bytes(bytes(header) + bytes(section))


# The import table of LiteRtLm.dll in v0.18.1-2 (#87), reduced to one symbol per DLL.
BRIDGE_IMPORTS = {
    "KERNEL32.dll": ["GetLastError"],
    "bcryptprimitives.dll": ["ProcessPrng"],
    "api-ms-win-crt-heap-l1-1-0.dll": ["free"],
    "libLiteRt.dll": ["LiteRtCreateEnvironment"],
    "MSVCP140.dll": ["_Thrd_yield"],
    "VCRUNTIME140.dll": ["memcpy"],
    "VCRUNTIME140_1.dll": ["__CxxFrameHandler4"],
    "VCRUNTIME140_THREADS.dll": ["_Cnd_wait"],
}


def upstream_bundle(directory: Path, *, bridge_linker=(14, 51)) -> None:
    """The v0.18.1-2 Windows bundle shape: a /MD bridge beside static-CRT upstream DLLs."""
    directory.mkdir(parents=True, exist_ok=True)
    make_pe(directory / "LiteRtLm.dll", linker=bridge_linker, imports=BRIDGE_IMPORTS,
            exports=["litert_lm_engine_create"])
    make_pe(directory / "libLiteRt.dll", linker=(14, 0), exports=["LiteRtCreateEnvironment"],
            imports={"KERNEL32.dll": ["GetLastError"], "dbghelp.dll": ["SymInitialize"]})


def runtime_dlls(directory: Path, *, version=RUNTIME) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    make_pe(directory / "msvcp140.dll", linker=version[:2], file_version=version, exports=["_Thrd_yield"],
            imports={"VCRUNTIME140.dll": ["memcpy"], "VCRUNTIME140_1.dll": ["__CxxFrameHandler4"]})
    make_pe(directory / "vcruntime140.dll", linker=version[:2], file_version=version, exports=["memcpy"])
    make_pe(directory / "vcruntime140_1.dll", linker=version[:2], file_version=version, exports=["__CxxFrameHandler4"],
            imports={"VCRUNTIME140.dll": ["memcpy"]})
    make_pe(directory / "vcruntime140_threads.dll", linker=version[:2], file_version=version, exports=["_Cnd_wait"],
            imports={"VCRUNTIME140.dll": ["memcpy"]})


def errors_for(directory: Path, arch: str = "x64") -> list[str]:
    return windows_runtime.bundle_errors(windows_runtime.read_bundle(directory), arch)


class PeReaderTest(unittest.TestCase):
    def test_reads_every_table_the_closure_check_needs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "sample.dll"
            make_pe(path, arch="arm64", linker=(14, 51), imports={"MSVCP140.dll": ["?id@?$codecvt@"]},
                    delay_imports={"nvcuda.dll": ["cuInit"]}, exports=["a", "b"],
                    file_version=(14, 51, 36231, 1))
            image = windows_runtime.read_pe(path)
        self.assertEqual(image.machine, "arm64")
        self.assertEqual(image.linker_version, (14, 51))
        self.assertEqual(image.imports, {"msvcp140.dll": frozenset({"?id@?$codecvt@"})})
        self.assertEqual(image.delay_imports, {"nvcuda.dll": frozenset({"cuInit"})})
        self.assertEqual(set(image.all_imports()), {"msvcp140.dll", "nvcuda.dll"})
        self.assertEqual(image.exports, frozenset({"a", "b"}))
        self.assertEqual(image.file_version, (14, 51, 36231, 1))

    def test_rejects_a_non_pe_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "text.dll"
            path.write_bytes(b"not a portable executable")
            with self.assertRaises(windows_runtime.PeError):
                windows_runtime.read_pe(path)


class BundleClosureTest(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.bundle = Path(temp.name) / "x64"
        upstream_bundle(self.bundle)

    def test_v0181_2_bundle_is_missing_the_visual_cpp_runtime(self) -> None:
        self.assertEqual(
            errors_for(self.bundle),
            [
                f"litertlm.dll: imports {name}, which neither the bundle nor Windows provides"
                for name in ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll", "vcruntime140_threads.dll")
            ],
        )

    def test_app_local_runtime_completes_the_bundle(self) -> None:
        runtime_dlls(self.bundle)
        self.assertEqual(errors_for(self.bundle), [])

    def test_missing_export_fails(self) -> None:
        runtime_dlls(self.bundle)
        make_pe(self.bundle / "vcruntime140_threads.dll", file_version=RUNTIME, exports=["_Mtx_lock"],
                imports={"VCRUNTIME140.dll": ["memcpy"]})
        self.assertEqual(
            errors_for(self.bundle),
            ["litertlm.dll: vcruntime140_threads.dll does not export _Cnd_wait"],
        )

    def test_runtime_older_than_the_bridge_linker_fails(self) -> None:
        runtime_dlls(self.bundle, version=(14, 44, 35211, 0))
        self.assertEqual(
            errors_for(self.bundle),
            ["litertlm.dll: linked by MSVC 14.51, newer than the bundled Visual C++ runtime 14.44.35211.0"],
        )

    def test_runtime_from_mixed_redistributables_fails(self) -> None:
        runtime_dlls(self.bundle)
        make_pe(self.bundle / "vcruntime140_threads.dll", file_version=(14, 50, 35710, 0), exports=["_Cnd_wait"],
                imports={"VCRUNTIME140.dll": ["memcpy"]})
        [error] = errors_for(self.bundle)
        self.assertIn("Visual C++ runtime DLLs come from different redistributables", error)

    def test_windows_system_and_debug_runtime_files_never_ship(self) -> None:
        runtime_dlls(self.bundle)
        make_pe(self.bundle / "bcryptprimitives.dll", exports=["ProcessPrng"])
        make_pe(self.bundle / "vcruntime140d.dll")
        self.assertEqual(
            errors_for(self.bundle),
            [
                "bcryptprimitives.dll: Windows provides this library; the bundle must not ship it",
                "vcruntime140d.dll: a debug runtime or a Visual Studio debug_nonredist file, "
                "which may not be redistributed",
            ],
        )

    def test_wrong_architecture_fails(self) -> None:
        runtime_dlls(self.bundle)
        self.assertIn("litertlm.dll: x64 image in a arm64 bundle", errors_for(self.bundle, "arm64"))


class StageVcRuntimeTest(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.bundle = self.root / "bin" / "windows" / "x64"
        upstream_bundle(self.bundle)
        self.redist = self.root / "Redist" / "MSVC" / "14.51.36247"
        runtime_dlls(self.redist / "x64" / "Microsoft.VC145.CRT")
        runtime_dlls(self.redist / "x64" / "Microsoft.VC145.CRT" / "onecore")
        runtime_dlls(self.redist / "debug_nonredist" / "x64" / "Microsoft.VC145.DebugCRT")

    def test_stages_the_import_closure_from_the_toolset_redistributable_folder(self) -> None:
        staged = windows_runtime.stage_vc_runtime(self.bundle, "x64", self.redist)

        self.assertEqual(
            sorted(staged),
            ["msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll", "vcruntime140_threads.dll"],
        )
        for name in staged:
            self.assertEqual(
                (self.bundle / name).read_bytes(),
                (self.redist / "x64" / "Microsoft.VC145.CRT" / name).read_bytes(),
            )
        self.assertEqual(validate_pe_dependencies(self.root), 6)

    def test_stages_runtime_needed_only_by_another_runtime_dll(self) -> None:
        make_pe(self.bundle / "LiteRtLm.dll", imports={"MSVCP140.dll": ["_Thrd_yield"]})
        staged = windows_runtime.stage_vc_runtime(self.bundle, "x64", self.redist)
        self.assertEqual(sorted(staged), ["msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll"])

    def test_unknown_dependency_fails_instead_of_staging(self) -> None:
        make_pe(self.bundle / "LiteRtLm.dll", imports={"OpenCL_custom.dll": ["clGetPlatformIDs"]})
        with self.assertRaisesRegex(RuntimeError, "imports opencl_custom.dll, which is neither bundled"):
            windows_runtime.stage_vc_runtime(self.bundle, "x64", self.redist)
        self.assertEqual(sorted(path.name for path in self.bundle.iterdir()), ["LiteRtLm.dll", "libLiteRt.dll"])

    def test_runtime_missing_from_the_redistributable_folder_fails(self) -> None:
        (self.redist / "x64" / "Microsoft.VC145.CRT" / "vcruntime140_threads.dll").unlink()
        with self.assertRaisesRegex(RuntimeError, "imports vcruntime140_threads.dll"):
            windows_runtime.stage_vc_runtime(self.bundle, "x64", self.redist)

    def test_stale_redistributable_fails_the_bundle_check(self) -> None:
        upstream_bundle(self.bundle, bridge_linker=(14, 52))
        with self.assertRaisesRegex(RuntimeError, "linked by MSVC 14.52, newer than the bundled"):
            windows_runtime.stage_vc_runtime(self.bundle, "x64", self.redist)

    def test_build_stages_runtime_for_windows_only(self) -> None:
        with patch.object(build_upstream_runtime, "BIN_DIR", self.root / "bin"), \
             patch.object(windows_runtime, "vc_redist_dir", return_value=self.redist):
            build_upstream_runtime.stage_windows_vc_runtime("linux", "x64")
            self.assertFalse((self.bundle / "msvcp140.dll").exists())
            build_upstream_runtime.stage_windows_vc_runtime("windows", "x64")
        self.assertTrue((self.bundle / "vcruntime140_threads.dll").is_file())


class ValidatePeDependenciesTest(unittest.TestCase):
    def test_reports_the_v0181_2_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            upstream_bundle(root / "bin" / "windows" / "x64")
            with self.assertRaises(SystemExit) as raised:
                validate_pe_dependencies(root)
        self.assertIn(
            "- bin/windows/x64/litertlm.dll: imports vcruntime140_threads.dll, "
            "which neither the bundle nor Windows provides",
            str(raised.exception),
        )

    def test_root_without_windows_runtimes_checks_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(validate_pe_dependencies(Path(temp)), 0)


class VcRedistDirTest(unittest.TestCase):
    def test_developer_environment_wins(self) -> None:
        with patch.dict(os.environ, {"VCToolsRedistDir": r"C:\VS\VC\Redist\MSVC\14.51.36247"}), \
             patch.object(subprocess, "run") as run:
            self.assertEqual(windows_runtime.vc_redist_dir(), Path(r"C:\VS\VC\Redist\MSVC\14.51.36247"))
        run.assert_not_called()

    def test_vswhere_selects_the_default_redistributable_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            installation = Path(temp)
            version_file = installation / "VC" / "Auxiliary" / "Build" / "Microsoft.VCRedistVersion.default.txt"
            version_file.parent.mkdir(parents=True)
            version_file.write_text("14.51.36247\n")
            completed = subprocess.CompletedProcess([], 0, stdout=f"{installation}\n")
            environment = {key: value for key, value in os.environ.items() if key != "VCToolsRedistDir"}
            with patch.dict(os.environ, environment, clear=True), \
                 patch.object(subprocess, "run", return_value=completed) as run:
                self.assertEqual(
                    windows_runtime.vc_redist_dir(),
                    installation / "VC" / "Redist" / "MSVC" / "14.51.36247",
                )
        self.assertIn("Microsoft.VisualStudio.Component.VC.Tools.x86.x64", run.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
