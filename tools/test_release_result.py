from __future__ import annotations

import unittest

from release_result import build_result


UPSTREAM = "924e79c91542761242244e4f1651851f822e4cbb"
NATIVE = "451ba0ce7c366972b4dc0e58f08ffe590958f943"


class ReleaseResultTest(unittest.TestCase):
    def manifest(self) -> dict:
        return {
            "schemaVersion": 2,
            "release": {"tag": "v0.16.0-3"},
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
                "draft": True,
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
            run_url="https://example.invalid/run/42",
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
        with self.assertRaisesRegex(ValueError, "digests"):
            build_result(
                correlation_id="valid",
                release_metadata={
                    "id": 7,
                    "html_url": "https://example.invalid/release/7",
                    "draft": True,
                    "assets": [{"name": "manifest.json", "digest": None}],
                },
                **common,
            )


if __name__ == "__main__":
    unittest.main()
