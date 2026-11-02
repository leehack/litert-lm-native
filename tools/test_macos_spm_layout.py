"""Exercise the actual staged macOS SPM layout with Mach-O dependencies."""
import hashlib
import plistlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import package_apple_xcframeworks as package


@unittest.skipUnless(sys.platform == "darwin", "requires macOS Mach-O loader")
class MacOsSpmLayoutTest(unittest.TestCase):
    def test_companion_framework_signatures_survive_packaging(self):
        for name in ("LiteRtMetalAccelerator", "LiteRtTopKMetalSampler"):
            with self.subTest(module=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / "companion.c"
                source.write_text("int companion_answer(void) { return 42; }\n")
                library = root / f"lib{name}.dylib"
                subprocess.run(["clang", "-dynamiclib", str(source), "-o", str(library),
                                "-install_name", f"@rpath/{library.name}",
                                "-Wl,-headerpad_max_install_names"], check=True)
                subprocess.run(["codesign", "--force", "--sign", "-", str(library)], check=True)
                original = hashlib.sha256(library.read_bytes()).hexdigest()
                work = root / "work"
                args = package.make_macos_framework_argument(name, {"arm64": library}, work)
                archive = package.create_xcframework(name, args, work, root / "dist", "test")
                extracted = root / "extracted"
                subprocess.run(["ditto", "-x", "-k", str(archive), str(extracted)], check=True)
                framework = extracted / f"{name}.xcframework/macos-arm64/{name}.framework"
                verified = subprocess.run(["codesign", "--verify", "--deep", "--strict",
                                           str(framework)], capture_output=True, text=True)
                self.assertEqual(verified.returncode, 0, verified.stderr)
                loaded = subprocess.run([sys.executable, "-c",
                    "import ctypes,sys; lib=ctypes.CDLL(sys.argv[1]); assert lib.companion_answer()==42",
                    str(framework / name)], capture_output=True, text=True)
                self.assertEqual(loaded.returncode, 0, loaded.stderr)
                self.assertEqual(hashlib.sha256(library.read_bytes()).hexdigest(), original)

    def test_framework_and_shim_load_without_flat_runtime_neighbors(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "raw"
            source.mkdir()
            provider = source / "libGemmaModelConstraintProvider.dylib"
            core = source / "libLiteRtLm.dylib"
            shim = source / "libCLiteRTLM_mac.dylib"
            (source / "provider.c").write_text("int provider_answer(void) { return 42; }\n")
            (source / "core.c").write_text("extern int provider_answer(void); int runtime_answer(void) { return provider_answer(); }\n")
            (source / "shim.c").write_text("int shim_marker(void) { return 1; }\n")
            for name, extra in (
                ("provider", []),
                ("core", [str(provider)]),
                ("shim", [f"-Wl,-reexport_library,{core}"]),
            ):
                destination = {"provider": provider, "core": core, "shim": shim}[name]
                subprocess.run(["clang", "-dynamiclib", str(source / f"{name}.c"),
                                "-o", str(destination), "-install_name", f"@rpath/{destination.name}",
                                "-Wl,-rpath,@loader_path", *extra], check=True)
            originals = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (provider, core, shim)}
            work = root / "work"
            work.mkdir()
            args = package.make_macos_framework_argument("LiteRtLm", {"arm64": core}, work)
            framework = Path(args[1])
            binary = framework / "Versions/A/LiteRtLm"
            with self.assertRaisesRegex(RuntimeError, "Missing macOS SPM dependency"):
                package.complete_macos_primary_framework(framework, {}, work)
            package.complete_macos_primary_framework(framework, {provider.name: {"arm64": provider}}, work)
            shim_args = package.make_macos_library_argument("CLiteRTLMMac", {"arm64": shim}, work, include_headers=False)
            package.retarget_macos_compatibility_shim(shim_args)
            app = root / "App.app/Contents/Frameworks"
            app.mkdir(parents=True)
            shutil.copytree(framework, app / "LiteRtLm.framework", symlinks=True)
            shutil.copy2(shim_args[1], app / shim.name)
            self.assertFalse((app / core.name).exists())
            self.assertFalse((app / provider.name).exists())
            # Separate process avoids libraries cached by another test masking
            # an incomplete layout or resolving through source build paths.
            result = subprocess.run([sys.executable, "-c",
                "import ctypes,sys; lib=ctypes.CDLL(sys.argv[1]); assert lib.runtime_answer()==42",
                str(app / shim.name)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("@loader_path/Dependencies/" + provider.name,
                          package._macho_dependencies(binary))
            for path, digest in originals.items():
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)


class MacOsSpmPackagingWiringTest(unittest.TestCase):
    @staticmethod
    def _stage_xcframework(command):
        if command[0] != "xcodebuild":
            return
        xcframework = Path(command[-1])
        libraries = []
        for identifier, platform in (("macos-arm64", "macos"), ("ios-arm64", "ios")):
            (xcframework / identifier / "Companion.framework").mkdir(parents=True)
            libraries.append({"LibraryIdentifier": identifier,
                              "LibraryPath": "Companion.framework",
                              "SupportedPlatform": platform})
        (xcframework / "Info.plist").write_bytes(plistlib.dumps({"AvailableLibraries": libraries}))

    def test_only_final_macos_framework_is_signed_and_verified_before_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            events = []
            def run(command):
                events.append(command)
                self._stage_xcframework(command)
            with mock.patch.object(package, "run", side_effect=run), \
                 mock.patch.object(package, "zip_xcframework", side_effect=lambda *args: events.append(["zip"])):
                package.create_xcframework("Companion", [], root, root / "dist", "test")
            self.assertEqual([command[0] for command in events],
                             ["xcodebuild", "codesign", "codesign", "zip"])
            sign, verify = events[1:3]
            self.assertIn("--sign", sign)
            self.assertEqual(sign[sign.index("--sign") + 1], "-")
            self.assertIn("--verify", verify)
            self.assertIn("--deep", verify)
            self.assertIn("--strict", verify)
            expected = str(root / "Companion.xcframework/macos-arm64/Companion.framework")
            self.assertEqual(sign[-1], expected)
            self.assertEqual(verify[-1], expected)

    def test_signing_or_verification_failure_prevents_archive(self):
        for failing_flag in ("--sign", "--verify"):
            with self.subTest(flag=failing_flag), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                def run(command):
                    self._stage_xcframework(command)
                    if command[0] == "codesign" and failing_flag in command:
                        raise subprocess.CalledProcessError(1, command)
                with mock.patch.object(package, "run", side_effect=run), \
                     mock.patch.object(package, "zip_xcframework") as archive:
                    with self.assertRaises(subprocess.CalledProcessError):
                        package.create_xcframework("Companion", [], root, root / "dist", "test")
                    archive.assert_not_called()

    def test_macos_framework_paths_cannot_escape_the_slice(self):
        for identifier, library in (("../outside", "Companion.framework"),
                                    ("macos-arm64", "../Companion.framework")):
            with self.subTest(identifier=identifier, library=library), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "Info.plist").write_bytes(plistlib.dumps({"AvailableLibraries": [{
                    "LibraryIdentifier": identifier, "LibraryPath": library,
                    "SupportedPlatform": "macos",
                }]}))
                with mock.patch.object(package, "run") as run:
                    with self.assertRaisesRegex(RuntimeError, "Invalid macOS framework slice path"):
                        package.sign_macos_framework_slices(root)
                    run.assert_not_called()

    def test_dependency_architecture_coverage_is_checked_per_slice(self):
        for x64_needs_provider in (False, True):
            with self.subTest(x64_needs_provider=x64_needs_provider), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                framework = root / "LiteRtLm.framework"
                binary = framework / "Versions/A/LiteRtLm"
                binary.parent.mkdir(parents=True)
                binary.write_bytes(b"core")
                provider = root / "libProvider.dylib"
                provider.write_bytes(b"provider")
                def dependencies(current, arch=None):
                    if current == binary and (arch == "arm64" or x64_needs_provider):
                        return ["@rpath/libProvider.dylib"]
                    return []
                with mock.patch.object(package, "_macho_arches", side_effect=lambda p: {"arm64", "x86_64"} if p == binary else {"arm64"}), \
                     mock.patch.object(package, "_macho_dependencies", side_effect=dependencies), \
                     mock.patch.object(package, "make_macos_library_argument", return_value=["-library", str(provider)]), \
                     mock.patch.object(package, "run"):
                    if x64_needs_provider:
                        with self.assertRaisesRegex(RuntimeError, "lacks required x86_64 slice"):
                            package.complete_macos_primary_framework(framework, {provider.name: {"arm64": provider}}, root)
                    else:
                        package.complete_macos_primary_framework(framework, {provider.name: {"arm64": provider}}, root)

    def test_primary_and_shim_are_repaired_before_archiving(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            order = []
            with mock.patch.object(package, "BIN_DIR", root / "bin"), \
                 mock.patch.object(package, "WORK_DIR", root / "work"), \
                 mock.patch.object(package, "DIST_DIR", root / "dist"), \
                 mock.patch.object(package, "ios_framework_module_names", return_value=[]), \
                 mock.patch.object(package, "macos_libraries_by_name", return_value={}), \
                 mock.patch.object(package, "macos_companion_args_by_module", return_value={"CLiteRTLMMac": ["-library", "shim"]}), \
                 mock.patch.object(package, "make_macos_framework_argument", return_value=["-framework", "core.framework"]), \
                 mock.patch.object(package, "complete_macos_primary_framework", side_effect=lambda *a: order.append("core")), \
                 mock.patch.object(package, "retarget_macos_compatibility_shim", side_effect=lambda *a: order.append("shim")), \
                 mock.patch.object(package, "package_ios_framework_module", side_effect=lambda *a, **k: order.append("archive") or root / "result.zip"), \
                 mock.patch.object(package, "package_ios_companions", return_value=([], set())), \
                 mock.patch.object(package, "package_macos_companions", return_value=[]):
                package.package_all("v0.17.0-1", clean=False, compatibility_tag="v0.17.0")
            self.assertEqual(order[:3], ["core", "shim", "archive"])


if __name__ == "__main__":
    unittest.main()
