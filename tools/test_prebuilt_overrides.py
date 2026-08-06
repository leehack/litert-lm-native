from __future__ import annotations

import unittest

from prebuilt_overrides import (
    V0_15_ANDROID_DAWN_ROLLBACK_COMMIT,
    V0_15_ANDROID_SAMPLER_FIX_COMMIT,
    prebuilt_override_manifest,
    prebuilt_overrides,
)


class PrebuiltOverridesTest(unittest.TestCase):
    def test_v015_pins_android_corrections_for_both_architectures(self) -> None:
        overrides = prebuilt_overrides("v0.15.0")

        self.assertEqual({override.arch for override in overrides}, {"arm64", "x64"})
        self.assertEqual(
            {(override.arch, override.filename) for override in overrides},
            {
                ("arm64", "libLiteRtTopKOpenClSampler.so"),
                ("x64", "libLiteRtTopKOpenClSampler.so"),
                ("arm64", "libwebgpu_dawn.so"),
                ("x64", "libwebgpu_dawn.so"),
            },
        )
        self.assertEqual(
            {override.source_commit for override in overrides},
            {
                V0_15_ANDROID_SAMPLER_FIX_COMMIT,
                V0_15_ANDROID_DAWN_ROLLBACK_COMMIT,
            },
        )
        self.assertTrue(all(len(override.sha256) == 64 for override in overrides))

    def test_manifest_records_exact_override_provenance(self) -> None:
        manifest = prebuilt_override_manifest("v0.15.0")

        self.assertEqual(len(manifest), 4)
        self.assertTrue(
            all(
                entry["sourceRepository"] == "google-ai-edge/LiteRT-LM"
                and entry["targetPath"].startswith("bin/android/")
                for entry in manifest
            )
        )
        self.assertEqual(
            {
                entry["targetPath"]: entry["sourceCommit"]
                for entry in manifest
            },
            {
                "bin/android/arm64/libLiteRtTopKOpenClSampler.so": (
                    V0_15_ANDROID_SAMPLER_FIX_COMMIT
                ),
                "bin/android/x64/libLiteRtTopKOpenClSampler.so": (
                    V0_15_ANDROID_SAMPLER_FIX_COMMIT
                ),
                "bin/android/arm64/libwebgpu_dawn.so": (
                    V0_15_ANDROID_DAWN_ROLLBACK_COMMIT
                ),
                "bin/android/x64/libwebgpu_dawn.so": (
                    V0_15_ANDROID_DAWN_ROLLBACK_COMMIT
                ),
            },
        )

    def test_other_versions_have_no_override(self) -> None:
        self.assertEqual(prebuilt_overrides("v0.14.0"), ())
        self.assertEqual(prebuilt_override_manifest("v0.14.0"), [])


if __name__ == "__main__":
    unittest.main()
