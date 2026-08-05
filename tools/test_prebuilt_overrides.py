from __future__ import annotations

import unittest

from prebuilt_overrides import (
    V0_15_ANDROID_SAMPLER_FIX_COMMIT,
    prebuilt_override_manifest,
    prebuilt_overrides,
)


class PrebuiltOverridesTest(unittest.TestCase):
    def test_v015_pins_both_android_sampler_architectures(self) -> None:
        overrides = prebuilt_overrides("v0.15.0")

        self.assertEqual({override.arch for override in overrides}, {"arm64", "x64"})
        self.assertEqual(
            {override.filename for override in overrides},
            {"libLiteRtTopKOpenClSampler.so"},
        )
        self.assertEqual(
            {override.source_commit for override in overrides},
            {V0_15_ANDROID_SAMPLER_FIX_COMMIT},
        )
        self.assertTrue(all(len(override.sha256) == 64 for override in overrides))

    def test_manifest_records_exact_override_provenance(self) -> None:
        manifest = prebuilt_override_manifest("v0.15.0")

        self.assertEqual(len(manifest), 2)
        self.assertTrue(
            all(
                entry["sourceRepository"] == "google-ai-edge/LiteRT-LM"
                and entry["sourceCommit"] == V0_15_ANDROID_SAMPLER_FIX_COMMIT
                and entry["targetPath"].startswith("bin/android/")
                for entry in manifest
            )
        )

    def test_other_versions_have_no_override(self) -> None:
        self.assertEqual(prebuilt_overrides("v0.14.0"), ())
        self.assertEqual(prebuilt_override_manifest("v0.14.0"), [])


if __name__ == "__main__":
    unittest.main()
