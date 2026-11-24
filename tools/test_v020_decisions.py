from __future__ import annotations

import unittest

from asr_overlap_patch import source_patch_manifest
from prebuilt_overrides import prebuilt_overrides
from xnnpack_pf32_sme2_patch import commit_for


class V020DecisionsTest(unittest.TestCase):
    def test_manifest_keeps_audited_carries_with_new_source_identities(self) -> None:
        previous = source_patch_manifest("v0.19.1")
        records = source_patch_manifest("v0.20.0")
        self.assertEqual({r["id"] for r in records}, {r["id"] for r in previous})
        self.assertEqual(len(records), len(previous) + 1)
        self.assertEqual(len({(r["id"], r["source"]) for r in records}), len(records))
        by_id = {r["id"]: r for r in records}
        for patch_id in (
            "android-qwen3-gpu-safety", "huggingface-token-bytes",
            "stream-finish-reason", "step-zero-state", "litert-stage-spatial-tensors",
        ):
            self.assertTrue(by_id[patch_id]["path"].endswith("_v020.patch"))
        self.assertEqual(
            by_id["asr-untimed-overlap"]["path"], "native/bridge/asr_untimed_overlap_v019.patch",
        )
        self.assertEqual(commit_for("v0.20.0"), "08cc38b61f7589f84e91c6e343e0f130ae3279ca")
        self.assertEqual(prebuilt_overrides("v0.20.0"), prebuilt_overrides("v0.19.1"))
        with self.assertRaisesRegex(RuntimeError, "no explicit decision"):
            source_patch_manifest("v0.20.1")
