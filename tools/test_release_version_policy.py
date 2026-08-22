from __future__ import annotations

import unittest
from pathlib import Path

from release_version_policy import (
    PolicyError,
    development_tag_for,
    parse_release_tag,
    parse_upstream,
    validate_history,
    validate_pair,
)


COMMIT = "ba82499873945908bf8bcfc96e955d0677eb1fa1"


class ReleaseVersionPolicyTest(unittest.TestCase):
    def test_scheduled_workflow_is_detection_only(self) -> None:
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/auto_upstream_release.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("contents: read", workflow)
        self.assertIn("preparation.json", workflow)
        self.assertNotIn("gh workflow run", workflow)
        self.assertNotIn("gh release create", workflow)
        self.assertNotIn("contents: write", workflow)

    def test_release_workflow_requires_exact_identity_and_approval(self) -> None:
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/native_release.yml").read_text(
            encoding="utf-8"
        )
        for required_input in (
            "release_tag:",
            "upstream_commit:",
            "upstream_compatibility_tag:",
            "native_commit:",
            "correlation_id:",
            "publication_approval:",
        ):
            self.assertIn(required_input, workflow)
        self.assertIn("publication_approval == 'publish'", workflow)
        self.assertIn("Invalid correlation identifier", workflow)
        self.assertIn("github.run_id", workflow)
        self.assertIn("--draft", workflow)
        self.assertIn("--require-smoke linux/x64", workflow)
        self.assertIn("--require-smoke windows/x64", workflow)

    def test_stable_and_compact_rebuild(self) -> None:
        upstream = parse_upstream(
            upstream_tag="v0.16.1",
            upstream_commit=COMMIT,
            compatibility_tag="v0.16.1",
        )
        stable = validate_pair(upstream, "v0.16.1")
        rebuild = validate_pair(upstream, "v0.16.1-1")
        self.assertFalse(stable.github_prerelease)
        self.assertTrue(rebuild.github_prerelease)

    def test_development_identity_is_commit_based(self) -> None:
        upstream = parse_upstream(
            upstream_tag="",
            upstream_commit=COMMIT,
            compatibility_tag="v0.16.1",
        )
        self.assertEqual(development_tag_for(COMMIT), "gba8249987394")
        development = validate_pair(upstream, "gba8249987394")
        rebuild = validate_pair(upstream, "gba8249987394-2")
        self.assertEqual(development.channel, "development")
        self.assertEqual(development.kind, "commit")
        self.assertEqual(rebuild.rebuild, 2)
        self.assertTrue(development.github_prerelease)

    def test_legacy_native_suffix_is_read_only_but_counts_for_order(self) -> None:
        legacy = parse_release_tag("v0.16.0-native.2")
        self.assertTrue(legacy.legacy)
        candidate = parse_release_tag("v0.16.0-3")
        validate_history(candidate, ["v0.16.0", "v0.16.0-native.2"])
        with self.assertRaisesRegex(PolicyError, "greater than 2"):
            validate_history(
                parse_release_tag("v0.16.0-1"),
                ["v0.16.0", "v0.16.0-native.2"],
            )

    def test_rebuild_requires_aligned_immediate_predecessor(self) -> None:
        with self.assertRaisesRegex(PolicyError, "orphan stable rebuild"):
            validate_history(parse_release_tag("v0.17.0-1"), ["v0.16.0"])
        with self.assertRaisesRegex(PolicyError, "predecessor rebuild 1"):
            validate_history(
                parse_release_tag("v0.16.0-2"),
                ["v0.16.0"],
            )
        validate_history(
            parse_release_tag("v0.16.0-3"),
            ["v0.16.0", "v0.16.0-native.2"],
        )

        with self.assertRaisesRegex(PolicyError, "orphan development rebuild"):
            validate_history(parse_release_tag("gba8249987394-1"), [])
        with self.assertRaisesRegex(PolicyError, "predecessor rebuild 1"):
            validate_history(
                parse_release_tag("gba8249987394-2"),
                ["gba8249987394"],
            )
        validate_history(
            parse_release_tag("gba8249987394-2"),
            ["gba8249987394", "gba8249987394-1"],
        )

    def test_collision_and_rollback_are_rejected(self) -> None:
        with self.assertRaisesRegex(PolicyError, "collision"):
            validate_history(parse_release_tag("v0.16.1"), ["v0.16.1"])
        with self.assertRaisesRegex(PolicyError, "rollback"):
            validate_history(parse_release_tag("v0.15.1"), ["v0.16.0"])
        with self.assertRaisesRegex(PolicyError, "greater than 1"):
            validate_history(
                parse_release_tag("gba8249987394"), ["gba8249987394-1"]
            )

    def test_invalid_or_mismatched_identities_are_rejected(self) -> None:
        stable = parse_upstream(
            upstream_tag="v0.16.1",
            upstream_commit=COMMIT,
            compatibility_tag="v0.16.1",
        )
        development = parse_upstream(
            upstream_tag="",
            upstream_commit=COMMIT,
            compatibility_tag="v0.16.1",
        )
        invalid_pairs = (
            (stable, "v0.16.0"),
            (stable, "v0.16.1-native.3"),
            (stable, "gba8249987394"),
            (development, "v0.16.1"),
            (development, "gba8249987395"),
        )
        for upstream, tag in invalid_pairs:
            with self.subTest(tag=tag):
                with self.assertRaises(PolicyError):
                    validate_pair(upstream, tag)

        with self.assertRaises(PolicyError):
            parse_upstream(
                upstream_tag="v0.16.1-rc.1",
                upstream_commit=COMMIT,
                compatibility_tag="v0.16.1",
            )
        with self.assertRaises(PolicyError):
            development_tag_for(COMMIT[:12])


if __name__ == "__main__":
    unittest.main()
