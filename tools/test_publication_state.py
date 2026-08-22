from __future__ import annotations

import unittest

from publication_state import PublicationStateError, plan_publication, release_notes


UPSTREAM = "924e79c91542761242244e4f1651851f822e4cbb"
NATIVE = "451ba0ce7c366972b4dc0e58f08ffe590958f943"


def plan(releases: list[dict], approval: str = "publish") -> dict:
    return plan_publication(
        releases,
        approval=approval,
        release_tag="v0.16.0-3",
        upstream_tag="v0.16.0",
        upstream_commit=UPSTREAM,
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

    def test_prepare_only_never_adopts_existing_draft(self) -> None:
        with self.assertRaisesRegex(PublicationStateError, "collision"):
            plan([self.matching_draft()], approval="prepare-only")


if __name__ == "__main__":
    unittest.main()
