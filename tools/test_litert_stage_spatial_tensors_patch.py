import hashlib
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from asr_overlap_patch import source_patch_manifest, source_sha256
from litert_stage_spatial_tensors_patch import (
    LITERT_REF,
    PATCH_PATH,
    SOURCES,
    UPSTREAM_FIX,
    require_stage_spatial_tensors_patch_decision,
    stage_spatial_tensors_patch_manifest,
)

REPO = Path(__file__).resolve().parents[1]


class StageSpatialTensorsPatchTest(unittest.TestCase):
    def test_requires_a_version_specific_decision(self) -> None:
        for tag in ("v0.18.1", "v0.19.0"):
            self.assertFalse(require_stage_spatial_tensors_patch_decision(tag))
            self.assertEqual(stage_spatial_tensors_patch_manifest(tag), [])
        self.assertTrue(require_stage_spatial_tensors_patch_decision("v0.19.1"))
        for tag in ("v0.19.2", "main"):
            with self.subTest(tag=tag), self.assertRaisesRegex(RuntimeError, "no explicit decision"):
                stage_spatial_tensors_patch_manifest(tag)

    @unittest.skipUnless(os.environ.get("LITERT_STAGE_SPATIAL_TENSORS_SOURCE"),
                         "requires the pinned unpatched LiteRT source tree")
    def test_backport_matches_the_pinned_preimages_and_postimages(self) -> None:
        stock = Path(os.environ["LITERT_STAGE_SPATIAL_TENSORS_SOURCE"])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for path, (preimage, _) in SOURCES.items():
                data = (stock / path).read_bytes()
                self.assertEqual(source_sha256(data), preimage, path)
                (root / path).parent.mkdir(parents=True, exist_ok=True)
                (root / path).write_bytes(data)
            subprocess.run(["git", "apply", str(REPO / PATCH_PATH)], cwd=root, check=True)
            for path, (_, postimage) in SOURCES.items():
                self.assertEqual(source_sha256((root / path).read_bytes()), postimage, path)

    def test_manifest_attributes_exactly_the_four_patched_sources(self) -> None:
        patch = (REPO / PATCH_PATH).read_bytes()
        headers = re.findall(rb"^diff --git a/(\S+) b/\1$", patch, re.MULTILINE)
        self.assertEqual([path.decode() for path in headers], list(SOURCES))
        records = stage_spatial_tensors_patch_manifest("v0.19.1")
        self.assertEqual(source_patch_manifest("v0.19.1")[-len(records):], records)
        self.assertEqual(len(records), len(SOURCES))
        for record, (path, (preimage, postimage)) in zip(records, SOURCES.items()):
            self.assertEqual(record["id"], "litert-stage-spatial-tensors")
            self.assertEqual(record["path"], PATCH_PATH)
            self.assertEqual(record["source"], f"LiteRT@{LITERT_REF}/{path}")
            self.assertEqual(record["sha256"], hashlib.sha256(patch).hexdigest())
            self.assertEqual(record["preimageSha256Lf"], preimage)
            self.assertEqual(record["postimageSha256Lf"], postimage)
            self.assertIn(f"google-ai-edge/LiteRT@{UPSTREAM_FIX}", record["scope"])
            self.assertIn("excludes official upstream prebuilts", record["scope"])


if __name__ == "__main__":
    unittest.main()
