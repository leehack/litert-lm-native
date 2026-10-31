from __future__ import annotations

import unittest

from asr_litertlm_container_patch import require_container_patch_decision
from asr_overlap_patch import V019_MERGER_SOURCE, source_patch_manifest
from litert_cpu_options_identifier_patch import require_cpu_options_identifier_patch_decision
from litert_lm_symbols import has_prebuilt_topk_samplers, uses_c_api_v1
from package_ios_runtime import ios_dlopen_dependencies
from prebuilt_overrides import prebuilt_overrides
from stream_finish_reason_patch import require_finish_reason_patch_decision
from validate_release_manifest import allowed_spm_assets, required_spm_assets
from validate_runtime_artifacts import required_runtime_artifacts
from workspace_build_patch import require_workspace_build_patch_decision


class V019DecisionsTest(unittest.TestCase):
    def test_upstream_contained_carries_are_retired(self) -> None:
        self.assertFalse(require_container_patch_decision("v0.19.0"))
        self.assertFalse(require_cpu_options_identifier_patch_decision("v0.19.0"))
        self.assertFalse(require_workspace_build_patch_decision("v0.19.0"))

    def test_manifest_records_only_the_carries_still_applied(self) -> None:
        records = source_patch_manifest("v0.19.0")
        self.assertEqual(
            {record["id"] for record in records},
            {"asr-untimed-overlap", "stream-finish-reason",
             "xnnpack-pf32-sme2", "xnnpack-pqs8-qc4w-sme2"},
        )
        overlap = next(r for r in records if r["id"] == "asr-untimed-overlap")
        self.assertEqual(overlap["source"], V019_MERGER_SOURCE)
        self.assertTrue(require_finish_reason_patch_decision("v0.19.0"))

    def test_topk_sampler_packaging_stops_at_v019(self) -> None:
        self.assertTrue(has_prebuilt_topk_samplers("v0.18.1"))
        self.assertFalse(has_prebuilt_topk_samplers("v0.19.0"))
        self.assertTrue(uses_c_api_v1("v0.19.0"))
        self.assertFalse(uses_c_api_v1("v0.18.1"))
        self.assertIn("libLiteRtTopKMetalSampler.dylib",
                      ios_dlopen_dependencies("v0.18.1"))
        self.assertEqual(ios_dlopen_dependencies("v0.19.0"),
                         ("libLiteRtMetalAccelerator.dylib",))
        for assets in (required_spm_assets("v0.19.0"), allowed_spm_assets("v0.19.0")):
            self.assertFalse([name for name in assets if "TopK" in name])
        self.assertTrue([name for name in required_spm_assets("v0.18.1") if "TopK" in name])
        self.assertFalse([path for path in required_runtime_artifacts("v0.19.0") if "TopK" in str(path)])

    def test_android_dawn_rollback_waits_for_device_evidence(self) -> None:
        self.assertEqual(prebuilt_overrides("v0.19.0"), prebuilt_overrides("v0.18.1"))


if __name__ == "__main__":
    unittest.main()
