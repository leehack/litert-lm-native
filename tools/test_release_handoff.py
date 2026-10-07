from __future__ import annotations
import unittest
from release_handoff import handoff


class ReleaseHandoffTest(unittest.TestCase):
    def setUp(self):
        self.digest = "sha256:" + "a" * 64
        self.result = dict(
            release=dict(
                url="https://github.com/leehack/litert-lm-native/releases/tag/v0.17.0-8",
                assetDigests={"manifest.json": self.digest},
            ),
            request=dict(
                releaseTag="v0.17.0-8", nativeCommit="b" * 40, upstreamCommit="c" * 40
            ),
            workflow=dict(url="https://github.com/example/run", runAttempt=1),
            candidate={},
        )
        self.manifest = dict(
            release=dict(tag="v0.17.0-8"),
            native=dict(commit="b" * 40),
            upstream=dict(commit="c" * 40),
            realModelSmokes=[
                dict(
                    platform="linux",
                    arch="x64",
                    result="pass",
                    backend="cpu",
                    model=dict(fileName="moonshine.litertlm"),
                )
            ],
        )

    def test_preview_is_digest_bound_readonly_and_does_not_infer_device_qualification(
        self,
    ):
        summary, preview = handoff(
            self.result,
            self.manifest,
            self.digest,
            [
                dict(
                    started_at="2026-10-07T00:00:00Z",
                    completed_at="2026-10-07T00:00:05Z",
                ),
                dict(started_at="2026-10-07T00:00:00Z", completed_at=None),
            ],
        )
        self.assertFalse(preview["deviceQualified"])
        self.assertEqual(preview["modelEvidence"], self.manifest["realModelSmokes"])
        self.assertEqual(
            preview["qualificationLimits"]["independentReview"], "not-attached"
        )
        self.assertTrue(preview["requiresReviewedConsumerPR"])
        self.assertEqual(preview["timingSnapshot"]["completedRunnerSeconds"], 5)
        self.assertFalse(preview["timingSnapshot"]["final"])
        self.assertIn("--litert-lm-tag v0.17.0-8 --dry-run", summary)
        self.assertIn("CPU model evidence does not qualify GPU", summary)

    def test_manifest_byte_and_source_mismatches_rejected(self):
        with self.assertRaises(ValueError):
            handoff(self.result, self.manifest, "sha256:" + "d" * 64, [])
        self.manifest["native"]["commit"] = "d" * 40
        with self.assertRaises(ValueError):
            handoff(self.result, self.manifest, self.digest, [])

    def test_original_candidate_identity_is_retained(self):
        preparation = dict(
            source=dict(runId=41, runAttempt=1, artifactId=7, digest=self.digest),
            result=dict(workflow=dict(url="https://github.com/example/source-run")),
        )
        self.result["candidate"]["preparation"] = preparation
        summary, preview = handoff(self.result, self.manifest, self.digest, [])
        self.assertEqual(preview["preparation"], preparation)
        self.assertIn("artifact 7", summary)
        self.assertIn("source-run", summary)


if __name__ == "__main__":
    unittest.main()
