from __future__ import annotations

import io
import json
import os
import plistlib
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import build_upstream_runtime as builder
import ios_runtime_policy as policy
import package_apple_xcframeworks as apple
import package_ios_runtime as ios
import package_release as release
import validate_runtime_dependencies as dependencies
import validate_affected_candidate as affected
from litert_lm_symbols import APPLE_METAL_ACCELERATOR_SYMBOLS, APPLE_METAL_SAMPLER_SYMBOLS
from qualification_scope import MATRIX


class IosSourcePolicyTest(unittest.TestCase):
    def test_missing_or_changed_source_gate_prevents_build(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = root / "runtime/conversation/model_data_processor/BUILD"
            gate.parent.mkdir(parents=True)
            fixture = (Path(__file__).parent / "fixtures/ios_fst_gate.BUILD").read_text()
            for text in ("", fixture.replace('"LITERT_LM_FST_CONSTRAINTS_DISABLED": "1"', '"OTHER": "1"'),
                         fixture.replace(':litert_lm_fst_constraints_disabled": []', ':other": []', 1)):
                gate.write_text(text)
                with patch.object(builder, "materialize_git_lfs_libraries"), patch.object(builder, "patch_upstream_ios_sampler_path"), patch.object(builder, "run") as run:
                    with self.assertRaisesRegex(RuntimeError, "gate"):
                        builder.build_runtime(root, "ios", "arm64", "v0.17.0", "1")
                    run.assert_not_called()

    def test_unknown_compatibility_tag_cannot_disable_policy(self) -> None:
        for tag in ("", "g" + "a" * 12, "v0.17.0-7"):
            with self.subTest(tag=tag), self.assertRaisesRegex(ValueError, "compatibility tag"):
                policy.provider_free_ios(tag)

    def test_production_clis_require_explicit_compatibility_context(self) -> None:
        for module in (apple, dependencies):
            result = subprocess.run([sys.executable, module.__file__], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("required", result.stderr)

    def test_workflows_pass_selected_context_and_keep_full_matrix(self) -> None:
        root = Path(__file__).parents[1]
        for name, variable in (("pr_release_qualification.yml", "$QUALIFICATION_UPSTREAM_TAG"), ("native_release.yml", "$COMPATIBILITY_TAG")):
            text = (root / ".github/workflows" / name).read_text()
            self.assertIn(f'--compatibility-tag "{variable}"', text)
            for line in text.splitlines():
                if "python3 tools/validate_runtime_dependencies.py" in line:
                    self.assertIn(f'--upstream-tag "{variable}"', line)


@unittest.skipUnless(sys.platform == "darwin", "requires Apple Mach-O tools")
class IosBinaryPolicyTest(unittest.TestCase):
    def build(self, root: Path, name: str, *, symbol: bool = False, link: Path | None = None, minimum: str = "16.4", simulator: bool = False, exports: list[str] | None = None) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        source = root / f"{name}.c"
        source.write_text("extern void LiteRtLmGemmaModelConstraintProvider_Create(void); void fixture(void) { LiteRtLmGemmaModelConstraintProvider_Create(); }" if symbol else "void LiteRtLmGemmaModelConstraintProvider_Create(void) {}" if "Provider" in name else "void fixture(void) {}")
        if exports:
            source.write_text("\n".join(f"void {symbol}(void) {{}}" for symbol in exports))
        binary = root / f"lib{name}.dylib"
        args = ["xcrun", "--sdk", "iphonesimulator" if simulator else "iphoneos", "clang", "-dynamiclib", "-arch", "arm64", f"-mios-simulator-version-min={minimum}" if simulator else f"-miphoneos-version-min={minimum}", "-install_name", f"@rpath/{binary.name}", str(source), "-o", str(binary)]
        if symbol and link is None:
            args += ["-Wl,-undefined,dynamic_lookup"]
        if link:
            args += ["-Wl,-needed_library," + str(link)]
        subprocess.run(args, check=True, capture_output=True)
        return binary

    def test_real_deployment_floors_fail_closed_in_directory_and_archive(self) -> None:
        for simulator in (False, True):
            with self.subTest(simulator=simulator), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                directory = root / "bin/ios" / ("arm64-sim" if simulator else "arm64")
                binary = self.build(directory, "LiteRtMetalAccelerator", minimum="26.4", simulator=simulator)
                with self.assertRaisesRegex(RuntimeError, "above 16.4"):
                    policy.validate_ios_directory(directory)
                dist = root / "dist"
                dist.mkdir()
                with zipfile.ZipFile(dist / "Metal.zip", "w") as file:
                    library = {"SupportedPlatform": "ios", "LibraryIdentifier": "custom-slice"}
                    if simulator:
                        library["SupportedPlatformVariant"] = "simulator"
                    file.writestr("Metal.xcframework/Info.plist", plistlib.dumps({"AvailableLibraries": [library]}))
                    file.writestr("Metal.xcframework/custom-slice/Metal.framework/Metal", binary.read_bytes())
                with self.assertRaisesRegex(RuntimeError, "above 16.4"):
                    policy.validate_ios_archives(dist)
                binary = self.build(directory, "LiteRtMetalAccelerator", simulator=simulator)
                policy.validate_ios_directory(directory)
                framework = directory / "Metal.framework"
                framework.mkdir()
                (framework / "Metal").write_bytes(binary.read_bytes())
                info = {"CFBundleExecutable": "Metal", "CFBundleSupportedPlatforms": ["iPhoneSimulator" if simulator else "iPhoneOS"], "MinimumOSVersion": "26.4"}
                (framework / "Info.plist").write_bytes(plistlib.dumps(info))
                with self.assertRaisesRegex(RuntimeError, "declares 26.4"):
                    policy.validate_ios_directory(directory)
                info["MinimumOSVersion"] = "16.4"
                (framework / "Info.plist").write_bytes(plistlib.dumps(info))
                policy.validate_ios_directory(directory)

    def test_wrong_platform_and_archive_metadata_cannot_qualify(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary = self.build(root / "bin/ios/arm64-sim", "LiteRtLm")
            with self.assertRaisesRegex(RuntimeError, "Invalid iPhoneSimulator"):
                policy.validate_ios_directory(root / "bin/ios")
            dist = root / "dist"
            dist.mkdir()
            for declared, expected in (("15.0", "but its binary requires"), ("26.4", "declares 26.4"), ("16.4", None)):
                with zipfile.ZipFile(dist / "LiteRtLm.zip", "w") as file:
                    file.writestr("LiteRtLm.xcframework/Info.plist", plistlib.dumps({"AvailableLibraries": [{"SupportedPlatform": "ios", "LibraryIdentifier": "custom-device"}]}))
                    file.writestr("LiteRtLm.xcframework/custom-device/LiteRtLm.framework/Info.plist", plistlib.dumps({"CFBundleExecutable": "LiteRtLm", "CFBundleSupportedPlatforms": ["iPhoneOS"], "MinimumOSVersion": declared}))
                    file.writestr("LiteRtLm.xcframework/custom-device/LiteRtLm.framework/LiteRtLm", binary.read_bytes())
                if expected:
                    with self.assertRaisesRegex(RuntimeError, expected):
                        policy.validate_ios_archives(dist)
                else:
                    policy.validate_ios_archives(dist)

    def test_real_load_and_all_undefined_symbols_rejected_before_cleanup(self) -> None:
        for mode in ("undefined", "linked", "two-level"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp) / "bin/ios/arm64"
                provider = self.build(directory, "GemmaModelConstraintProvider")
                self.build(directory, "LiteRtLm", symbol=mode != "linked", link=provider if mode != "undefined" else None)
                if mode == "two-level":
                    report = subprocess.run(["nm", "-m", str(directory / "libLiteRtLm.dylib")], check=True, capture_output=True, text=True).stdout
                    self.assertIn("(from libGemmaModelConstraintProvider)", report)
                    self.assertNotIn("dynamically looked up", report)
                with self.assertRaisesRegex(RuntimeError, "still requires"):
                    policy.validate_ios_directory(directory, remove_unused_provider=True)
                self.assertTrue(provider.exists())
                result = subprocess.run([sys.executable, dependencies.__file__, "--root", tmp, "--upstream-tag", "v0.17.0"], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("still requires", result.stderr)

    def test_unused_flat_framework_removed_but_metal_and_macos_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = root / "bin/ios/arm64"
            self.build(directory, "LiteRtLm")
            provider = self.build(directory, "gemma_model_constraint_provider")
            framework = directory / "GemmaModelConstraintProvider.framework"
            framework.mkdir()
            (framework / framework.stem).write_bytes(provider.read_bytes())
            metal = self.build(directory, "LiteRtMetalAccelerator")
            macos = root / "bin/macos/arm64/libgemma_model_constraint_provider.dylib"
            macos.parent.mkdir(parents=True)
            macos.write_bytes(provider.read_bytes())
            with self.assertRaisesRegex(RuntimeError, "inventory"):
                policy.validate_ios_directory(directory)
            policy.validate_ios_directory(directory, remove_unused_provider=True)
            self.assertFalse(provider.exists())
            self.assertFalse(framework.exists())
            self.assertTrue(metal.exists())
            self.assertTrue(macos.exists())
            policy.validate_ios_directory(directory)

    def test_source_builder_finalizes_both_source_entry_paths(self) -> None:
        for local_source in (False, True):
            with self.subTest(local_source=local_source), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                output = self.build(root / "source", "LiteRtLm")
                directory = root / "bin/ios/arm64"
                provider = self.build(directory, "GemmaModelConstraintProvider")
                arguments = ["builder", "--upstream-tag", "v0.17.0", "--platform", "ios", "--arch", "arm64"]
                if local_source:
                    arguments += ["--source-root", str(root / "source")]
                with patch.object(sys, "argv", arguments), patch.object(builder, "BIN_DIR", root / "bin"), patch.object(builder, "download_upstream", return_value=root / "source"), patch.object(builder, "build_runtime", return_value=output), patch.object(builder, "validate_exported_symbols"), patch.object(builder, "stage_runtime_dependencies"), patch.object(builder, "stage_runtime_overrides"):
                    self.assertEqual(builder.main(), 0)
                self.assertFalse(provider.exists())
                policy.validate_ios_directory(directory)

    def test_production_source_packager_gate_runs_before_staging(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = root / "ios/arm64"
            source = self.build(directory, "LiteRtLm", symbol=True)
            with patch.object(ios, "BIN_DIR", root), patch.object(ios, "copy_framework_executable") as copy:
                with self.assertRaisesRegex(RuntimeError, "still requires"):
                    ios.stage_source_built_slice({"arch": "arm64", "sdk": "iphoneos", "framework_binary": source}, False, "v0.17.0")
                copy.assert_not_called()

    def test_spm_and_manifest_reject_stale_provider_before_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = self.build(root / "bin/ios/arm64", "GemmaModelConstraintProvider")
            with patch.object(apple, "BIN_DIR", root / "bin"), patch.object(apple, "create_xcframework") as create:
                with self.assertRaisesRegex(RuntimeError, "inventory"):
                    apple.package_all("v0.17.0-7", False, "v0.17.0")
                create.assert_not_called()
            with patch.object(release, "BIN_DIR", root / "bin"), patch.object(release, "DIST_DIR", root / "dist"):
                with self.assertRaisesRegex(RuntimeError, "inventory"):
                    release.build_manifest(upstream_tag="v0.17.0", upstream_commit="a" * 40, compatibility_tag="v0.17.0", release_tag="v0.17.0-7", native_commit="b" * 40, official_upstream_assets=True)
            self.assertTrue(provider.exists())

    def test_partial_qualification_cli_applies_candidate_policy_and_preserves_legacy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [row for row in MATRIX if row["platform"] == "ios"]
            for simulator in (False, True):
                arch = "arm64-sim" if simulator else "arm64"
                for module, exports in (("LiteRtLm", []), ("CLiteRTLM", []), ("LiteRtMetalAccelerator", APPLE_METAL_ACCELERATOR_SYMBOLS), ("LiteRtTopKMetalSampler", APPLE_METAL_SAMPLER_SYMBOLS)):
                    binary = self.build(root / "inputs" / arch, module, simulator=simulator, exports=exports)
                    ios.stage_dependency_framework({"sdk": "iphonesimulator" if simulator else "iphoneos"}, root / "bin/ios" / arch, binary)

            def run(tag: str = "v0.17.0") -> subprocess.CompletedProcess:
                environment = dict(os.environ, SELECTED_MATRIX=json.dumps({"include": rows}), QUALIFICATION_UPSTREAM_TAG=tag, QUALIFICATION_UPSTREAM_COMMIT="a" * 40, PR_HEAD_SHA="b" * 40, QUALIFICATION_RELEASE_TAG=tag)
                return subprocess.run([sys.executable, affected.__file__], cwd=root, env=environment, capture_output=True, text=True)

            healthy = run()
            self.assertEqual(healthy.returncode, 0, healthy.stderr)
            self.assertIn("Validated affected platforms", healthy.stdout)
            high = self.build(root / "inputs/arm64", "LiteRtMetalAccelerator", minimum="26.4", exports=APPLE_METAL_ACCELERATOR_SYMBOLS)
            ios.stage_dependency_framework({"sdk": "iphoneos"}, root / "bin/ios/arm64", high)
            rejected = run()
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("above 16.4", rejected.stderr)
            self.assertNotIn("Validated affected platforms", rejected.stdout)
            historical = run("v0.16.0")
            self.assertEqual(historical.returncode, 0, historical.stderr)
            low = self.build(root / "inputs/arm64", "LiteRtMetalAccelerator", exports=APPLE_METAL_ACCELERATOR_SYMBOLS)
            ios.stage_dependency_framework({"sdk": "iphoneos"}, root / "bin/ios/arm64", low)
            archive_root = root / "dist/spm/v0.17.0"
            archive_root.mkdir(parents=True)
            with zipfile.ZipFile(archive_root / "Provider.zip", "w") as file:
                provider = self.build(root / "inputs/provider", "GemmaModelConstraintProvider")
                framework = root / "staged/GemmaModelConstraintProvider.framework"
                framework.mkdir(parents=True)
                (framework / framework.stem).write_bytes(provider.read_bytes())
                ios.write_framework_info_plist(framework, executable=framework.stem, bundle_identifier="dev.leehack.litertlm.provider.fixture", supported_platform="iPhoneOS")
                file.writestr("GemmaModelConstraintProvider.xcframework/Info.plist", plistlib.dumps({"AvailableLibraries": [{"SupportedPlatform": "ios", "LibraryIdentifier": "custom-device", "LibraryPath": framework.name, "SupportedArchitectures": ["arm64"]}]}))
                prefix = "GemmaModelConstraintProvider.xcframework/custom-device/GemmaModelConstraintProvider.framework/"
                file.writestr(prefix + "Info.plist", (framework / "Info.plist").read_bytes())
                file.writestr(prefix + framework.stem, provider.read_bytes())
            rejected = run()
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("archive contains", rejected.stderr)
            self.assertNotIn("Validated affected platforms", rejected.stdout)
            historical = run("v0.16.0")
            self.assertEqual(historical.returncode, 0, historical.stderr)

    def test_production_cli_validates_real_platform_before_macos_exemption(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "provider.c"
            source.write_text("void fixture(void) {}")
            macos = root / "provider.dylib"
            subprocess.run(["xcrun", "--sdk", "macosx", "clang", "-dynamiclib", "-arch", "arm64", str(source), "-o", str(macos)], check=True, capture_output=True)
            ios_binary = self.build(root / "ios", "GemmaModelConstraintProvider", minimum="26.4")
            dist = root / "dist"
            dist.mkdir()
            archive = dist / "GemmaModelConstraintProvider.zip"
            module = "GemmaModelConstraintProvider"
            for label, variant, binary, expected, identifier in (
                ("macos", None, macos, None, "custom-slice"),
                ("macos", None, macos, None, "ios-custom"),
                ("macos", None, ios_binary, "disagrees with actual Mach-O platform", "custom-slice"),
                ("unknown", None, ios_binary, "Unsupported XCFramework", "custom-slice"),
                (None, None, ios_binary, "Unsupported XCFramework", "custom-slice"),
                ("macos", "simulator", macos, "Unsupported XCFramework", "custom-slice"),
                ("ios", "unknown", ios_binary, "Unsupported XCFramework", "custom-slice"),
            ):
                with self.subTest(label=label, variant=variant, identifier=identifier):
                    library = {"LibraryIdentifier": identifier, "LibraryPath": module + ".framework", "SupportedArchitectures": ["arm64"]}
                    if label is not None:
                        library["SupportedPlatform"] = label
                    if variant is not None:
                        library["SupportedPlatformVariant"] = variant
                    with zipfile.ZipFile(archive, "w") as file:
                        file.writestr(module + ".xcframework/Info.plist", plistlib.dumps({"AvailableLibraries": [library]}))
                        prefix = module + ".xcframework/" + identifier + "/" + module + ".framework/"
                        file.writestr(prefix + "Info.plist", plistlib.dumps({"CFBundleExecutable": module, "CFBundleSupportedPlatforms": ["MacOSX"], "MinimumOSVersion": "16.4"}))
                        file.writestr(prefix + module, binary.read_bytes())
                    result = subprocess.run([sys.executable, dependencies.__file__, "--root", str(root), "--upstream-tag", "v0.17.0", "--archive-root", str(dist)], capture_output=True, text=True)
                    if expected is None:
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertIn("Validated runtime dependencies", result.stdout)
                    else:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn(expected, result.stderr)
                        self.assertNotIn("Validated runtime dependencies", result.stdout)

    def test_real_archive_binary_dependencies_and_provider_members_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary = self.build(root / "inputs", "LiteRtLm", symbol=True)
            dist = root / "dist"
            dist.mkdir()
            archive = dist / "LiteRtLm.zip"
            healthy = self.build(root / "healthy", "LiteRtLm")
            framework = root / "staged/LiteRtLm.framework"
            framework.mkdir(parents=True)

            def write_archive(source: Path) -> None:
                (framework / "LiteRtLm").write_bytes(source.read_bytes())
                ios.write_framework_info_plist(
                    framework,
                    executable="LiteRtLm",
                    bundle_identifier="dev.leehack.litertlm.fixture",
                    supported_platform="iPhoneOS",
                )
                with zipfile.ZipFile(archive, "w") as file:
                    file.writestr("LiteRtLm.xcframework/Info.plist", plistlib.dumps({
                        "CFBundlePackageType": "XFWK",
                        "XCFrameworkFormatVersion": "1.0",
                        "AvailableLibraries": [{
                            "SupportedPlatform": "ios",
                            "LibraryIdentifier": "custom-device",
                            "LibraryPath": "LiteRtLm.framework",
                            "SupportedArchitectures": ["arm64"],
                        }],
                    }))
                    prefix = "LiteRtLm.xcframework/custom-device/LiteRtLm.framework/"
                    file.writestr(prefix + "Info.plist", (framework / "Info.plist").read_bytes())
                    file.writestr(prefix + "LiteRtLm", source.read_bytes())

            write_archive(healthy)
            policy.validate_ios_archives(dist)
            write_archive(binary)
            with self.assertRaisesRegex(RuntimeError, "still requires"):
                policy.validate_ios_archives(dist)
            archive.unlink()
            archive = dist / "litert-lm-native-runtime-ios-arm64-v0.17.0-7.tar.gz"
            with tarfile.open(archive, "w:gz") as file:
                data = b"stale provider"
                member = tarfile.TarInfo("arm64/libgemma_model_constraint_provider.dylib")
                member.size = len(data)
                file.addfile(member, io.BytesIO(data))
            with self.assertRaisesRegex(RuntimeError, "archive contains"):
                policy.validate_ios_archives(dist)
            archive.unlink()
