from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from android_gpu_safety_patch import applies as android_gpu_safety_applies
from asr_litertlm_container_patch import require_container_patch_decision
from asr_overlap_patch import V019_MERGER_SOURCE, source_patch_manifest
from litert_cpu_options_identifier_patch import require_cpu_options_identifier_patch_decision
from ios_runtime_policy import verify_upstream_fst_gate
from litert_lm_symbols import (
    APPLE_STATIC_GPU_ACCELERATOR_SYMBOLS,
    has_prebuilt_apple_litert_companions,
    has_prebuilt_apple_metal_accelerator,
    has_prebuilt_topk_samplers,
    required_bridge_symbols,
    required_c_api_symbols,
    uses_c_api_v1,
)
from package_ios_runtime import ios_dlopen_dependencies
from package_ios_runtime import validate_source_built_symbols as ios_source_built_symbols
from package_macos_runtime import validate_source_built_symbols as macos_source_built_symbols
from prebuilt_overrides import prebuilt_overrides
from stream_finish_reason_patch import require_finish_reason_patch_decision
from validate_release_manifest import allowed_spm_assets, required_spm_assets
from validate_runtime_artifacts import forbidden_runtime_artifacts, required_runtime_artifacts
from validate_runtime_dependencies import newest_glibc_requirement
from workspace_build_patch import require_workspace_build_patch_decision
from xnnpack_pf32_sme2_patch import commit_for as xnnpack_commit_for


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
             "xnnpack-pf32-sme2", "xnnpack-pqs8-qc4w-sme2",
             "android-qwen3-gpu-safety", "huggingface-token-bytes"},
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
        self.assertEqual(ios_dlopen_dependencies("v0.19.0"), ())
        for assets in (required_spm_assets("v0.19.0"), allowed_spm_assets("v0.19.0")):
            self.assertFalse([name for name in assets if "TopK" in name])
        self.assertTrue([name for name in required_spm_assets("v0.18.1") if "TopK" in name])
        self.assertFalse([path for path in required_runtime_artifacts("v0.19.0") if "TopK" in str(path)])

    def test_apple_metal_accelerator_packaging_stops_at_v019(self) -> None:
        metal_zip = "litert-lm-native-apple-LiteRtMetalAccelerator-xcframework-{tag}.zip"
        self.assertTrue(has_prebuilt_apple_metal_accelerator("v0.18.1"))
        self.assertFalse(has_prebuilt_apple_metal_accelerator("v0.19.1"))
        self.assertIn("libLiteRtMetalAccelerator.dylib", ios_dlopen_dependencies("v0.18.1"))
        self.assertIn(metal_zip, required_spm_assets("v0.18.1"))
        self.assertNotIn(metal_zip, allowed_spm_assets("v0.19.1"))
        self.assertTrue([p for p in required_runtime_artifacts("v0.18.1") if "Metal" in str(p)])
        self.assertFalse([p for p in required_runtime_artifacts("v0.19.1") if "Metal" in str(p)])
        self.assertEqual(forbidden_runtime_artifacts("v0.18.1"), [])
        self.assertEqual(
            {p.as_posix() for p in forbidden_runtime_artifacts("v0.19.1") if "Metal" in p.name},
            {
                "bin/ios/arm64/LiteRtMetalAccelerator.framework/LiteRtMetalAccelerator",
                "bin/ios/arm64-sim/LiteRtMetalAccelerator.framework/LiteRtMetalAccelerator",
                "bin/ios/arm64/libLiteRtMetalAccelerator.dylib",
                "bin/ios/arm64-sim/libLiteRtMetalAccelerator.dylib",
                "bin/macos/arm64/libLiteRtMetalAccelerator.dylib",
            },
        )

    def test_apple_litert_companion_packaging_stops_at_v019(self) -> None:
        litert_zips = {
            "litert-lm-native-apple-LiteRt-xcframework-{tag}.zip",
            "litert-lm-native-apple-LiteRtWebGpuAccelerator-xcframework-{tag}.zip",
        }
        self.assertTrue(has_prebuilt_apple_litert_companions("v0.18.1"))
        self.assertFalse(has_prebuilt_apple_litert_companions("v0.19.1"))
        self.assertTrue(litert_zips <= set(allowed_spm_assets("v0.18.1")))
        self.assertFalse(litert_zips & set(allowed_spm_assets("v0.19.1")))
        self.assertFalse(litert_zips & set(required_spm_assets("v0.19.1")))
        self.assertEqual(forbidden_runtime_artifacts("v0.18.1"), [])
        self.assertLessEqual(
            {
                "bin/ios/arm64/libLiteRt.dylib",
                "bin/ios/arm64-sim/libLiteRt.dylib",
                "bin/macos/arm64/libLiteRt.dylib",
                "bin/macos/arm64/libLiteRtWebGpuAccelerator.dylib",
            },
            {p.as_posix() for p in forbidden_runtime_artifacts("v0.19.1")},
        )

    def test_v019_apple_runtimes_require_a_static_gpu_accelerator(self) -> None:
        required = (required_c_api_symbols("v0.19.1")
                    + required_bridge_symbols("v0.19.1"))
        for platform, validate in (("ios", ios_source_built_symbols),
                                   ("macos", macos_source_built_symbols)):
            static = APPLE_STATIC_GPU_ACCELERATOR_SYMBOLS[platform]
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as temp:
                binary = Path(temp) / "LiteRtLm"
                binary.write_bytes(b"\0".join(required))
                with self.assertRaisesRegex(RuntimeError, static.decode()):
                    validate(binary, "v0.19.1")
                validate(binary, "v0.18.1")
                binary.write_bytes(b"\0".join([*required, static]))
                validate(binary, "v0.19.1")

    def test_ios_fst_gate_follows_the_build_config_layout(self) -> None:
        provider = '"//runtime/components/constrained_decoding:gemma_model_constraint_provider_lib",\n'
        processors = (
            'actual = "//build_config:disable_fst_constraints"\n'
            '":litert_lm_fst_constraints_disabled": [\n"x",\n],\n'
            '"//conditions:default": [\n' + provider + '],\n'
        )
        define = 'define_values = {"LITERT_LM_FST_CONSTRAINTS_DISABLED": "1"},\n'
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "build_config").mkdir()
            directory = root / "runtime/conversation/model_data_processor"
            directory.mkdir(parents=True)
            (root / "build_config/BUILD").write_text(define)
            (directory / "BUILD").write_text(processors)
            verify_upstream_fst_gate(root)
            (directory / "BUILD").write_text(processors + provider)
            with self.assertRaisesRegex(RuntimeError, "dependency gate"):
                verify_upstream_fst_gate(root)
            (root / "build_config/BUILD").write_text("")
            with self.assertRaisesRegex(RuntimeError, "disable gate"):
                verify_upstream_fst_gate(root)

    def test_newest_glibc_requirement_compares_numerically(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            library = Path(temp) / "lib.so"
            library.write_bytes(b"\0GLIBC_2.9\0GLIBC_2.39\0GLIBC_2.2.5\0")
            self.assertEqual(newest_glibc_requirement(library), (2, 39))
            library.write_bytes(b"\0")
            self.assertIsNone(newest_glibc_requirement(library))

    def test_android_dawn_rollback_waits_for_device_evidence(self) -> None:
        self.assertEqual(prebuilt_overrides("v0.19.0"), prebuilt_overrides("v0.18.1"))

    def test_v0191_keeps_every_v0190_decision(self) -> None:
        # v0.19.1 changes no carried preimage, dependency pin or prebuilt.
        self.assertEqual(source_patch_manifest("v0.19.1"), source_patch_manifest("v0.19.0"))
        self.assertEqual(prebuilt_overrides("v0.19.1"), prebuilt_overrides("v0.19.0"))
        self.assertEqual(xnnpack_commit_for("v0.19.1"), xnnpack_commit_for("v0.19.0"))
        self.assertTrue(android_gpu_safety_applies("v0.19.1"))
        self.assertFalse(require_container_patch_decision("v0.19.1"))
        self.assertFalse(require_cpu_options_identifier_patch_decision("v0.19.1"))
        self.assertFalse(require_workspace_build_patch_decision("v0.19.1"))


if __name__ == "__main__":
    unittest.main()
