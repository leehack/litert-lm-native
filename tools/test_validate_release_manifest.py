from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import validate_runtime_artifacts
from generate_schema2_contract_fixture import (
    NATIVE_COMMIT,
    RELEASE_TAG,
    UPSTREAM_COMMIT,
    UPSTREAM_TAG,
    generate_manifest,
)
from validate_release_manifest import (
    main,
    validate_schema_2_identity,
    validate_schema_2_payload,
)
from validate_runtime_artifacts import (
    OFFICIAL_APPLE_RUNTIME_ARCHIVES,
    required_runtime_artifacts,
)


class ValidateReleaseManifestTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.valid = generate_manifest()

    def validate(self, manifest: dict) -> None:
        validate_schema_2_payload(
            manifest,
            upstream_tag=UPSTREAM_TAG,
            upstream_commit=UPSTREAM_COMMIT,
            compatibility_tag=UPSTREAM_TAG,
            native_commit=NATIVE_COMMIT,
            release_tag=RELEASE_TAG,
        )

    def development_manifest(self) -> tuple[dict, str]:
        manifest = deepcopy(self.valid)
        release_tag = f"g{UPSTREAM_COMMIT[:12]}"
        manifest["release"] = {
            "tag": release_tag,
            "channel": "development",
            "kind": "commit",
            "rebuild": 0,
            "githubPrerelease": True,
        }
        manifest["upstream"]["tag"] = None
        manifest["capabilities"]["officialUpstreamAssets"] = False

        path_updates: dict[str, str] = {}
        development_artifacts: list[dict] = []
        for artifact in manifest["artifacts"]:
            original_path = artifact["path"]
            if Path(original_path).parts[:2] == ("dist", "official"):
                continue
            updated_path = original_path.replace(RELEASE_TAG, release_tag)
            path_updates[original_path] = updated_path
            artifact["path"] = updated_path
            artifact["fileName"] = Path(updated_path).name
            artifact["upstreamTag"] = None
            artifact["releaseTag"] = release_tag
            development_artifacts.append(artifact)
        manifest["artifacts"] = development_artifacts

        for platform in manifest["platforms"]:
            platform["releaseAsset"] = (
                f"litert-lm-native-runtime-{platform['platform']}-"
                f"{platform['arch']}-{release_tag}.tar.gz"
            )
            platform["artifactPaths"] = [
                path_updates[path] for path in platform["artifactPaths"]
            ]
        for smoke in manifest["realModelSmokes"]:
            smoke["source"]["runtimeReleaseAsset"] = smoke["source"][
                "runtimeReleaseAsset"
            ].replace(RELEASE_TAG, release_tag)
        return manifest, release_tag

    def test_owner_generated_manifest_satisfies_final_contract(self) -> None:
        self.validate(deepcopy(self.valid))

    def test_development_manifest_excludes_official_upstream_artifacts(self) -> None:
        development, release_tag = self.development_manifest()
        validate_schema_2_payload(
            development,
            upstream_tag=None,
            upstream_commit=UPSTREAM_COMMIT,
            compatibility_tag=UPSTREAM_TAG,
            native_commit=NATIVE_COMMIT,
            release_tag=release_tag,
        )

        official_artifact = next(
            deepcopy(artifact)
            for artifact in self.valid["artifacts"]
            if Path(artifact["path"]).parts[:2] == ("dist", "official")
        )
        official_artifact["upstreamTag"] = None
        official_artifact["releaseTag"] = release_tag
        development["artifacts"].append(official_artifact)
        with self.assertRaisesRegex(
            SystemExit, "must not include official upstream artifacts"
        ):
            validate_schema_2_payload(
                development,
                upstream_tag=None,
                upstream_commit=UPSTREAM_COMMIT,
                compatibility_tag=UPSTREAM_TAG,
                native_commit=NATIVE_COMMIT,
                release_tag=release_tag,
            )

    def test_pre_v0_14_official_archive_paths_share_the_runtime_contract(self) -> None:
        tag = "v0.13.1"
        required = set(required_runtime_artifacts(tag, include_official_assets=True))
        expected = {
            Path("dist") / "official" / tag / archive
            for archive in OFFICIAL_APPLE_RUNTIME_ARCHIVES
        }

        self.assertTrue(expected.issubset(required))
        self.assertTrue(
            expected.isdisjoint(
                required_runtime_artifacts(tag, include_official_assets=False)
            )
        )

    def test_raw_apple_build_tree_fails_post_package_runtime_contract(self) -> None:
        post_package_paths = {
            Path("bin/ios/arm64/LiteRtLm.framework/LiteRtLm"),
            Path("bin/ios/arm64/CLiteRTLM.framework/CLiteRTLM"),
            Path("bin/ios/arm64-sim/LiteRtLm.framework/LiteRtLm"),
            Path("bin/ios/arm64-sim/CLiteRTLM.framework/CLiteRTLM"),
            Path("bin/macos/arm64/libCLiteRTLM_mac.dylib"),
            Path("bin/macos/x64/libCLiteRTLM_mac.dylib"),
            *validate_runtime_artifacts.V0_16_IOS_GPU_ARTIFACTS,
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for relative in required_runtime_artifacts(
                "v0.16.0", include_official_assets=False
            ):
                if relative in post_package_paths:
                    continue
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"runtime")
            for arch in ("arm64", "arm64-sim"):
                for name in (
                    "libLiteRtLm.dylib",
                    "libLiteRtMetalAccelerator.dylib",
                    "libLiteRtTopKMetalSampler.dylib",
                ):
                    path = root / "bin" / "ios" / arch / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b"raw-build-output")

            with (
                patch.object(validate_runtime_artifacts, "REPO_ROOT", root),
                patch.object(
                    sys,
                    "argv",
                    [
                        "validate_runtime_artifacts.py",
                        "--upstream-tag",
                        "v0.16.0",
                        "--allow-missing-official-assets",
                    ],
                ),
            ):
                with self.assertRaises(SystemExit) as failure:
                    validate_runtime_artifacts.main()

        message = str(failure.exception)
        for relative in post_package_paths:
            self.assertIn(relative.as_posix(), message)

    def test_complete_packaged_tree_satisfies_runtime_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            required = required_runtime_artifacts(
                "v0.16.0", include_official_assets=False
            )
            for relative in required:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"runtime")

            with (
                patch.object(validate_runtime_artifacts, "REPO_ROOT", root),
                patch.object(
                    sys,
                    "argv",
                    [
                        "validate_runtime_artifacts.py",
                        "--upstream-tag",
                        "v0.16.0",
                        "--allow-missing-official-assets",
                    ],
                ),
            ):
                self.assertEqual(validate_runtime_artifacts.main(), 0)

    def test_schema_2_payload_requires_exact_schema_version(self) -> None:
        wrong_version = deepcopy(self.valid)
        wrong_version["schemaVersion"] = 1
        with self.assertRaisesRegex(SystemExit, "schemaVersion must be 2"):
            self.validate(wrong_version)

    def test_invalid_release_identity_uses_clean_cli_error(self) -> None:
        with self.assertRaisesRegex(SystemExit, "Release identity is invalid"):
            validate_schema_2_payload(
                deepcopy(self.valid),
                upstream_tag=UPSTREAM_TAG,
                upstream_commit=UPSTREAM_COMMIT,
                compatibility_tag=UPSTREAM_TAG,
                native_commit=NATIVE_COMMIT,
                release_tag="v0.16.0-01",
            )

    def test_identity_phase_requires_hex_commits(self) -> None:
        for section in ("upstream", "native"):
            with self.subTest(section=section):
                malformed = deepcopy(self.valid)
                malformed[section]["commit"] = "z" * 40
                with self.assertRaisesRegex(SystemExit, "must be a full SHA"):
                    validate_schema_2_identity(
                        malformed,
                        upstream_tag=UPSTREAM_TAG,
                        upstream_commit=None,
                        compatibility_tag=UPSTREAM_TAG,
                        native_commit=None,
                        release_tag=RELEASE_TAG,
                    )

        with self.assertRaisesRegex(SystemExit, "requires --upstream-tag"):
            validate_schema_2_identity(
                deepcopy(self.valid),
                upstream_tag=None,
                upstream_commit=UPSTREAM_COMMIT,
                compatibility_tag=UPSTREAM_TAG,
                native_commit=NATIVE_COMMIT,
                release_tag=RELEASE_TAG,
            )

    def test_owner_generated_release_inventory_is_exact(self) -> None:
        fixture_dir = Path(__file__).resolve().parent / "fixtures"
        manifest = fixture_dir / "schema2_contract_manifest.json"
        release = fixture_dir / "schema2_contract_release.json"
        self.assertEqual(
            hashlib.sha256(release.read_bytes()).hexdigest(),
            "e2d199613270b62ad51c6b89fdb5375979822d8b5affd96e00c51afe59296002",
        )
        base_argv = [
            "validate_release_manifest.py",
            str(manifest),
            "--upstream-tag",
            UPSTREAM_TAG,
            "--upstream-commit",
            UPSTREAM_COMMIT,
            "--compatibility-tag",
            UPSTREAM_TAG,
            "--native-commit",
            NATIVE_COMMIT,
            "--release-tag",
            RELEASE_TAG,
            "--require-smoke",
            "linux/x64",
            "--require-smoke",
            "windows/x64",
            "--release-metadata",
            str(release),
        ]
        with patch.object(sys, "argv", base_argv):
            self.assertEqual(main(), 0)

        payload = json.loads(release.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temp:
            mutated = Path(temp) / "release.json"
            mutations = {
                "missing required assets": lambda value: value["assets"].pop(),
                "unexpected assets": lambda value: value["assets"].append(
                    {"name": "unexpected.bin", "digest": "sha256:" + "f" * 64}
                ),
                "duplicate assets": lambda value: value["assets"].append(
                    deepcopy(value["assets"][0])
                ),
                "exact GitHub SHA-256": lambda value: value["assets"][0].update(
                    {"digest": "sha256:not-a-digest"}
                ),
            }
            for expected_error, mutate in mutations.items():
                with self.subTest(expected_error=expected_error):
                    candidate = deepcopy(payload)
                    mutate(candidate)
                    mutated.write_text(json.dumps(candidate), encoding="utf-8")
                    with patch.object(sys, "argv", [*base_argv[:-1], str(mutated)]):
                        with self.assertRaisesRegex(SystemExit, expected_error):
                            main()

    def test_manifest_cannot_expand_the_allowed_spm_release_inventory(self) -> None:
        manifest = deepcopy(self.valid)
        source = next(
            artifact
            for artifact in manifest["artifacts"]
            if artifact["path"].startswith(f"dist/spm/{RELEASE_TAG}/")
        )
        extra = deepcopy(source)
        extra["path"] = f"dist/spm/{RELEASE_TAG}/unexpected-extra.zip"
        extra["fileName"] = "unexpected-extra.zip"
        manifest["artifacts"].append(extra)

        fixture = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "schema2_contract_release.json"
        )
        release = json.loads(fixture.read_text(encoding="utf-8"))
        release["assets"].append(
            {
                "name": "unexpected-extra.zip",
                "digest": "sha256:" + "f" * 64,
            }
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest_path = root / "manifest.json"
            release_path = root / "release.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            release_path.write_text(json.dumps(release), encoding="utf-8")
            with patch.object(
                sys,
                "argv",
                [
                    "validate_release_manifest.py",
                    str(manifest_path),
                    "--upstream-tag",
                    UPSTREAM_TAG,
                    "--upstream-commit",
                    UPSTREAM_COMMIT,
                    "--compatibility-tag",
                    UPSTREAM_TAG,
                    "--native-commit",
                    NATIVE_COMMIT,
                    "--release-tag",
                    RELEASE_TAG,
                    "--release-metadata",
                    str(release_path),
                ],
            ):
                with self.assertRaisesRegex(
                    SystemExit, "SPM artifact inventory mismatch"
                ):
                    main()

    def test_known_v0_16_spm_companions_are_allowed_and_release_bound(self) -> None:
        manifest = deepcopy(self.valid)
        source = next(
            artifact
            for artifact in manifest["artifacts"]
            if artifact["path"].startswith(f"dist/spm/{RELEASE_TAG}/")
        )
        companion_modules = (
            "GemmaModelConstraintProvider",
            "LiteRt",
            "LiteRtTopKWebGpuSampler",
            "LiteRtWebGpuAccelerator",
            "WebgpuDawn",
        )
        companion_names = []
        for module in companion_modules:
            name = (
                f"litert-lm-native-apple-{module}-xcframework-{RELEASE_TAG}.zip"
            )
            companion_names.append(name)
            companion = deepcopy(source)
            companion["path"] = f"dist/spm/{RELEASE_TAG}/{name}"
            companion["fileName"] = name
            manifest["artifacts"].append(companion)

        fixture = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "schema2_contract_release.json"
        )
        release = json.loads(fixture.read_text(encoding="utf-8"))
        release["assets"].extend(
            {
                "name": name,
                "digest": "sha256:" + hashlib.sha256(name.encode()).hexdigest(),
            }
            for name in companion_names
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest_path = root / "manifest.json"
            release_path = root / "release.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            release_path.write_text(json.dumps(release), encoding="utf-8")
            argv = [
                "validate_release_manifest.py",
                str(manifest_path),
                "--upstream-tag",
                UPSTREAM_TAG,
                "--upstream-commit",
                UPSTREAM_COMMIT,
                "--compatibility-tag",
                UPSTREAM_TAG,
                "--native-commit",
                NATIVE_COMMIT,
                "--release-tag",
                RELEASE_TAG,
                "--release-metadata",
                str(release_path),
            ]
            with patch.object(sys, "argv", argv):
                self.assertEqual(main(), 0)

            release["assets"] = [
                asset
                for asset in release["assets"]
                if asset["name"] != companion_names[-1]
            ]
            release_path.write_text(json.dumps(release), encoding="utf-8")
            with patch.object(sys, "argv", argv):
                with self.assertRaisesRegex(SystemExit, "missing required assets"):
                    main()

    def test_cli_rejects_malformed_manifest_and_release_metadata_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = root / "manifest.json"
            release = root / "release.json"
            manifest.write_text("not-json", encoding="utf-8")
            with patch.object(
                sys,
                "argv",
                [
                    "validate_release_manifest.py",
                    str(manifest),
                    "--release-tag",
                    RELEASE_TAG,
                ],
            ):
                with self.assertRaisesRegex(SystemExit, "valid UTF-8 JSON"):
                    main()

            manifest.write_text(json.dumps(self.valid), encoding="utf-8")
            release.write_text("[]", encoding="utf-8")
            with patch.object(
                sys,
                "argv",
                [
                    "validate_release_manifest.py",
                    str(manifest),
                    "--upstream-tag",
                    UPSTREAM_TAG,
                    "--release-tag",
                    RELEASE_TAG,
                    "--release-metadata",
                    str(release),
                ],
            ):
                with self.assertRaisesRegex(SystemExit, "metadata must be a JSON object"):
                    main()

    def test_wrong_package_and_incomplete_platforms_fail_closed(self) -> None:
        wrong_package = deepcopy(self.valid)
        wrong_package["package"] = "lookalike"
        with self.assertRaisesRegex(SystemExit, "package"):
            self.validate(wrong_package)

        empty_platforms = deepcopy(self.valid)
        empty_platforms["platforms"] = []
        with self.assertRaisesRegex(SystemExit, "nine platform"):
            self.validate(empty_platforms)

    def test_malformed_platform_fields_fail_cleanly_before_set_use(self) -> None:
        mutations = {
            "platform and arch must be strings": lambda platform: platform.update(
                {"platform": []}
            ),
            "unique artifact paths": lambda platform: platform.update(
                {"artifactPaths": [[]]}
            ),
            "unique allowed strings": lambda platform: platform.update(
                {"accelerators": [[]]}
            ),
        }
        for expected_error, mutate in mutations.items():
            with self.subTest(expected_error=expected_error):
                malformed = deepcopy(self.valid)
                mutate(malformed["platforms"][0])
                with self.assertRaisesRegex(SystemExit, expected_error):
                    self.validate(malformed)

    def test_path_only_artifact_and_unbound_provenance_fail_closed(self) -> None:
        path_only = deepcopy(self.valid)
        path_only["artifacts"][0] = {"path": path_only["artifacts"][0]["path"]}
        with self.assertRaisesRegex(SystemExit, "keys do not match"):
            self.validate(path_only)

        wrong_provenance = deepcopy(self.valid)
        wrong_provenance["artifacts"][0]["upstreamCommit"] = "0" * 40
        with self.assertRaisesRegex(SystemExit, "provenance mismatch"):
            self.validate(wrong_provenance)

        missing_override_target = deepcopy(self.valid)
        override = missing_override_target["upstream"]["prebuiltOverrides"][0]
        missing_override_target["artifacts"] = [
            artifact
            for artifact in missing_override_target["artifacts"]
            if artifact["path"] != override["targetPath"]
        ]
        for platform in missing_override_target["platforms"]:
            if override["targetPath"] in platform["artifactPaths"]:
                platform["artifactPaths"].remove(override["targetPath"])
        with self.assertRaisesRegex(SystemExit, "override target provenance"):
            self.validate(missing_override_target)

    def test_artifact_paths_require_normalized_posix_form(self) -> None:
        for unsafe in (r"bin\linux\x64\libLiteRtLm.so", "."):
            with self.subTest(path=unsafe):
                malformed = deepcopy(self.valid)
                malformed["artifacts"][0]["path"] = unsafe
                with self.assertRaisesRegex(SystemExit, "safe normalized"):
                    self.validate(malformed)

    def test_malformed_artifact_runtime_fails_before_set_membership(self) -> None:
        for malformed_runtime in ([], {}):
            with self.subTest(runtime=malformed_runtime):
                malformed = deepcopy(self.valid)
                malformed["artifacts"][0]["runtime"] = malformed_runtime
                with self.assertRaisesRegex(SystemExit, "invalid runtime family"):
                    self.validate(malformed)

    def test_required_runtime_path_must_keep_exact_platform_binding(self) -> None:
        misclassified = deepcopy(self.valid)
        required_path = "bin/macos/arm64/libLiteRtLm.dylib"
        artifact = next(
            item for item in misclassified["artifacts"] if item["path"] == required_path
        )
        artifact["runtime"] = "archive"
        artifact["platform"] = None
        artifact["arch"] = None
        platform = next(
            item
            for item in misclassified["platforms"]
            if item["platform"] == "macos" and item["arch"] == "arm64"
        )
        platform["artifactPaths"].remove(required_path)
        with self.assertRaisesRegex(SystemExit, "invalid runtime/platform/arch binding"):
            self.validate(misclassified)

    def test_accelerator_summaries_are_allowed_linked_unions(self) -> None:
        generic_gpu = deepcopy(self.valid)
        platform = next(
            item
            for item in generic_gpu["platforms"]
            if item["platform"] == "linux" and item["arch"] == "x64"
        )
        artifact = next(
            item
            for item in generic_gpu["artifacts"]
            if item["path"] in platform["artifactPaths"]
        )
        artifact["accelerators"] = ["gpu"]
        platform["accelerators"] = sorted(
            {
                accelerator
                for path in platform["artifactPaths"]
                for accelerator in next(
                    item
                    for item in generic_gpu["artifacts"]
                    if item["path"] == path
                )["accelerators"]
            }
        )
        self.validate(generic_gpu)

        fabricated = deepcopy(self.valid)
        platform = next(
            item
            for item in fabricated["platforms"]
            if item["platform"] == "linux" and item["arch"] == "x64"
        )
        artifact = next(
            item
            for item in fabricated["artifacts"]
            if item["path"] in platform["artifactPaths"]
        )
        artifact["accelerators"] = ["fabricated"]
        platform["accelerators"] = ["fabricated"]
        with self.assertRaisesRegex(SystemExit, "unique allowed values"):
            self.validate(fabricated)

        mismatched = deepcopy(self.valid)
        platform = next(
            item
            for item in mismatched["platforms"]
            if item["platform"] == "android" and item["arch"] == "arm64"
        )
        platform["accelerators"] = []
        with self.assertRaisesRegex(SystemExit, "do not match linked artifacts"):
            self.validate(mismatched)

    def test_bare_smoke_and_missing_source_or_expectation_fail_closed(self) -> None:
        bare = deepcopy(self.valid)
        bare["realModelSmokes"] = [
            {"platform": "linux", "arch": "x64", "result": "pass"}
        ]
        with self.assertRaisesRegex(SystemExit, "keys do not match"):
            self.validate(bare)

        for field in ("source", "expectation"):
            with self.subTest(field=field):
                incomplete = deepcopy(self.valid)
                del incomplete["realModelSmokes"][0][field]
                with self.assertRaisesRegex(SystemExit, "keys do not match"):
                    self.validate(incomplete)

    def test_smoke_evidence_is_bound_to_pinned_assets_and_runtime(self) -> None:
        wrong_model = deepcopy(self.valid)
        wrong_model["realModelSmokes"][0]["model"]["sha256"] = "a" * 64
        with self.assertRaisesRegex(SystemExit, "pinned smoke asset"):
            self.validate(wrong_model)

        wrong_source = deepcopy(self.valid)
        wrong_source["realModelSmokes"][0]["source"]["model"] = (
            "https://example.invalid/model.tflite"
        )
        with self.assertRaisesRegex(SystemExit, "immutable source provenance"):
            self.validate(wrong_source)

        wrong_library = deepcopy(self.valid)
        wrong_library["realModelSmokes"][0]["library"]["sha256"] = "b" * 64
        with self.assertRaisesRegex(SystemExit, "packaged runtime artifact"):
            self.validate(wrong_library)

        fabricated = deepcopy(self.valid)
        fabricated["realModelSmokes"][0]["expectation"]["value"] = "fabricated"
        fabricated["realModelSmokes"][0]["transcript"] = "fabricated"
        with self.assertRaisesRegex(SystemExit, "pinned transcript expectation"):
            self.validate(fabricated)

        with patch("validate_release_manifest.ASSETS", []):
            with self.assertRaisesRegex(
                SystemExit, "Pinned smoke asset configuration is incomplete"
            ):
                self.validate(deepcopy(self.valid))

    def test_incomplete_abi_capabilities_and_release_fail_closed(self) -> None:
        for section, field in (
            ("abi", "upstreamC"),
            ("capabilities", "streamChunkAccessors"),
            ("release", "githubPrerelease"),
        ):
            with self.subTest(section=section, field=field):
                incomplete = deepcopy(self.valid)
                del incomplete[section][field]
                with self.assertRaisesRegex(SystemExit, "keys do not match"):
                    self.validate(incomplete)

    def test_actual_v0_16_0_native_2_schema_1_metadata_remains_compatible(self) -> None:
        fixture = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "v0.16.0-native.2-manifest.json"
        )
        self.assertEqual(
            hashlib.sha256(fixture.read_bytes()).hexdigest(),
            "39da6bb0fb9591b6ed28ec0a5e2e934c8849e2eea9fb78f729249f83176b143f",
        )
        manifest = json.loads(fixture.read_text(encoding="utf-8"))
        tag = "v0.16.0-native.2"
        asset_names = {
            "manifest.json",
            "SHA256SUMS",
            f"litert-lm-native-prebuilts-{tag}.tar.gz",
            f"litert-lm-native-official-assets-{tag}.tar.gz",
            *(
                f"litert-lm-native-runtime-{platform}-{arch}-{tag}.tar.gz"
                for platform, arch in (
                    ("android", "arm64"),
                    ("android", "x64"),
                    ("ios", "arm64"),
                    ("ios", "arm64-sim"),
                    ("linux", "arm64"),
                    ("linux", "x64"),
                    ("macos", "arm64"),
                    ("macos", "x64"),
                    ("windows", "x64"),
                )
            ),
            *(
                Path(item["path"]).name
                for item in manifest["artifacts"]
                if item["path"].startswith(f"dist/spm/{tag}/")
                and item["path"].endswith(".zip")
            ),
        }
        with tempfile.TemporaryDirectory() as temp:
            release_metadata = Path(temp) / "release.json"
            release_metadata.write_text(
                json.dumps({"assets": [{"name": name} for name in asset_names]}),
                encoding="utf-8",
            )
            argv = [
                "validate_release_manifest.py",
                str(fixture),
                "--upstream-tag",
                "v0.16.0",
                "--release-tag",
                tag,
                "--release-metadata",
                str(release_metadata),
            ]
            with patch.object(sys, "argv", argv):
                self.assertEqual(main(), 0)


if __name__ == "__main__":
    unittest.main()
