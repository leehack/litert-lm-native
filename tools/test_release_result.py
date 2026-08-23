from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from publication_state import release_notes
from release_result import build_result, load_json_object, main, validate_published_result


UPSTREAM = "924e79c91542761242244e4f1651851f822e4cbb"
NATIVE = "451ba0ce7c366972b4dc0e58f08ffe590958f943"


class ReleaseResultTest(unittest.TestCase):
    def manifest(self) -> dict:
        return {
            "schemaVersion": 2,
            "release": {"tag": "v0.16.0-3", "githubPrerelease": True},
            "upstream": {
                "tag": "v0.16.0",
                "commit": UPSTREAM,
                "compatibilityTag": "v0.16.0",
            },
            "native": {"commit": NATIVE},
            "platforms": [{"platform": "linux", "arch": "x64"}],
            "artifacts": [{"path": "bin/linux/x64/libLiteRtLm.so"}],
            "realModelSmokes": [
                {"platform": "linux", "arch": "x64", "result": "pass"}
            ],
        }

    def test_result_binds_correlation_run_inputs_and_release_digests(self) -> None:
        result = build_result(
            manifest=self.manifest(),
            correlation_id="llamadart-42-1",
            repository="leehack/litert-lm-native",
            run_id=42,
            run_attempt=1,
            run_url="https://github.com/leehack/litert-lm-native/actions/runs/42",
            approval="publish",
            outcome="validated-for-publication",
            release_tag="v0.16.0-3",
            upstream_tag="v0.16.0",
            upstream_commit=UPSTREAM,
            compatibility_tag="v0.16.0",
            native_commit=NATIVE,
            candidate_artifact="release-candidate-v0.16.0-3-llamadart-42-1",
            release_metadata={
                "id": 7,
                "html_url": "https://github.com/example/releases/tag/v0.16.0-3",
                "tag_name": "v0.16.0-3",
                "target_commitish": NATIVE,
                "name": "LiteRT-LM v0.16.0-3",
                "body": release_notes(
                    release_tag="v0.16.0-3",
                    upstream_tag="v0.16.0",
                    upstream_commit=UPSTREAM,
                    compatibility_tag="v0.16.0",
                    native_commit=NATIVE,
                    correlation_id="llamadart-42-1",
                    workflow_run_id=42,
                ),
                "draft": True,
                "prerelease": True,
                "assets": [
                    {"name": "manifest.json", "digest": "sha256:" + "a" * 64},
                    {"name": "release-result.json", "digest": "sha256:" + "b" * 64},
                ],
            },
        )
        self.assertEqual(result["correlationId"], "llamadart-42-1")
        self.assertEqual(result["workflow"]["runId"], 42)
        self.assertEqual(result["release"]["id"], 7)
        self.assertEqual(
            result["release"]["assetDigests"]["manifest.json"],
            "sha256:" + "a" * 64,
        )

    def test_invalid_correlation_and_missing_digest_are_rejected(self) -> None:
        common = dict(
            manifest=self.manifest(),
            repository="leehack/litert-lm-native",
            run_id=42,
            run_attempt=1,
            run_url="https://github.com/leehack/litert-lm-native/actions/runs/42",
            approval="publish",
            outcome="validated-for-publication",
            release_tag="v0.16.0-3",
            upstream_tag="v0.16.0",
            upstream_commit=UPSTREAM,
            compatibility_tag="v0.16.0",
            native_commit=NATIVE,
            candidate_artifact="candidate",
        )
        with self.assertRaisesRegex(ValueError, "correlation"):
            build_result(correlation_id="bad value", **common)
        for section in ("release", "upstream", "native"):
            with self.subTest(section=section):
                malformed = self.manifest()
                malformed[section] = []
                with self.assertRaisesRegex(
                    ValueError, f"manifest {section} must be an object"
                ):
                    build_result(
                        correlation_id="valid",
                        **{**common, "manifest": malformed},
                    )
        with self.assertRaisesRegex(ValueError, "digests"):
            build_result(
                correlation_id="valid",
                release_metadata={
                    "id": 7,
                    "html_url": "https://example.invalid/release/7",
                    "tag_name": "v0.16.0-3",
                    "target_commitish": NATIVE,
                    "name": "LiteRT-LM v0.16.0-3",
                    "body": release_notes(
                        release_tag="v0.16.0-3",
                        upstream_tag="v0.16.0",
                        upstream_commit=UPSTREAM,
                        compatibility_tag="v0.16.0",
                        native_commit=NATIVE,
                        correlation_id="valid",
                        workflow_run_id=42,
                    ),
                    "draft": True,
                    "prerelease": True,
                    "assets": [{"name": "manifest.json", "digest": None}],
                },
                **common,
            )
        mismatched = {
            "id": 7,
            "html_url": "https://example.invalid/release/7",
            "tag_name": "wrong",
            "target_commitish": NATIVE,
            "name": "LiteRT-LM v0.16.0-3",
            "body": "wrong",
            "draft": False,
            "prerelease": True,
            "assets": [],
        }
        with self.assertRaisesRegex(ValueError, "exact transaction"):
            build_result(
                correlation_id="valid",
                release_metadata=mismatched,
                **common,
            )

    def test_exact_published_result_is_terminal_and_mismatch_rejects(self) -> None:
        metadata = {
            "id": 7,
            "html_url": "https://example.invalid/release/7",
            "tag_name": "v0.16.0-3",
            "target_commitish": NATIVE,
            "name": "LiteRT-LM v0.16.0-3",
            "body": release_notes(
                release_tag="v0.16.0-3",
                upstream_tag="v0.16.0",
                upstream_commit=UPSTREAM,
                compatibility_tag="v0.16.0",
                native_commit=NATIVE,
                correlation_id="valid",
                workflow_run_id=42,
            ),
            "draft": True,
            "prerelease": True,
            "assets": [
                {"name": "manifest.json", "digest": "sha256:" + "a" * 64},
                {"name": "release-result.json", "digest": "sha256:" + "b" * 64},
            ],
        }
        result = build_result(
            manifest=self.manifest(),
            correlation_id="valid",
            repository="leehack/litert-lm-native",
            run_id=42,
            run_attempt=1,
            run_url="https://github.com/leehack/litert-lm-native/actions/runs/42",
            approval="publish",
            outcome="validated-for-publication",
            release_tag="v0.16.0-3",
            upstream_tag="v0.16.0",
            upstream_commit=UPSTREAM,
            compatibility_tag="v0.16.0",
            native_commit=NATIVE,
            candidate_artifact="candidate",
            release_metadata=metadata,
        )
        metadata["draft"] = False
        validate_published_result(
            result,
            manifest=self.manifest(),
            correlation_id="valid",
            repository="leehack/litert-lm-native",
            release_tag="v0.16.0-3",
            upstream_tag="v0.16.0",
            upstream_commit=UPSTREAM,
            compatibility_tag="v0.16.0",
            native_commit=NATIVE,
            candidate_artifact="candidate",
            release_metadata=metadata,
        )
        result["correlationId"] = "wrong"
        with self.assertRaisesRegex(ValueError, "exact transaction"):
            validate_published_result(
                result,
                manifest=self.manifest(),
                correlation_id="valid",
                repository="leehack/litert-lm-native",
                release_tag="v0.16.0-3",
                upstream_tag="v0.16.0",
                upstream_commit=UPSTREAM,
                compatibility_tag="v0.16.0",
                native_commit=NATIVE,
                candidate_artifact="candidate",
                release_metadata=metadata,
            )
        result["correlationId"] = "valid"
        result["workflow"]["url"] = "https://example.invalid/run/42"
        with self.assertRaisesRegex(ValueError, "workflow URL"):
            validate_published_result(
                result,
                manifest=self.manifest(),
                correlation_id="valid",
                repository="leehack/litert-lm-native",
                release_tag="v0.16.0-3",
                upstream_tag="v0.16.0",
                upstream_commit=UPSTREAM,
                compatibility_tag="v0.16.0",
                native_commit=NATIVE,
                candidate_artifact="candidate",
                release_metadata=metadata,
            )

    def test_release_json_errors_are_clean_and_actionable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            malformed = root / "malformed.json"
            malformed.write_text("{", encoding="utf-8")
            non_utf8 = root / "non-utf8.json"
            non_utf8.write_bytes(b"\xff")
            missing = root / "missing.json"
            for path in (malformed, non_utf8, missing):
                with self.subTest(path=path.name):
                    with self.assertRaisesRegex(
                        ValueError, "release manifest must be valid UTF-8 JSON"
                    ):
                        load_json_object(path, label="release manifest")

            output = root / "result.json"
            with patch(
                "sys.argv",
                [
                    "release_result.py",
                    "--manifest",
                    str(malformed),
                    "--correlation-id",
                    "valid",
                    "--repository",
                    "leehack/litert-lm-native",
                    "--run-id",
                    "42",
                    "--run-attempt",
                    "1",
                    "--run-url",
                    "https://github.com/leehack/litert-lm-native/actions/runs/42",
                    "--approval",
                    "publish",
                    "--outcome",
                    "validated-for-publication",
                    "--release-tag",
                    "v0.16.0-3",
                    "--upstream-tag",
                    "v0.16.0",
                    "--upstream-commit",
                    UPSTREAM,
                    "--compatibility-tag",
                    "v0.16.0",
                    "--native-commit",
                    NATIVE,
                    "--candidate-artifact",
                    "candidate",
                    "--output",
                    str(output),
                ],
            ):
                with self.assertRaisesRegex(
                    SystemExit, "release manifest must be valid UTF-8 JSON"
                ):
                    main()

if __name__ == "__main__":
    unittest.main()
