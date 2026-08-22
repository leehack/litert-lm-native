from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from generate_schema2_contract_fixture import (
    NATIVE_COMMIT,
    RELEASE_TAG,
    UPSTREAM_COMMIT,
    UPSTREAM_TAG,
    generate_manifest,
)
from validate_release_manifest import main, validate_schema_2_payload


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

    def test_owner_generated_manifest_satisfies_final_contract(self) -> None:
        self.validate(deepcopy(self.valid))

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

    def test_wrong_package_and_incomplete_platforms_fail_closed(self) -> None:
        wrong_package = deepcopy(self.valid)
        wrong_package["package"] = "lookalike"
        with self.assertRaisesRegex(SystemExit, "package"):
            self.validate(wrong_package)

        empty_platforms = deepcopy(self.valid)
        empty_platforms["platforms"] = []
        with self.assertRaisesRegex(SystemExit, "nine platform"):
            self.validate(empty_platforms)

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
