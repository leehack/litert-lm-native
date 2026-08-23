from __future__ import annotations

from copy import deepcopy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import package_release
import validate_artifacts
from release_version_policy import PolicyError


UPSTREAM_COMMIT = "924e79c91542761242244e4f1651851f822e4cbb"
NATIVE_COMMIT = "451ba0ce7c366972b4dc0e58f08ffe590958f943"


class PackageReleaseTest(unittest.TestCase):
    def test_official_assets_must_match_stable_or_development_identity(self) -> None:
        contradictions = (
            ("v0.16.0", "v0.16.0-3", False),
            (None, f"g{UPSTREAM_COMMIT[:12]}", True),
        )
        for upstream_tag, release_tag, official_assets in contradictions:
            with self.subTest(upstream_tag=upstream_tag):
                with self.assertRaisesRegex(
                    ValueError,
                    "must be true for stable releases and false for development",
                ):
                    package_release.build_manifest(
                        upstream_tag=upstream_tag,
                        upstream_commit=UPSTREAM_COMMIT,
                        compatibility_tag="v0.16.0",
                        release_tag=release_tag,
                        native_commit=NATIVE_COMMIT,
                        official_upstream_assets=official_assets,
                    )

    def test_current_native_commit_reports_git_failures_cleanly(self) -> None:
        failures = (
            OSError("git is unavailable"),
            subprocess.CalledProcessError(
                128,
                ["git", "rev-parse", "HEAD"],
                stderr="fatal: not a git repository",
            ),
        )
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                with patch.object(
                    package_release.subprocess,
                    "check_output",
                    side_effect=failure,
                ):
                    with self.assertRaisesRegex(
                        ValueError,
                        "could not determine the native commit",
                    ):
                        package_release.current_native_commit()

    def test_main_reports_policy_and_evidence_failures_cleanly(self) -> None:
        arguments = [
            "package_release.py",
            "--upstream-tag",
            "v0.16.0",
            "--upstream-commit",
            UPSTREAM_COMMIT,
            "--compatibility-tag",
            "v0.16.0",
            "--release-tag",
            "v0.16.0-3",
            "--native-commit",
            NATIVE_COMMIT,
        ]
        failures = (
            PolicyError("release identity mismatch"),
            ValueError("smoke evidence mismatch"),
        )
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                with (
                    patch.object(sys, "argv", arguments),
                    patch.object(
                        package_release,
                        "build_manifest",
                        side_effect=failure,
                    ),
                ):
                    with self.assertRaisesRegex(
                        SystemExit,
                        f"Release manifest generation failed: {failure}",
                    ):
                        package_release.main()

    def test_manifest_and_artifact_shapes_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = root / "manifest.json"
            with (
                patch.object(validate_artifacts, "REPO_ROOT", root),
                patch.object(validate_artifacts, "MANIFEST_PATH", manifest),
            ):
                manifest.write_text("[]", encoding="utf-8")
                with self.assertRaisesRegex(SystemExit, "JSON object"):
                    validate_artifacts.validate_manifest()

                manifest.write_text(
                    json.dumps(
                        {
                            "schemaVersion": 1,
                            "package": "litert-lm-native",
                            "artifacts": [None],
                        }
                    ),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(SystemExit, r"artifact\[0\] must be an object"):
                    validate_artifacts.validate_manifest()

                base_artifact = {
                    "runtime": "native",
                    "platform": "linux",
                    "path": "runtime.so",
                    "fileName": "runtime.so",
                    "sha256": "0" * 64,
                }
                for unsafe_path in (
                    None,
                    [],
                    "",
                    ".",
                    "../runtime.so",
                    "/runtime.so",
                    "dir\\runtime.so",
                ):
                    with self.subTest(unsafe_path=unsafe_path):
                        artifact = dict(base_artifact)
                        artifact["path"] = unsafe_path
                        manifest.write_text(
                            json.dumps(
                                {
                                    "schemaVersion": 1,
                                    "package": "litert-lm-native",
                                    "artifacts": [artifact],
                                }
                            ),
                            encoding="utf-8",
                        )
                        with self.assertRaisesRegex(
                            SystemExit,
                            "safe normalized repository-relative path",
                        ):
                            validate_artifacts.validate_manifest()

    def test_schema_2_commit_rejects_non_hex_before_artifact_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schemaVersion": 2,
                        "package": "litert-lm-native",
                        "release": {},
                        "upstream": {"commit": "z" * 40},
                        "native": {"commit": NATIVE_COMMIT},
                        "abi": {},
                        "capabilities": {},
                        "platforms": [],
                        "realModelSmokes": [],
                        "artifacts": [],
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.object(validate_artifacts, "REPO_ROOT", root),
                patch.object(validate_artifacts, "MANIFEST_PATH", manifest),
            ):
                with self.assertRaisesRegex(SystemExit, "lowercase 40-hex SHA"):
                    validate_artifacts.validate_manifest()

    def test_schema_2_section_types_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = root / "manifest.json"
            valid = {
                "schemaVersion": 2,
                "package": "litert-lm-native",
                "release": {},
                "upstream": {"commit": UPSTREAM_COMMIT},
                "native": {"commit": NATIVE_COMMIT},
                "abi": {},
                "capabilities": {},
                "platforms": [],
                "realModelSmokes": [],
                "artifacts": [],
            }
            with (
                patch.object(validate_artifacts, "REPO_ROOT", root),
                patch.object(validate_artifacts, "MANIFEST_PATH", manifest),
            ):
                for section in (
                    "release",
                    "upstream",
                    "native",
                    "abi",
                    "capabilities",
                ):
                    with self.subTest(section=section):
                        malformed = deepcopy(valid)
                        malformed[section] = []
                        manifest.write_text(json.dumps(malformed), encoding="utf-8")
                        with self.assertRaisesRegex(
                            SystemExit, f"{section} must be an object"
                        ):
                            validate_artifacts.validate_manifest()

                for section in ("platforms", "realModelSmokes"):
                    with self.subTest(section=section):
                        malformed = deepcopy(valid)
                        malformed[section] = {}
                        manifest.write_text(json.dumps(malformed), encoding="utf-8")
                        with self.assertRaisesRegex(
                            SystemExit, f"{section} must be a list"
                        ):
                            validate_artifacts.validate_manifest()

    def test_generic_gpu_accelerator_is_schema_compatible(self) -> None:
        self.assertEqual(
            package_release.artifact_accelerators(
                Path("libLiteRtGpuAccelerator.so")
            ),
            ["gpu"],
        )

    def test_artifact_digest_rejects_non_hex_before_checksum_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            artifact = root / "runtime.so"
            artifact.write_bytes(b"runtime")
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "package": "litert-lm-native",
                        "artifacts": [
                            {
                                "runtime": "native",
                                "platform": "linux",
                                "path": "runtime.so",
                                "fileName": "runtime.so",
                                "sha256": "z" * 64,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.object(validate_artifacts, "REPO_ROOT", root),
                patch.object(validate_artifacts, "MANIFEST_PATH", manifest),
            ):
                with self.assertRaisesRegex(SystemExit, "64-hex digest"):
                    validate_artifacts.validate_manifest()

    def test_manifest_separates_all_release_identities_and_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bin_dir = root / "bin"
            library = bin_dir / "linux" / "x64" / "libLiteRtLm.so"
            library.parent.mkdir(parents=True)
            library.write_bytes(b"runtime")
            evidence_dir = root / "evidence"
            evidence_dir.mkdir()
            (evidence_dir / "linux-x64.json").write_text(
                json.dumps(
                    {
                        "id": "litert_lm_asr_moonshine",
                        "result": "pass",
                        "platform": "linux",
                        "arch": "x64",
                        "upstreamCommit": UPSTREAM_COMMIT,
                        "nativeCommit": NATIVE_COMMIT,
                        "backend": "cpu",
                        "abiVersion": 1,
                        "library": {"fileName": "lib.so", "sha256": "1" * 64},
                        "model": {"fileName": "model.tflite", "sha256": "2" * 64},
                        "tokenizer": {"fileName": "tokenizer.json", "sha256": "3" * 64},
                        "fixture": {
                            "fileName": "audio.wav",
                            "sha256": "4" * 64,
                            "sampleRateHz": 16000,
                            "sampleCount": 1,
                        },
                        "source": {
                            "runtimeReleaseAsset": "litert-lm-native-runtime-linux-x64-v0.16.0-3.tar.gz",
                            "model": "https://example.invalid/model",
                            "tokenizer": "https://example.invalid/tokenizer",
                            "fixture": "https://example.invalid/fixture",
                        },
                        "expectation": {
                            "type": "case-insensitive-substring",
                            "value": "how are you",
                        },
                        "transcript": "how are you doing",
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.object(package_release, "REPO_ROOT", root),
                patch.object(package_release, "BIN_DIR", bin_dir),
                patch.object(package_release, "WEB_DIST_DIR", root / "web"),
                patch.object(package_release, "DIST_DIR", root / "dist"),
                patch.object(package_release, "SHA256SUMS_PATH", root / "SHA256SUMS"),
            ):
                manifest = package_release.build_manifest(
                    upstream_tag="v0.16.0",
                    upstream_commit=UPSTREAM_COMMIT,
                    compatibility_tag="v0.16.0",
                    release_tag="v0.16.0-3",
                    native_commit=NATIVE_COMMIT,
                    evidence_dir=evidence_dir,
                    official_upstream_assets=True,
                )

        self.assertEqual(manifest["schemaVersion"], 2)
        self.assertEqual(manifest["release"]["tag"], "v0.16.0-3")
        self.assertEqual(manifest["upstream"]["tag"], "v0.16.0")
        self.assertEqual(manifest["upstream"]["commit"], UPSTREAM_COMMIT)
        self.assertEqual(manifest["native"]["commit"], NATIVE_COMMIT)
        self.assertEqual(manifest["abi"]["asrBridge"], 1)
        self.assertEqual(manifest["platforms"][0]["platform"], "linux")
        self.assertEqual(
            manifest["platforms"][0]["releaseAsset"],
            "litert-lm-native-runtime-linux-x64-v0.16.0-3.tar.gz",
        )
        self.assertEqual(len(manifest["realModelSmokes"]), 1)
        self.assertEqual(
            manifest["artifacts"][0]["sha256"],
            "d92c6a81b2ff50096bcda80885427d1f59a25b5f483f7055523504925d16ab23",
        )

    def test_evidence_must_match_exact_source_commits(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            evidence_dir = Path(temp)
            (evidence_dir / "bad.json").write_text(
                json.dumps(
                    {
                        "id": "litert_lm_asr_moonshine",
                        "result": "pass",
                        "platform": "linux",
                        "arch": "x64",
                        "upstreamCommit": "0" * 40,
                        "nativeCommit": NATIVE_COMMIT,
                        "backend": "cpu",
                        "abiVersion": 1,
                        "library": {"fileName": "lib.so", "sha256": "1" * 64},
                        "model": {"fileName": "model.tflite", "sha256": "2" * 64},
                        "tokenizer": {"fileName": "tokenizer.json", "sha256": "3" * 64},
                        "fixture": {
                            "fileName": "audio.wav",
                            "sha256": "4" * 64,
                            "sampleRateHz": 16000,
                            "sampleCount": 1,
                        },
                        "source": {
                            "runtimeReleaseAsset": "litert-lm-native-runtime-linux-x64-v0.16.0-3.tar.gz",
                            "model": "https://example.invalid/model",
                            "tokenizer": "https://example.invalid/tokenizer",
                            "fixture": "https://example.invalid/fixture",
                        },
                        "expectation": {
                            "type": "case-insensitive-substring",
                            "value": "how are you",
                        },
                        "transcript": "how are you doing",
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "upstream commit mismatch"):
                package_release.load_smoke_evidence(
                    evidence_dir,
                    upstream_commit=UPSTREAM_COMMIT,
                    native_commit=NATIVE_COMMIT,
                    release_tag="v0.16.0-3",
                )

    def test_smoke_evidence_json_errors_are_clean_and_actionable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            evidence_dir = Path(temp)
            malformed = evidence_dir / "malformed.json"
            malformed.write_text("{", encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError, "smoke evidence must be valid UTF-8 JSON"
            ):
                package_release.load_smoke_evidence(
                    evidence_dir,
                    upstream_commit=UPSTREAM_COMMIT,
                    native_commit=NATIVE_COMMIT,
                    release_tag="v0.16.0-3",
                )

            malformed.unlink()
            non_utf8 = evidence_dir / "non-utf8.json"
            non_utf8.write_bytes(b"\xff")
            with self.assertRaisesRegex(
                ValueError, "smoke evidence must be valid UTF-8 JSON"
            ):
                package_release.load_smoke_evidence(
                    evidence_dir,
                    upstream_commit=UPSTREAM_COMMIT,
                    native_commit=NATIVE_COMMIT,
                    release_tag="v0.16.0-3",
                )

            with patch.object(Path, "read_text", side_effect=OSError("unavailable")):
                with self.assertRaisesRegex(
                    ValueError, "smoke evidence must be valid UTF-8 JSON"
                ):
                    package_release.load_smoke_evidence(
                        evidence_dir,
                        upstream_commit=UPSTREAM_COMMIT,
                        native_commit=NATIVE_COMMIT,
                        release_tag="v0.16.0-3",
                    )

    def test_smoke_evidence_rejects_symlinked_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            evidence_dir = root / "evidence"
            evidence_dir.mkdir()
            outside = root / "outside.json"
            outside.write_text("{}", encoding="utf-8")
            linked = evidence_dir / "linked.json"
            try:
                linked.symlink_to(outside)
            except OSError as error:
                self.skipTest(f"symlinks unavailable: {error}")
            with self.assertRaisesRegex(ValueError, "regular non-symlink file"):
                package_release.load_smoke_evidence(
                    evidence_dir,
                    upstream_commit=UPSTREAM_COMMIT,
                    native_commit=NATIVE_COMMIT,
                    release_tag="v0.16.0-3",
                )

    def test_smoke_evidence_rejects_symlinked_or_non_directory_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            outside = root / "outside"
            outside.mkdir()
            linked = root / "linked-evidence"
            try:
                linked.symlink_to(outside, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"symlinks unavailable: {error}")
            evidence_file = root / "evidence.json"
            evidence_file.write_text("{}", encoding="utf-8")

            for evidence_root in (linked, evidence_file):
                with self.subTest(evidence_root=evidence_root.name):
                    with self.assertRaisesRegex(
                        ValueError,
                        "smoke evidence directory must be a non-symlink directory",
                    ):
                        package_release.load_smoke_evidence(
                            evidence_root,
                            upstream_commit=UPSTREAM_COMMIT,
                            native_commit=NATIVE_COMMIT,
                            release_tag="v0.16.0-3",
                        )


if __name__ == "__main__":
    unittest.main()
