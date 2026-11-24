from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import android_gpu_safety_patch
import step_zero_state_patch
import stream_finish_reason_patch
from asr_overlap_patch import source_patch_manifest, source_sha256
from build_upstream_runtime import patch_stream_finish_reason
from prebuilt_overrides import prebuilt_overrides
from xnnpack_pf32_sme2_patch import commit_for


class V020DecisionsTest(unittest.TestCase):
    def test_git_format_carries_apply_inside_owner_checkout(self) -> None:
        before = b"context\nupstream\n"
        after = b"context\npatched\n"
        hashes = source_sha256(before), source_sha256(after)
        names_and_appliers = (
            (stream_finish_reason_patch, "c/c_api_internal.h", patch_stream_finish_reason,
             {"V020_SOURCES": {"c/c_api_internal.h": hashes}}),
            (step_zero_state_patch, step_zero_state_patch.SOURCE, step_zero_state_patch.apply,
             {"V020_PREIMAGE": hashes[0], "V020_POSTIMAGE": hashes[1]}),
            (android_gpu_safety_patch, "c/engine.cc", android_gpu_safety_patch.apply,
             {"V020_SOURCES": {"c/engine.cc": hashes}}),
        )
        with tempfile.TemporaryDirectory() as temp:
            owner = Path(temp)
            subprocess.run(["git", "init", "--quiet", str(owner)], check=True)
            source_root = owner / ".tmp" / "litert-build" / "LiteRT-LM-v0.20.0"
            patch_file = owner / "carry.patch"
            for module, name, apply, identities in names_and_appliers:
                with self.subTest(source=name):
                    source = source_root / name
                    source.parent.mkdir(parents=True, exist_ok=True)
                    source.write_bytes(before)
                    patch_file.write_bytes((
                        f"diff --git a/{name} b/{name}\n"
                        f"--- a/{name}\n+++ b/{name}\n"
                        "@@ -1,2 +1,2 @@\n context\n-upstream\n+patched\n"
                    ).encode())
                    with patch.multiple(module, V020_PATCH_PATH=str(patch_file), **identities):
                        apply(source_root, "v0.20.0")
                    self.assertEqual(source.read_bytes(), after)
                    self.assertFalse((owner / name).exists())

    def test_manifest_keeps_audited_carries_with_new_source_identities(self) -> None:
        previous = source_patch_manifest("v0.19.1")
        records = source_patch_manifest("v0.20.0")
        self.assertEqual({r["id"] for r in records}, {r["id"] for r in previous} | {"windows-engine-fd"})
        self.assertEqual(len(records), len(previous) + 2)
        self.assertEqual(len({(r["id"], r["source"]) for r in records}), len(records))
        by_id = {r["id"]: r for r in records}
        for patch_id in (
            "android-qwen3-gpu-safety", "huggingface-token-bytes",
            "stream-finish-reason", "step-zero-state", "litert-stage-spatial-tensors", "windows-engine-fd",
        ):
            self.assertTrue(by_id[patch_id]["path"].endswith("_v020.patch"))
        self.assertEqual(
            by_id["asr-untimed-overlap"]["path"], "native/bridge/asr_untimed_overlap_v019.patch",
        )
        self.assertEqual(commit_for("v0.20.0"), "08cc38b61f7589f84e91c6e343e0f130ae3279ca")
        self.assertEqual(prebuilt_overrides("v0.20.0"), prebuilt_overrides("v0.19.1"))
        with self.assertRaisesRegex(RuntimeError, "no explicit decision"):
            source_patch_manifest("v0.20.1")
