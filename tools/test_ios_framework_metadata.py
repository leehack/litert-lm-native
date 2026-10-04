from __future__ import annotations

import hashlib
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ios_framework_metadata as metadata
import package_apple_xcframeworks as apple
import package_ios_runtime as ios
import validate_runtime_dependencies as dependencies


class IosMetadataParserTest(unittest.TestCase):
    def test_cli_requires_apple_tools_only_when_apple_inputs_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = dict(os.environ, PATH="/nonexistent")
            command = [sys.executable, str(Path(dependencies.__file__).resolve()), "--root", str(root)]
            absent = subprocess.run(command, env=environment, capture_output=True, text=True)
            self.assertEqual(absent.returncode, 0, absent.stderr)
            framework = root / "bin/ios/arm64/Provider.framework"
            framework.mkdir(parents=True)
            (framework / "Provider").write_bytes(b"Apple runtime input")
            required = subprocess.run(command, env=environment, capture_output=True, text=True)
            self.assertNotEqual(required.returncode, 0)
            self.assertIn("Apple runtime validation requires otool, nm", required.stderr)
            self.assertNotIn("Validated runtime dependencies", required.stdout)
            # Plain macOS dylibs require the same production inspection tools.
            shutil.rmtree(root / "bin/ios")
            library = root / "bin/macos/arm64/libLiteRtLm.dylib"
            library.parent.mkdir(parents=True)
            library.write_bytes(b"Apple runtime input")
            required = subprocess.run(command, env=environment, capture_output=True, text=True)
            self.assertNotEqual(required.returncode, 0)
            self.assertIn("Apple runtime validation requires otool, nm", required.stderr)

    def parse(self, outputs: list[str], platform: str = "iPhoneSimulator") -> str:
        results = [subprocess.CompletedProcess([], 0, "arm64 x86_64\n")]
        results.extend(subprocess.CompletedProcess([], 0, output) for output in outputs)
        with patch.object(metadata.subprocess, "run", side_effect=results):
            return metadata.binary_minimum_os(Path("fixture"), platform)

    def test_all_slices_contribute_their_numeric_minimum(self) -> None:
        self.assertEqual(self.parse([
            "Load command 0\n cmd LC_BUILD_VERSION\n platform IOSSIMULATOR\n minos 16.4\n",
            "Load command 0\n cmd LC_BUILD_VERSION\n platform IOSSIMULATOR\n minos 26.4\n",
        ]), "26.4")
        self.assertGreater(metadata.version_tuple("16.10"), metadata.version_tuple("16.4"))

    def test_missing_second_slice_target_fails_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "one iOS deployment target"):
            self.parse([
                "Load command 0\n cmd LC_BUILD_VERSION\n platform IOSSIMULATOR\n minos 16.4\n",
                "fixture has no build commands",
            ])

    def test_wrong_platform_and_duplicate_targets_fail_closed(self) -> None:
        for output in (
            "Load command 0\n cmd LC_BUILD_VERSION\n platform MACOS\n minos 15.0\n",
            "Load command 0\n cmd LC_BUILD_VERSION\n platform IOSSIMULATOR\n minos 15.0\n" * 2,
        ):
            with self.subTest(output=output), self.assertRaises(RuntimeError):
                self.parse([output])

    def test_legacy_device_and_intel_simulator(self) -> None:
        outputs = [subprocess.CompletedProcess([], 0, "arm64\n"),
                   subprocess.CompletedProcess([], 0, "Load command 4\n cmd LC_VERSION_MIN_IPHONEOS\n version 13.0\n sdk 15.0\n")]
        with patch.object(metadata.subprocess, "run", side_effect=outputs):
            self.assertEqual(metadata.binary_minimum_os(Path("fixture"), "iPhoneOS"), "13.0")
        outputs[0] = subprocess.CompletedProcess([], 0, "x86_64\n")
        with patch.object(metadata.subprocess, "run", side_effect=outputs):
            self.assertEqual(metadata.binary_minimum_os(Path("fixture"), "iPhoneSimulator"), "13.0")


@unittest.skipUnless(sys.platform == "darwin", "requires real Apple packaging tools")
class IosMetadataPackagingTest(unittest.TestCase):
    def build(self, root: Path, name: str, minimum: str, simulator: bool = False, arch: str = "arm64") -> Path:
        root.mkdir(parents=True, exist_ok=True)
        source = root / f"{name}.c"
        source.write_text("int fixture(void) { return 42; }\n")
        binary = root / f"lib{name}.dylib"
        subprocess.run([
            "xcrun", "--sdk", "iphonesimulator" if simulator else "iphoneos", "clang",
            "-dynamiclib", "-arch", arch,
            f"-mios-simulator-version-min={minimum}" if simulator else f"-miphoneos-version-min={minimum}",
            "-install_name", f"@rpath/lib{name}.dylib", str(source), "-o", str(binary),
        ], check=True, capture_output=True)
        return binary

    def test_real_dependency_staging_preserves_binary_floor(self) -> None:
        for simulator in (False, True):
            with self.subTest(simulator=simulator), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = self.build(root, "GemmaModelConstraintProvider", "26.4", simulator)
                original = hashlib.sha256(source.read_bytes()).hexdigest()
                ios.stage_dependency_framework(
                    {"sdk": "iphonesimulator" if simulator else "iphoneos"}, root, source
                )
                framework = root / "GemmaModelConstraintProvider.framework"
                info = plistlib.loads((framework / "Info.plist").read_bytes())
                self.assertEqual(info["MinimumOSVersion"], "26.4")
                self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), original)
                self.assertEqual(metadata.binary_minimum_os(framework / framework.stem,
                    "iPhoneSimulator" if simulator else "iPhoneOS"), "26.4")

    def test_real_fat_simulator_archive_retains_highest_slice_floor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for arch, minimum in (("arm64", "16.4"), ("x86_64", "26.4")):
                target = root / "bin/ios" / ("arm64-sim" if arch == "arm64" else "x64-sim")
                source = self.build(target, "Provider", minimum, True, arch)
                ios.stage_dependency_framework({"sdk": "iphonesimulator"}, target, source)
            target = root / "bin/ios/arm64"
            source = self.build(target, "Provider", "16.4")
            ios.stage_dependency_framework({"sdk": "iphoneos"}, target, source)
            originals = {p: hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in (root / "bin").rglob("*") if p.is_file()}
            work = root / "work"
            work.mkdir()
            with patch.object(apple, "BIN_DIR", root / "bin"):
                archive = apple.package_ios_framework_module("Provider", work, root / "dist", "fixture")
            import zipfile
            with zipfile.ZipFile(archive) as packaged:
                packaged.extractall(root / "unpacked")
            frameworks = list((root / "unpacked").rglob("Provider.framework"))
            self.assertEqual(len(frameworks), 2)
            for framework in frameworks:
                info = plistlib.loads((framework / "Info.plist").read_bytes())
                platform = info["CFBundleSupportedPlatforms"][0]
                self.assertEqual(info["MinimumOSVersion"], "26.4" if platform == "iPhoneSimulator" else "16.4")
                metadata.validate_framework_metadata(framework, platform)
            for path, digest in originals.items():
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)

    def test_generated_framework_keeps_packaging_floor_above_binary_floor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.build(root, "Provider", "13.0")
            ios.stage_dependency_framework({"sdk": "iphoneos"}, root, source)
            framework = root / "Provider.framework"
            self.assertEqual(plistlib.loads((framework / "Info.plist").read_bytes())["MinimumOSVersion"], "15.0")

    def test_real_packaged_framework_rejected_by_spm_and_release_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "bin/ios/arm64"
            source = self.build(target, "GemmaModelConstraintProvider", "26.4")
            ios.stage_dependency_framework({"sdk": "iphoneos"}, target, source)
            framework = target / "GemmaModelConstraintProvider.framework"
            binary = framework / framework.stem
            for declared in ("15.0", "not-a-version", None):
                info = plistlib.loads((framework / "Info.plist").read_bytes())
                info["MinimumOSVersion"] = declared
                if declared is None:
                    del info["MinimumOSVersion"]
                (framework / "Info.plist").write_bytes(plistlib.dumps(info))
                with patch.object(apple, "BIN_DIR", root / "bin"), patch.object(apple, "run") as writer:
                    with self.assertRaises(RuntimeError):
                        apple.package_ios_framework_module(framework.stem, root / "work", root / "dist", "fixture")
                    writer.assert_not_called()
                with self.assertRaises(RuntimeError):
                    dependencies.validate_macho_dependencies(root)
                result = subprocess.run([
                    sys.executable, str(Path(dependencies.__file__).resolve()), "--root", str(root)
                ], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("NameError", result.stderr)
                self.assertNotIn("validate_framework_metadata' is not defined", result.stderr)
            info["MinimumOSVersion"] = "26.4"
            (framework / "Info.plist").write_bytes(plistlib.dumps(info))
            result = subprocess.run([
                sys.executable, str(Path(dependencies.__file__).resolve()), "--root", str(root)
            ], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            info["MinimumOSVersion"] = "15.0"
            (framework / "Info.plist").write_bytes(plistlib.dumps(info))
            # Official-archive imports must reject the same drift before reuse.
            destination = root / framework.name
            destination.mkdir()
            shutil.copy2(binary, destination / framework.stem)
            with self.assertRaises(RuntimeError):
                ios.copy_framework_info_plist(framework, destination)


if __name__ == "__main__":
    unittest.main()
