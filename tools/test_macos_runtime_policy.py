"""Regression coverage for the arm64-only macOS runtime policy (#72)."""
from __future__ import annotations

import plistlib
import re
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import build_upstream_runtime
import macos_runtime_policy as policy
import package_apple_xcframeworks as packager
import package_macos_runtime
import qualification_scope
import validate_runtime_dependencies
from validate_runtime_dependencies import validate_macho_dependencies

REPO_ROOT = Path(__file__).resolve().parents[1]
PROVIDER_REFERENCE = """
extern void *LiteRtLmGemmaModelConstraintProvider_Create(void);
extern void *LiteRtLmGemmaModelConstraintProvider_CreateConstraintFromTools(void);
extern void LiteRtLmGemmaModelConstraintProvider_Destroy(void *);
void *const provider_entry_points[] = {
    (void *)&LiteRtLmGemmaModelConstraintProvider_Create,
    (void *)&LiteRtLmGemmaModelConstraintProvider_CreateConstraintFromTools,
    (void *)&LiteRtLmGemmaModelConstraintProvider_Destroy,
};
"""
PROVIDER_DEFINITION = """
void *LiteRtLmGemmaModelConstraintProvider_Create(void) { return 0; }
void *LiteRtLmGemmaModelConstraintProvider_CreateConstraintFromTools(void) { return 0; }
void LiteRtLmGemmaModelConstraintProvider_Destroy(void *provider) { (void)provider; }
"""


def compile_dylib(
    output: Path,
    source: str,
    arch: str,
    *,
    install_name: str | None = None,
    extra: list[str] | None = None,
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    source_file = output.with_name(output.name + ".c")
    source_file.write_text(source, encoding="utf-8")
    subprocess.run(
        [
            "xcrun", "clang", "-dynamiclib", "-arch", arch,
            "-mmacosx-version-min=14.0",
            "-install_name", install_name or f"@rpath/{output.name}",
            "-Wl,-rpath,@loader_path",
            str(source_file), "-o", str(output), *(extra or []),
        ],
        check=True,
        capture_output=True,
    )
    source_file.unlink()
    return output


def flat_provider_runtime(output: Path, arch: str) -> Path:
    """Mimic the published x86_64 runtime: provider binds left to dyld."""
    return compile_dylib(
        output, PROVIDER_REFERENCE, arch, extra=["-Wl,-undefined,dynamic_lookup"]
    )


def lipo(output: Path, *slices: Path) -> Path:
    subprocess.run(
        ["xcrun", "lipo", "-create", *map(str, slices), "-output", str(output)],
        check=True,
        capture_output=True,
    )
    return output


@unittest.skipUnless(sys.platform == "darwin", "requires Apple toolchain")
class MacOsRuntimeValidationTest(unittest.TestCase):
    def test_x64_runtime_with_flat_provider_binds_fails_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            flat_provider_runtime(root / "bin/macos/x64/libLiteRtLm.dylib", "x86_64")
            with self.assertRaises(SystemExit) as failure:
                validate_macho_dependencies(root)
        message = str(failure.exception)
        self.assertIn("bin/macos/x64 is not a supported runtime directory", message)
        self.assertIn(
            "bin/macos/x64/libLiteRtLm.dylib (x86_64) leaves required Gemma "
            "constraint provider symbols unresolved: "
            "_LiteRtLmGemmaModelConstraintProvider_Create, "
            "_LiteRtLmGemmaModelConstraintProvider_CreateConstraintFromTools, "
            "_LiteRtLmGemmaModelConstraintProvider_Destroy",
            message,
        )

    def test_universal_binary_reports_its_non_host_slice(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = root / "raw"
            provider = compile_dylib(
                raw / "libGemmaModelConstraintProvider.dylib", PROVIDER_DEFINITION, "arm64"
            )
            arm64 = compile_dylib(
                raw / "arm64/libLiteRtLm.dylib", PROVIDER_REFERENCE, "arm64",
                extra=[str(provider)],
            )
            x86_64 = flat_provider_runtime(raw / "x86_64/libLiteRtLm.dylib", "x86_64")
            universal = lipo(raw / "libLiteRtLm.dylib", arm64, x86_64)
            self.assertEqual(policy.unresolved_provider_symbols(arm64), {})
            self.assertEqual(
                set(policy.unresolved_provider_symbols(universal)), {"x86_64"}
            )

            target = root / "bin/macos/arm64"
            target.mkdir(parents=True)
            (target / provider.name).write_bytes(provider.read_bytes())
            (target / "libLiteRtLm.dylib").write_bytes(universal.read_bytes())
            with self.assertRaisesRegex(SystemExit, r"libLiteRtLm\.dylib \(x86_64\) leaves"):
                validate_macho_dependencies(root)

            (target / "libLiteRtLm.dylib").write_bytes(arm64.read_bytes())
            self.assertEqual(validate_macho_dependencies(root), 2)

    def test_archive_audit_rejects_x64_runtime_and_universal_slices(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = root / "raw"
            arm64 = compile_dylib(raw / "arm64/libCLiteRTLM_mac.dylib", "int a(void) { return 1; }\n", "arm64")
            x86_64 = flat_provider_runtime(raw / "x86_64/libCLiteRTLM_mac.dylib", "x86_64")
            universal = lipo(raw / "libCLiteRTLM_mac.dylib", arm64, x86_64)
            release = root / "release"
            release.mkdir()
            for name, library in (("Thin", arm64), ("Universal", universal)):
                xcframework = root / name / "CLiteRTLMMac.xcframework"
                subprocess.run(
                    ["xcodebuild", "-create-xcframework", "-library", str(library),
                     "-output", str(xcframework)],
                    check=True,
                    capture_output=True,
                )
                packager.zip_xcframework(
                    xcframework, release / f"litert-lm-native-apple-{name}-xcframework-v0.18.0-1.zip"
                )
            runtime_dir = root / "runtime"
            for arch in ("arm64", "x64"):
                (runtime_dir / "macos" / arch).mkdir(parents=True)
                with tarfile.open(
                    release / f"litert-lm-native-runtime-macos-{arch}-v0.18.0-1.tar.gz", "w:gz"
                ) as bundle:
                    bundle.add(runtime_dir / "macos" / arch, arcname=f"macos/{arch}")

            errors = policy.validate_macos_archives(release)

        self.assertEqual(len(errors), 4, errors)
        joined = "\n".join(errors)
        self.assertNotIn("-Thin-", joined)
        self.assertNotIn("runtime-macos-arm64", joined)
        self.assertIn("litert-lm-native-runtime-macos-x64-v0.18.0-1.tar.gz: macOS runtimes are published for arm64 only", joined)
        self.assertRegex(joined, r"Universal.*declares macOS architectures \['arm64', 'x86_64'\]")
        self.assertRegex(joined, r"Universal.*contains \['x86_64', 'arm64'\]")
        self.assertRegex(joined, r"Universal.*\(x86_64\) leaves Gemma constraint provider symbols")


@unittest.skipUnless(sys.platform == "darwin", "packages with xcodebuild and codesign")
class MacOsArm64OnlyPackagingTest(unittest.TestCase):
    def stage_runtime(self, bin_dir: Path) -> None:
        target = bin_dir / "macos/arm64"
        provider = compile_dylib(
            target / "libGemmaModelConstraintProvider.dylib", PROVIDER_DEFINITION, "arm64"
        )
        core = compile_dylib(
            target / "libLiteRtLm.dylib", PROVIDER_REFERENCE, "arm64", extra=[str(provider)]
        )
        compile_dylib(
            target / "libCLiteRTLM_mac.dylib", "", "arm64",
            extra=["-x", "c", f"-Wl,-reexport_library,{core}"],
        )

    def package(self, root: Path) -> list[Path]:
        with patch.object(packager, "BIN_DIR", root / "bin"), \
             patch.object(packager, "WORK_DIR", root / "work"), \
             patch.object(packager, "DIST_DIR", root / "dist"):
            return packager.package_all("v0.18.0-1", clean=True, compatibility_tag="v0.18.0")

    def test_primary_and_compatibility_xcframeworks_are_arm64_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.stage_runtime(root / "bin")
            archives = self.package(root)
            names = sorted(archive.name for archive in archives)
            self.assertEqual(
                names,
                [
                    "litert-lm-native-apple-CLiteRTLMMac-xcframework-v0.18.0-1.zip",
                    "litert-lm-native-apple-GemmaModelConstraintProvider-xcframework-v0.18.0-1.zip",
                    "litert-lm-native-apple-LiteRtLm-xcframework-v0.18.0-1.zip",
                ],
            )
            for archive in archives:
                with zipfile.ZipFile(archive) as bundle:
                    plist = next(n for n in bundle.namelist() if re.fullmatch(r"[^/]+\.xcframework/Info\.plist", n))
                    libraries = plistlib.loads(bundle.read(plist))["AvailableLibraries"]
                self.assertEqual(
                    [(item["LibraryIdentifier"], item["SupportedArchitectures"]) for item in libraries],
                    [("macos-arm64", ["arm64"])],
                    archive.name,
                )
            self.assertEqual(policy.validate_macos_archives(root / "dist"), [])

    def test_stale_x64_runtime_directory_stops_packaging(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.stage_runtime(root / "bin")
            flat_provider_runtime(root / "bin/macos/x64/libLiteRtLm.dylib", "x86_64")
            with self.assertRaisesRegex(RuntimeError, "Unsupported macOS runtime architecture directories .*: x64"):
                self.package(root)
            self.assertFalse((root / "dist").exists())
            with patch.object(package_macos_runtime, "BIN_DIR", root / "bin"):
                with self.assertRaisesRegex(RuntimeError, "arm64 only"):
                    package_macos_runtime.package_macos_runtime(
                        root / "missing.zip", clean=True, upstream_tag="v0.18.0"
                    )


def write_runtime_tarball(release: Path, archive_arch: str, member_arch: str) -> Path:
    staging = release.parent / "staging" / archive_arch / member_arch
    (staging / "libLiteRtLm.dylib").parent.mkdir(parents=True)
    (staging / "libLiteRtLm.dylib").write_bytes(b"\x00")
    release.mkdir(parents=True, exist_ok=True)
    archive = release / f"litert-lm-native-runtime-macos-{archive_arch}-v0.18.0-1.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(staging, arcname=f"macos/{member_arch}")
    return archive


class MacOsArchiveAuditCallSiteTest(unittest.TestCase):
    def test_arm64_tarball_with_foreign_arch_member_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            release = Path(temp) / "release"
            write_runtime_tarball(release, "arm64", "arm64")
            self.assertEqual(policy.validate_macos_archives(release), [])
            write_runtime_tarball(release, "arm64", "x64")
            errors = policy.validate_macos_archives(release)
        self.assertTrue(errors)
        self.assertTrue(
            all(
                error.startswith(
                    "litert-lm-native-runtime-macos-arm64-v0.18.0-1.tar.gz: contains macos/x64"
                )
                for error in errors
            ),
            errors,
        )

    def test_runtime_dependency_main_audits_archive_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive_root = root / "archives"
            write_runtime_tarball(archive_root, "arm64", "arm64")

            def run_main() -> int:
                with patch.object(sys, "argv", [
                    "validate_runtime_dependencies.py", "--root", str(root),
                    "--upstream-tag", "v0.18.0", "--archive-root", str(archive_root),
                ]):
                    return validate_runtime_dependencies.main()

            self.assertEqual(run_main(), 0)
            write_runtime_tarball(archive_root, "x64", "x64")
            with self.assertRaises(SystemExit) as failure:
                run_main()
        message = str(failure.exception)
        self.assertIn("macOS archive validation failed", message)
        self.assertIn(
            "litert-lm-native-runtime-macos-x64-v0.18.0-1.tar.gz: macOS runtimes are "
            "published for arm64 only",
            message,
        )

    def test_packager_main_audits_its_release_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            dist = Path(temp) / "dist"
            release = dist / "v0.18.0-1"
            packaged = write_runtime_tarball(release, "arm64", "arm64")

            def run_main() -> int:
                with patch.object(packager, "DIST_DIR", dist), \
                     patch.object(packager, "REPO_ROOT", Path(temp)), \
                     patch.object(packager, "package_all", return_value=[packaged]), \
                     patch.object(packager, "validate_privacy_manifests"), \
                     patch.object(sys, "argv", [
                         "package_apple_xcframeworks.py", "--release-tag", "v0.18.0-1",
                         "--compatibility-tag", "v0.18.0",
                     ]):
                    return packager.main()

            self.assertEqual(run_main(), 0)
            write_runtime_tarball(release, "arm64", "x64")
            with self.assertRaisesRegex(
                RuntimeError,
                r"macOS XCFramework validation failed:\n"
                r"litert-lm-native-runtime-macos-arm64-v0\.18\.0-1\.tar\.gz: contains macos/x64",
            ):
                run_main()


class MacOsArm64OnlyInventoryTest(unittest.TestCase):
    def test_official_x86_64_slices_are_not_repackaged(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            xcframework = root / "CLiteRTLM_mac.xcframework"
            xcframework.mkdir()
            (xcframework / "Info.plist").write_bytes(plistlib.dumps({
                "AvailableLibraries": [{
                    "LibraryIdentifier": "macos-arm64_x86_64",
                    "LibraryPath": "libCLiteRTLM_mac.dylib",
                    "SupportedArchitectures": ["arm64", "x86_64"],
                    "SupportedPlatform": "macos",
                }],
            }))
            specs = package_macos_runtime.discover_macos_slices(root)
        self.assertEqual([spec["arch"] for spec in specs], ["arm64"])

    def test_no_build_matrix_or_target_produces_macos_x64(self) -> None:
        self.assertNotIn(("macos", "x64"), build_upstream_runtime.RUNTIME_TARGETS)
        self.assertNotIn(
            ("macos", "x64"),
            {(row["platform"], row["arch"]) for row in qualification_scope.MATRIX},
        )
        workflow = (REPO_ROOT / ".github/workflows/native_release.yml").read_text(encoding="utf-8")
        self.assertIn('"platform": "macos", "arch": "arm64"', workflow)
        self.assertNotIn('"platform": "macos", "arch": "x64"', workflow)
        with patch.object(sys, "argv", [
            "build_upstream_runtime.py", "--upstream-tag", "v0.18.0",
            "--platform", "macos", "--arch", "x64",
        ]):
            with self.assertRaisesRegex(SystemExit, "macos/x64: macOS runtimes are published for arm64 only"):
                build_upstream_runtime.main()


if __name__ == "__main__":
    unittest.main()
