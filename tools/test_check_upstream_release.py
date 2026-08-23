from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from check_upstream_release import evaluate_release, main
from validate_runtime_artifacts import OFFICIAL_APPLE_RUNTIME_ARCHIVES


COMMIT = "924e79c91542761242244e4f1651851f822e4cbb"


def metadata(tag: str, commit: str, assets: tuple[str, ...]) -> dict:
    return {
        "tag": tag,
        "commit": commit,
        "assets": [{"name": name} for name in assets],
    }


class CheckUpstreamReleaseTest(unittest.TestCase):
    def test_malformed_candidate_fails_without_a_traceback_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            candidate = Path(temp) / "candidate.json"
            candidate.write_text("{", encoding="utf-8")
            with patch(
                "sys.argv",
                [
                    "check_upstream_release.py",
                    "--candidate",
                    str(candidate),
                    "--native-repository",
                    "leehack/litert-lm-native",
                ],
            ):
                with self.assertRaises(SystemExit):
                    main()

    def test_skips_same_commit_metadata_only_release(self) -> None:
        decision = evaluate_release(
            metadata("v0.16.1", "same-commit", ("litert_lm_main.macos_arm64",)),
            {"tag": "v0.16.0", "commit": "same-commit"},
        )

        self.assertFalse(decision["shouldPrepare"])
        self.assertEqual(decision["reason"], "same_upstream_commit")
        self.assertEqual(
            decision["missingAssets"], sorted(OFFICIAL_APPLE_RUNTIME_ARCHIVES)
        )

    def test_skips_new_commit_missing_required_official_assets(self) -> None:
        decision = evaluate_release(
            metadata("v0.17.0", "new-commit", ("CLiteRTLM.xcframework.zip",)),
            {"tag": "v0.16.0", "commit": "old-commit"},
        )

        self.assertFalse(decision["shouldPrepare"])
        self.assertEqual(decision["reason"], "missing_required_official_assets")
        self.assertEqual(
            decision["missingAssets"], ["CLiteRTLM_mac.xcframework.zip"]
        )

    def test_allows_newer_runtime_release_with_required_assets(self) -> None:
        decision = evaluate_release(
            metadata("v0.17.0", "new-commit", OFFICIAL_APPLE_RUNTIME_ARCHIVES),
            {"tag": "v0.16.0", "commit": "old-commit"},
        )

        self.assertTrue(decision["shouldPrepare"])
        self.assertEqual(decision["reason"], "ready")
        self.assertEqual(decision["missingAssets"], [])
        self.assertEqual(decision["preparation"]["releaseTag"], "v0.17.0")
        self.assertEqual(
            decision["preparation"]["publicationApproval"], "prepare-only"
        )

    def test_explicit_rebuild_may_reuse_commit_but_still_requires_assets(self) -> None:
        decision = evaluate_release(
            metadata("v0.16.0", COMMIT, OFFICIAL_APPLE_RUNTIME_ARCHIVES),
            {"tag": "v0.16.0", "commit": COMMIT},
            allow_same_commit=True,
            release_tag="v0.16.0-3",
        )
        self.assertTrue(decision["shouldPrepare"])
        self.assertEqual(decision["preparation"]["releaseTag"], "v0.16.0-3")
        self.assertNotEqual(
            decision["preparation"]["releaseTag"], decision["candidate"]["tag"]
        )

        blocked = evaluate_release(
            metadata("v0.16.0", COMMIT, ("CLiteRTLM.xcframework.zip",)),
            {"tag": "v0.16.0", "commit": COMMIT},
            allow_same_commit=True,
            release_tag="v0.16.0-3",
        )
        self.assertFalse(blocked["shouldPrepare"])
        self.assertEqual(blocked["reason"], "missing_required_official_assets")

        missing_tag = evaluate_release(
            metadata("v0.16.0", COMMIT, OFFICIAL_APPLE_RUNTIME_ARCHIVES),
            {"tag": "v0.16.0", "commit": COMMIT},
            allow_same_commit=True,
        )
        self.assertFalse(missing_tag["shouldPrepare"])
        self.assertEqual(missing_tag["reason"], "exact_rebuild_tag_required")
        self.assertIsNone(missing_tag["preparation"])

        with self.assertRaisesRegex(ValueError, "native rebuild tag"):
            evaluate_release(
                metadata("v0.16.0", COMMIT, OFFICIAL_APPLE_RUNTIME_ARCHIVES),
                {"tag": "v0.16.0", "commit": COMMIT},
                allow_same_commit=True,
                release_tag="v0.16.0",
            )


if __name__ == "__main__":
    unittest.main()
