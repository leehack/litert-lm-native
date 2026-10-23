from __future__ import annotations

from copy import deepcopy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import build_upstream_runtime as build
import package_release
from asr_litertlm_container_patch import SOURCES
from asr_overlap_patch import POSTIMAGE_SHA256, source_patch_manifest, source_sha256
from stream_finish_reason_patch import BAZEL_DEFINE as FINISH_REASON_DEFINE, finish_reason_patch_manifest
from workspace_build_patch import workspace_build_patch_manifest
from xnnpack_pf32_sme2_patch import xnnpack_pf32_patch_manifest
from xnnpack_pqs8_qc4w_sme2_patch import xnnpack_qc4w_patch_manifest
from prebuilt_overrides import ANDROID_DAWN_ROLLBACKS, prebuilt_overrides
from test_asr_litertlm_container_patch import stage_preimage
from validate_release_manifest import validate_schema_2_identity

REPO = Path(__file__).resolve().parents[1]
UPSTREAM_COMMIT = "bda624851d74be34d4e1f7fac1fc4155939539c7"
NATIVE_COMMIT = "8182448814867ad329be7e995b4e8aab5efd79c8"


class V0181QualificationTest(unittest.TestCase):
    def test_v0181_production_build_applies_all_three_source_carries_before_bazel(self):
        # These fixtures are byte-identical in exact v0.18.0 and v0.18.1.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stage_preimage(root)
            merger = root / "omni/asr/timestamp_text_merger.cc"
            merger.write_bytes((REPO / "tools/fixtures/timestamp_text_merger_v018.cc").read_bytes())
            with (patch.object(build, "materialize_git_lfs_libraries", return_value=0),
                  patch.object(build, "patch_stream_finish_reason") as finish_reason,
                  patch.object(build, "bazel_command", return_value=["bazel"]),
                  patch.object(build, "run", side_effect=RuntimeError("reached Bazel")) as run):
                with self.assertRaisesRegex(RuntimeError, "reached Bazel"):
                    build.build_runtime(root, "macos", "arm64", "v0.18.1", "2")
            # Finish-reason source application is covered with fixtures in
            # test_stream_finish_reason_patch; here only its v0.18.1 wiring.
            finish_reason.assert_called_once_with(root, "v0.18.1")
            self.assertIn(FINISH_REASON_DEFINE, run.call_args.args[0])
            self.assertEqual(source_sha256(merger.read_bytes()), POSTIMAGE_SHA256)
            for source, (_, postimage) in SOURCES.items():
                self.assertEqual(source_sha256((root / source).read_bytes()), postimage)
            self.assertIn("--define=litert_lm_asr_api=true", run.call_args.args[0])
            # Exact idempotence and drift rejection also apply to the new tag.
            build.patch_asr_untimed_overlap(root, "v0.18.1")
            build.patch_asr_litertlm_container(root, "v0.18.1")
            merger.write_bytes(merger.read_bytes() + b"// drift\n")
            with (patch.object(build, "patch_stream_finish_reason"),
                  self.assertRaisesRegex(RuntimeError, "requalify untimed overlap")):
                build.build_runtime(root, "macos", "arm64", "v0.18.1", "2")

    def test_v0181_manifest_keeps_all_patch_and_dawn_records_and_rejects_loss(self):
        with tempfile.TemporaryDirectory() as temp:
            with (patch.object(package_release, "iter_artifacts", return_value=[]),
                  patch.object(package_release, "provider_free_ios", return_value=False),
                  patch.object(package_release, "SHA256SUMS_PATH", Path(temp) / "SHA256SUMS")):
                manifest = package_release.build_manifest(
                    upstream_tag="v0.18.1", upstream_commit=UPSTREAM_COMMIT,
                    compatibility_tag="v0.18.1", release_tag="v0.18.1",
                    native_commit=NATIVE_COMMIT, official_upstream_assets=True)
        self.assertEqual(manifest["upstream"]["sourcePatches"],
                         source_patch_manifest("v0.18.0") + workspace_build_patch_manifest("v0.18.1")
                         + xnnpack_pf32_patch_manifest("v0.18.1")
                         + xnnpack_qc4w_patch_manifest("v0.18.1"))
        self.assertEqual(finish_reason_patch_manifest("v0.18.1"), finish_reason_patch_manifest("v0.18.0"))
        self.assertTrue({"stream-finish-reason", "asr-untimed-overlap", "workspace-build", "xnnpack-pf32-sme2",
                         "xnnpack-pqs8-qc4w-sme2"}
                        <= {entry["id"] for entry in manifest["upstream"]["sourcePatches"]})
        self.assertEqual(prebuilt_overrides("v0.18.1"), ANDROID_DAWN_ROLLBACKS)
        def validate(value):
            validate_schema_2_identity(value, upstream_tag="v0.18.1", upstream_commit=UPSTREAM_COMMIT,
                                      compatibility_tag="v0.18.1", native_commit=NATIVE_COMMIT,
                                      release_tag="v0.18.1")
        validate(manifest)
        for field in ("sourcePatches", "prebuiltOverrides"):
            broken = deepcopy(manifest)
            broken["upstream"][field] = []
            with self.subTest(field=field), self.assertRaises(SystemExit):
                validate(broken)

    def test_gpu_teardown_selection_follows_last_starlark_assignment(self):
        old = next(iter(build.LITERT_REFS_WITHOUT_GPU_TEARDOWN_ORDERING))
        new = "ca21dc99de51c76bdcc572afeea1dd937d3c9e5c"
        # Stable v0.18.1 retains an old assignment before the effective one.
        for first, last, needs in ((old, new, False), (new, old, True)):
            with self.subTest(last=last):
                self.assertEqual(build.needs_gpu_environment_teardown_patch(
                    f'LITERT_REF = "{first}"\nLITERT_REF = "{last}"\n', "v0.18.1"), needs)

    def test_qualification_workflow_uses_exact_stable_candidate(self):
        workflow = (REPO / ".github/workflows/pr_release_qualification.yml").read_text()
        self.assertIn("QUALIFICATION_UPSTREAM_TAG: v0.18.1", workflow)
        self.assertIn(f"QUALIFICATION_UPSTREAM_COMMIT: {UPSTREAM_COMMIT}", workflow)


if __name__ == "__main__":
    unittest.main()
