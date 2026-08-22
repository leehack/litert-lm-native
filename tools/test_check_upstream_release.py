from __future__ import annotations

import unittest

from check_upstream_release import evaluate_release
from validate_runtime_artifacts import OFFICIAL_APPLE_RUNTIME_ARCHIVES


def metadata(tag: str, commit: str, assets: tuple[str, ...]) -> dict:
    return {
        "tag": tag,
        "commit": commit,
        "assets": [{"name": name} for name in assets],
    }


class CheckUpstreamReleaseTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
