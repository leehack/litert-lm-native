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
        self.assertIn("persist-credentials: false", workflow)
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
        self.assertIn('test "$GITHUB_SHA" = "$NATIVE_COMMIT"', workflow)
        self.assertIn("github.run_id", workflow)
        self.assertIn("--draft", workflow)
        self.assertIn("--require-smoke linux/x64", workflow)
        self.assertIn("--require-smoke windows/x64", workflow)
        self.assertGreaterEqual(workflow.count("--tag-ref"), 4)
        self.assertEqual(workflow.count("--candidate-dir candidate"), 2)
        self.assertIn(
            "--release-result published-release-check/release-result.json",
            workflow,
        )
        self.assertGreaterEqual(workflow.count("persist-credentials: false"), 4)
        self.assertEqual(
            workflow.count('git merge-base --is-ancestor "$NATIVE_COMMIT" origin/main'),
            2,
        )
        self.assertEqual(workflow.count("litert-release-publication"), 5)
        self.assertEqual(workflow.count('type == "required_reviewers"'), 2)
        publish_job = workflow[workflow.index("  publish:") :]
        self.assertIn("group: litert-lm-native-publication", publish_job)
        self.assertIn("cancel-in-progress: false", publish_job)
        self.assertLess(
            publish_job.index("group: litert-lm-native-publication"),
            publish_job.index("Recheck exact identity and immutable history"),
        )
        self.assertLess(
            workflow.index("Revalidate protected environment after reviewer approval"),
            workflow.index("- uses: actions/checkout@v6", workflow.index("  publish:")),
        )

        lines = workflow.splitlines()
        run_blocks: list[str] = []
        for index, line in enumerate(lines):
            stripped = line.lstrip()
            if not stripped.startswith("run:"):
                continue
            indent = len(line) - len(stripped)
            block = [stripped.removeprefix("run:")]
            for following in lines[index + 1 :]:
                following_stripped = following.lstrip()
                following_indent = len(following) - len(following_stripped)
                if following_stripped and following_indent <= indent:
                    break
                block.append(following)
            run_blocks.append("\n".join(block))
        self.assertTrue(run_blocks)
        self.assertNotIn("${{ inputs.", "\n".join(run_blocks))

        protocol = (root / "docs/release_protocol.md").read_text(encoding="utf-8")
        self.assertIn("dispatched repository ref resolves exactly to `native_commit`", protocol)

    def test_pr_qualification_is_exact_head_prepare_only(self) -> None:
        root = Path(__file__).resolve().parents[1]
        workflow = (
            root / ".github/workflows/pr_release_qualification.yml"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "ref: ${{ github.event.pull_request.head.sha }}", workflow
        )
        self.assertEqual(workflow.count("platform:"), 9)
        self.assertIn("Verify nine-platform candidate", workflow)
        self.assertIn("Expected exact real-model evidence", workflow)
        self.assertIn("group: pr-release-qualification-", workflow)
        self.assertIn("cancel-in-progress: true", workflow)
        self.assertNotIn("publication_approval", workflow)
        self.assertNotIn("gh release", workflow)
        self.assertNotIn("contents: write", workflow)

    def test_pr_qualification_packages_apple_candidate_before_validation(self) -> None:
        root = Path(__file__).resolve().parents[1]
        workflow = (
            root / ".github/workflows/pr_release_qualification.yml"
        ).read_text(encoding="utf-8")
        verify = workflow[workflow.index("  verify:") :]

        self.assertIn("runs-on: macos-latest", verify)
        self.assertNotIn("runs-on: ubuntu-latest", verify)
        self.assertIn('--upstream-ref "$QUALIFICATION_UPSTREAM_COMMIT"', verify)
        self.assertIn("--skip-overrides", verify)
        self.assertIn("--overrides-only", verify)
        ordered_steps = (
            "tools/package_upstream_prebuilts.py",
            "actions/download-artifact@v4",
            "cp -R staged/bin/* bin/",
            "--overrides-only",
            "tools/package_ios_runtime.py",
            "tools/package_macos_runtime.py",
            "tools/validate_runtime_artifacts.py",
        )
        offsets = [verify.index(step) for step in ordered_steps]
        self.assertEqual(offsets, sorted(offsets))
        self.assertNotIn("cp -R staged/bin .", verify)
        self.assertEqual(verify.count("tools/package_upstream_prebuilts.py"), 2)
        self.assertEqual(verify.count("--upstream-ref"), 1)
        self.assertEqual(verify.count("--skip-overrides"), 1)
        self.assertEqual(verify.count("--overrides-only"), 1)
        self.assertEqual(verify.count("tools/package_ios_runtime.py"), 1)
        self.assertEqual(verify.count("tools/package_macos_runtime.py"), 1)
        self.assertEqual(verify.count("tools/validate_runtime_artifacts.py"), 1)

    def test_runtime_validator_describes_official_asset_override(self) -> None:
        root = Path(__file__).resolve().parents[1]
        validator = (root / "tools/validate_runtime_artifacts.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            '"official Apple release archives."',
            validator,
        )
        self.assertNotIn("source-only development package", validator)

    def test_draft_identity_is_reconciled_before_candidate_tag_is_allowed(self) -> None:
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/native_release.yml").read_text(
            encoding="utf-8"
        )
        preflight = workflow[
            workflow.index("- name: Verify native and upstream commits") :
            workflow.index("  runtime-matrix:")
        ]
        publish_recheck = workflow[
            workflow.index("- name: Recheck exact identity and immutable history") :
            workflow.index("- name: Create or safely resume exact draft")
        ]
        for section in (preflight, publish_recheck):
            self.assertLess(
                section.index("tools/publication_state.py"),
                section.index("--allow-existing-candidate-tag"),
            )
            self.assertIn('publication_action="$(jq -r .action publication-plan.json)"', section)
            self.assertIn('[ "$publication_action" = resume ]', section)
            self.assertIn('[ "$publication_action" = verify-published ]', section)
        self.assertIn("--skip-history", preflight)

    def test_exact_published_retry_is_verified_without_mutation(self) -> None:
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/native_release.yml").read_text(
            encoding="utf-8"
        )
        self.assertGreaterEqual(workflow.count("--allow-published-exact"), 7)
        self.assertEqual(
            workflow.count("--workflow-run-id"),
            workflow.count("python3 tools/publication_state.py"),
        )
        self.assertIn("tools/validate_release_result.py", workflow)
        self.assertIn("Exact published transaction already exists", workflow)
        asset_mutation = workflow[
            workflow.index(
                'if [ "$(jq -r .action publication-plan.json)" != verify-published ]'
            ) :
            workflow.index("- name: Validate draft and promote it")
        ]
        self.assertIn("!= verify-published", asset_mutation)

        preflight = workflow[
            workflow.index("- name: Verify native and upstream commits") :
            workflow.index("  runtime-matrix:")
        ]
        published_recovery_gate = (
            'if [ "$publication_action" != verify-published ]; then'
        )
        self.assertIn("consumability_args=()", preflight)
        self.assertIn(published_recovery_gate, preflight)
        self.assertIn("consumability_args+=(--require-ready)", preflight)
        self.assertLess(
            preflight.index(
                'publication_action="$(jq -r .action publication-plan.json)"'
            ),
            preflight.index(published_recovery_gate),
        )

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
            validate_history(parse_release_tag("v0.17.0-1"), [])
        with self.assertRaisesRegex(PolicyError, "orphan stable rebuild"):
            validate_history(parse_release_tag("v0.17.0-1"), ["v0.16.0"])
        with self.assertRaisesRegex(PolicyError, "predecessor rebuild 1"):
            validate_history(
                parse_release_tag("v0.16.0-2"),
                ["v0.16.0"],
            )
        with self.assertRaisesRegex(PolicyError, "base release"):
            validate_history(parse_release_tag("v0.17.0-2"), ["v0.17.0-1"])
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
        with self.assertRaisesRegex(PolicyError, "base release"):
            validate_history(
                parse_release_tag("g123456789abc-2"),
                ["g123456789abc-1"],
            )
        validate_history(
            parse_release_tag("gba8249987394-2"),
            ["gba8249987394", "gba8249987394-1"],
        )

    def test_collision_and_rollback_are_rejected(self) -> None:
        with self.assertRaisesRegex(PolicyError, "collision"):
            validate_history(parse_release_tag("v0.16.1"), ["v0.16.1"])
        with self.assertRaisesRegex(PolicyError, "collision"):
            validate_history(
                parse_release_tag("v0.16.0-3"),
                ["v0.16.0", "v0.16.0-3"],
            )
        with self.assertRaisesRegex(PolicyError, "rollback"):
            validate_history(parse_release_tag("v0.15.1"), ["v0.16.0"])
        with self.assertRaisesRegex(PolicyError, "greater than 1"):
            validate_history(
                parse_release_tag("gba8249987394"), ["gba8249987394-1"]
            )

    def test_matching_draft_candidate_tag_can_be_ignored_after_reconciliation(self) -> None:
        validate_history(
            parse_release_tag("v0.16.1-2"),
            ["v0.16.1", "v0.16.1-1", "v0.16.1-2"],
            allow_existing_candidate=True,
        )
        with self.assertRaisesRegex(PolicyError, "predecessor rebuild 1"):
            validate_history(
                parse_release_tag("v0.16.1-2"),
                ["v0.16.1", "v0.16.1-2"],
                allow_existing_candidate=True,
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
