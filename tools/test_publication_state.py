from __future__ import annotations

import unittest
import hashlib
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

from publication_state import (
    PublicationStateError,
    main,
    plan_publication,
    release_notes,
    validate_candidate_assets,
    validate_tag_ref,
)


UPSTREAM = "924e79c91542761242244e4f1651851f822e4cbb"
NATIVE = "451ba0ce7c366972b4dc0e58f08ffe590958f943"


def plan(releases: list[dict], approval: str = "publish") -> dict:
    return plan_publication(
        releases,
        approval=approval,
        release_tag="v0.16.0-3",
        upstream_tag="v0.16.0",
        upstream_commit=UPSTREAM,
        compatibility_tag="v0.16.0",
        native_commit=NATIVE,
        correlation_id="llamadart-400-1",
        prerelease=True,
    )


class PublicationStateTest(unittest.TestCase):
    def matching_draft(self) -> dict:
        return {
            "id": 42,
            "tag_name": "v0.16.0-3",
            "draft": True,
            "prerelease": True,
            "target_commitish": NATIVE,
            "name": "LiteRT-LM v0.16.0-3",
            "body": release_notes(
                release_tag="v0.16.0-3",
                upstream_tag="v0.16.0",
                upstream_commit=UPSTREAM,
                compatibility_tag="v0.16.0",
                native_commit=NATIVE,
                correlation_id="llamadart-400-1",
            ),
        }

    def test_absent_release_creates_and_exact_draft_resumes(self) -> None:
        self.assertEqual(plan([])["action"], "create")
        resumed = plan([self.matching_draft()])
        self.assertEqual(resumed["action"], "resume")
        self.assertEqual(resumed["releaseId"], 42)

    def test_published_or_mismatched_drafts_fail_closed(self) -> None:
        published = self.matching_draft()
        published["draft"] = False
        with self.assertRaisesRegex(PublicationStateError, "published"):
            plan([published])

        mismatch = self.matching_draft()
        mismatch["body"] = "different correlation"
        with self.assertRaisesRegex(PublicationStateError, "exact inputs"):
            plan([mismatch])

        compatibility_mismatch = self.matching_draft()
        with self.assertRaisesRegex(PublicationStateError, "exact inputs"):
            plan_publication(
                [compatibility_mismatch],
                approval="publish",
                release_tag="v0.16.0-3",
                upstream_tag="v0.16.0",
                upstream_commit=UPSTREAM,
                compatibility_tag="v0.15.0",
                native_commit=NATIVE,
                correlation_id="llamadart-400-1",
                prerelease=True,
            )

    def test_prepare_only_never_adopts_existing_draft(self) -> None:
        with self.assertRaisesRegex(PublicationStateError, "collision"):
            plan([self.matching_draft()], approval="prepare-only")

    def test_malformed_release_entry_fails_cleanly(self) -> None:
        with self.assertRaisesRegex(PublicationStateError, "entries must be objects"):
            plan([None])
        with tempfile.TemporaryDirectory() as temp:
            releases = Path(temp) / "releases.json"
            output = Path(temp) / "plan.json"
            releases.write_text("[null]", encoding="utf-8")
            with patch.object(
                sys,
                "argv",
                [
                    "publication_state.py",
                    "--releases",
                    str(releases),
                    "--approval",
                    "publish",
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
                    "--correlation-id",
                    "llamadart-400-1",
                    "--prerelease",
                    "true",
                    "--output",
                    str(output),
                ],
            ):
                with self.assertRaisesRegex(SystemExit, "entries must be objects"):
                    main()

    def test_tag_ref_must_target_exact_native_commit(self) -> None:
        validate_tag_ref(
            {
                "ref": "refs/tags/v0.16.0-3",
                "object": {"type": "commit", "sha": NATIVE},
            },
            release_tag="v0.16.0-3",
            native_commit=NATIVE,
        )
        with self.assertRaisesRegex(PublicationStateError, "exact native commit"):
            validate_tag_ref(
                {
                    "ref": "refs/tags/v0.16.0-3",
                    "object": {"type": "commit", "sha": "0" * 40},
                },
                release_tag="v0.16.0-3",
                native_commit=NATIVE,
            )

    def test_candidate_assets_are_bound_by_name_size_state_and_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            candidate = Path(temp)
            release_dir = candidate / "release"
            release_dir.mkdir()
            files = {
                "manifest.json": b"manifest",
                "SHA256SUMS": b"sums",
                "release-result.json": b"result",
                "runtime.tar.gz": b"runtime",
            }
            for name, content in files.items():
                path = release_dir / name if name == "runtime.tar.gz" else candidate / name
                path.write_bytes(content)
            metadata = self.matching_draft()
            metadata["assets"] = [
                {
                    "name": name,
                    "state": "uploaded",
                    "size": len(content),
                    "digest": "sha256:" + hashlib.sha256(content).hexdigest(),
                }
                for name, content in files.items()
            ]
            validate_candidate_assets(metadata, candidate_dir=candidate)
            metadata["assets"][0]["digest"] = "sha256:" + "f" * 64
            with self.assertRaisesRegex(PublicationStateError, "digest mismatch"):
                validate_candidate_assets(metadata, candidate_dir=candidate)


if __name__ == "__main__":
    unittest.main()
