from __future__ import annotations

import unittest

from prebuilt_overrides import (
    ANDROID_DAWN_ROLLBACK_COMMIT,
    prebuilt_override_manifest,
    prebuilt_overrides,
)


class PrebuiltOverridesTest(unittest.TestCase):
    def test_manifest_records_exact_override_provenance(self) -> None:
        manifest = prebuilt_override_manifest("v0.20.0")

        self.assertEqual(len(manifest), 2)
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
                "bin/android/arm64/libwebgpu_dawn.so": (
                    ANDROID_DAWN_ROLLBACK_COMMIT
                ),
                "bin/android/x64/libwebgpu_dawn.so": (
                    ANDROID_DAWN_ROLLBACK_COMMIT
                ),
            },
        )

    def test_supported_versions_keep_the_validated_android_dawn_rollback(self) -> None:
        for tag in ("v0.20.0",):
            with self.subTest(tag=tag):
                self._assert_dawn_rollback(tag)

    def _assert_dawn_rollback(self, tag: str) -> None:
        overrides = prebuilt_overrides(tag)

        self.assertEqual(
            {(override.arch, override.filename) for override in overrides},
            {
                ("arm64", "libwebgpu_dawn.so"),
                ("x64", "libwebgpu_dawn.so"),
            },
        )
        self.assertEqual(
            {override.source_commit for override in overrides},
            {ANDROID_DAWN_ROLLBACK_COMMIT},
        )
        self.assertTrue(all(len(override.sha256) == 64 for override in overrides))

        manifest = prebuilt_override_manifest(tag)
        self.assertEqual(len(manifest), 2)
        self.assertEqual(
            {entry["sourceCommit"] for entry in manifest},
            {ANDROID_DAWN_ROLLBACK_COMMIT},
        )

    def test_v0171_preserves_exact_v0170_override_provenance(self) -> None:
        self.assertEqual(prebuilt_override_manifest("v0.17.1"),
                         prebuilt_override_manifest("v0.17.0"))
        self.assertEqual(prebuilt_overrides("v0.17.0"), ())
        self.assertEqual(prebuilt_overrides("v0.17.2"), ())

    def test_v0191_manifest_preserves_both_dawn_rollbacks(self) -> None:
        historical = prebuilt_override_manifest("v0.19.1")
        self.assertEqual(len(historical), 2)
        self.assertEqual(historical, prebuilt_override_manifest("v0.20.0"))
        self.assertEqual(prebuilt_overrides("v0.19.1"), ())

    def test_other_versions_have_no_override(self) -> None:
        self.assertEqual(prebuilt_overrides("v0.14.0"), ())
        self.assertEqual(prebuilt_override_manifest("v0.14.0"), [])


if __name__ == "__main__":
    unittest.main()
