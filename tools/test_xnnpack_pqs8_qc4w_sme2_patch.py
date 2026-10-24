from __future__ import annotations

import hashlib
import re
import unittest
from pathlib import Path

import build_upstream_runtime as build
from asr_overlap_patch import source_patch_manifest
from xnnpack_pf32_sme2_patch import (
    ARCHIVE,
    SOURCES as PF32_SOURCES,
    XNNPACK_COMMIT,
)
from xnnpack_pqs8_qc4w_sme2_patch import (
    PATCH_PATH,
    SOURCES,
    require_xnnpack_qc4w_patch_decision,
    xnnpack_qc4w_patch_manifest,
)

REPO = Path(__file__).resolve().parents[1]
PATCH = (REPO / PATCH_PATH).read_text(encoding="utf-8")
CONFIG = "src/configs/gemm-config.c"
SME2_CONDITION = "if (XNN_ENABLE_ARM_SME2 && (hardware_config->arch_flags & xnn_arch_arm_sme2)) {"


class XnnpackPqs8Qc4wSme2PatchTest(unittest.TestCase):
    def test_decision_applies_only_to_v0181(self) -> None:
        for tag in ("v0.17.1", "v0.18.0"):
            self.assertFalse(require_xnnpack_qc4w_patch_decision(tag))
            self.assertEqual(xnnpack_qc4w_patch_manifest(tag), [])
        self.assertTrue(require_xnnpack_qc4w_patch_decision("v0.18.1"))
        for tag in ("v0.18.2", "v0.19.0", "main"):
            with self.subTest(tag=tag), self.assertRaisesRegex(
                RuntimeError, "no explicit decision"
            ):
                require_xnnpack_qc4w_patch_decision(tag)

    def test_patch_disables_only_the_sme2_pqs8_qc4w_config(self) -> None:
        self.assertEqual(re.findall(r"^diff --git a/(\S+) b/\1$", PATCH, re.MULTILINE), [CONFIG])
        self.assertEqual(list(SOURCES), [CONFIG])
        self.assertNotRegex(PATCH, r"(?m)^index ")
        self.assertEqual(len(re.findall(r"^@@ ", PATCH, re.MULTILINE)), 1)
        removed = re.findall(r"^-(?!-- )(.*)$", PATCH, re.MULTILINE)
        added = re.findall(r"^\+(?!\+\+ )(.*)$", PATCH, re.MULTILINE)
        self.assertEqual(removed, [f"  {SME2_CONDITION}"])
        self.assertEqual(added[-1], f"  {SME2_CONDITION.replace('if (', 'if (0 && ', 1)}")
        self.assertTrue(all(line.startswith("  // ") for line in added[:-1]))
        self.assertIn("xnn_pqs8_qc4w_gemm_minmax_fp32_ukernel_32x32c4__neonsme2_get_mr", PATCH)

    def test_patch_applies_after_the_pf32_rollback(self) -> None:
        self.assertEqual(SOURCES[CONFIG][0], PF32_SOURCES[CONFIG][1])
        pf32 = ARCHIVE.index('"@//bridge:xnnpack_pf32_sme2.patch",')
        qc4w = ARCHIVE.index('"@//bridge:xnnpack_pqs8_qc4w_sme2.patch",')
        self.assertLess(pf32, qc4w)
        self.assertIn('"xnnpack_pqs8_qc4w_sme2.patch"',
                      (REPO / "native/bridge/BUILD.bazel").read_text(encoding="utf-8"))

    def test_build_verifies_the_final_postimage_of_every_patched_source(self) -> None:
        expected = {name: postimage for name, (_, postimage) in PF32_SOURCES.items()}
        expected[CONFIG] = SOURCES[CONFIG][1]
        self.assertEqual(build.XNNPACK_POSTIMAGES, expected)

    def test_manifest_records_the_opt_out_last(self) -> None:
        records = [r for r in source_patch_manifest("v0.18.1")
                   if r["id"] != "litert-cpu-options-identifier"]
        self.assertEqual(records[-1:], xnnpack_qc4w_patch_manifest("v0.18.1"))
        record = records[-1]
        self.assertEqual(record["id"], "xnnpack-pqs8-qc4w-sme2")
        self.assertEqual(record["path"], PATCH_PATH)
        self.assertEqual(record["sha256"], hashlib.sha256((REPO / PATCH_PATH).read_bytes()).hexdigest())
        self.assertEqual(record["source"], f"XNNPACK@{XNNPACK_COMMIT}/{CONFIG}")
        self.assertEqual((record["preimageSha256Lf"], record["postimageSha256Lf"]), SOURCES[CONFIG])
        self.assertNotIn("xnnpack-pqs8-qc4w-sme2", {r["id"] for r in source_patch_manifest("v0.18.0")})


if __name__ == "__main__":
    unittest.main()
