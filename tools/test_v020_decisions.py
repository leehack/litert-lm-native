from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import android_gpu_safety_patch
import build_upstream_runtime as build
import windows_engine_fd_patch as windows_fd
from asr_overlap_patch import source_patch_manifest, source_sha256
from prebuilt_overrides import prebuilt_overrides
from xnnpack_pf32_sme2_patch import XNNPACK_COMMIT


class V020DecisionsTest(unittest.TestCase):
    def test_git_format_carries_apply_inside_owner_checkout(self) -> None:
        before = b"context\nupstream\n"
        after = b"context\npatched\n"
        hashes = source_sha256(before), source_sha256(after)
        names_and_appliers = (
            (build, "c/c_api_internal.h", build.patch_stream_finish_reason,
             {"FINISH_REASON_SOURCES": {"c/c_api_internal.h": hashes}}),
            (android_gpu_safety_patch, "c/engine.cc", android_gpu_safety_patch.apply,
             {"SOURCES": {"c/engine.cc": hashes}}),
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
                    patch_attr = "FINISH_REASON_PATCH_PATH" if module is build else "PATCH_PATH"
                    with patch.multiple(module, **{patch_attr: str(patch_file)}, **identities):
                        apply(source_root, "v0.20.0")
                    self.assertEqual(source.read_bytes(), after)
                    self.assertFalse((owner / name).exists())

    def test_manifest_keeps_audited_carries_with_new_source_identities(self) -> None:
        previous = source_patch_manifest("v0.19.1")
        records = source_patch_manifest("v0.20.0")
        self.assertEqual(previous, [])
        self.assertEqual({r["id"] for r in records}, {
            "asr-untimed-overlap", "stream-finish-reason", "android-qwen3-gpu-safety",
            "windows-engine-fd", "xnnpack-pf32-sme2", "xnnpack-pqs8-qc4w-sme2",
            "huggingface-token-bytes", "litert-stage-spatial-tensors",
            "android-automatic-gpu",
        })
        self.assertEqual(len({(r["id"], r["source"]) for r in records}), len(records))
        by_id = {r["id"]: r for r in records}
        for patch_id in (
            "android-qwen3-gpu-safety", "huggingface-token-bytes",
            "stream-finish-reason", "litert-stage-spatial-tensors", "windows-engine-fd",
            "android-automatic-gpu",
        ):
            self.assertTrue(by_id[patch_id]["path"].endswith("_v020.patch"))
        self.assertEqual(
            by_id["asr-untimed-overlap"]["path"], "native/bridge/asr_untimed_overlap_v019.patch",
        )
        self.assertEqual(XNNPACK_COMMIT, "08cc38b61f7589f84e91c6e343e0f130ae3279ca")
        self.assertEqual(prebuilt_overrides("v0.19.1"), ())
        with self.assertRaisesRegex(RuntimeError, "no explicit decision"):
            source_patch_manifest("v0.20.1")

    def test_windows_engine_fd_applies_the_android_guard_and_checks_it_on_retry(self) -> None:
        upstream, guarded, final = b"upstream\n", b"guarded\n", b"portable\n"
        engine = windows_fd.SOURCE
        build_file = "c/BUILD"
        safety = {name: (source_sha256(upstream), source_sha256(guarded))
                  for name in (engine, build_file)}

        def edit(name: str, before: bytes, after: bytes) -> bytes:
            return (f"diff --git a/{name} b/{name}\n--- a/{name}\n+++ b/{name}\n@@ -1 +1 @@\n".encode()
                    + b"-" + before + b"+" + after)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "c").mkdir()
            (root / engine).write_bytes(upstream)
            (root / build_file).write_bytes(upstream)
            safety_patch, fd_patch = root / "safety.patch", root / "fd.patch"
            safety_patch.write_bytes(edit(engine, upstream, guarded) + edit(build_file, upstream, guarded))
            fd_patch.write_bytes(edit(engine, guarded, final))
            with (patch.multiple(android_gpu_safety_patch, SOURCES=safety, PATCH_PATH=str(safety_patch)),
                  patch.multiple(windows_fd, SOURCES=safety, PATCH_PATH=str(fd_patch),
                                 PREIMAGE_SHA256=source_sha256(guarded), POSTIMAGE_SHA256=source_sha256(final))):
                windows_fd.apply(root, "v0.20.0")
                self.assertEqual((root / engine).read_bytes(), final)
                self.assertEqual((root / build_file).read_bytes(), guarded)
                windows_fd.apply(root, "v0.20.0")
                (root / build_file).write_bytes(upstream)
                with self.assertRaisesRegex(RuntimeError, "C API BUILD source changed"):
                    windows_fd.apply(root, "v0.20.0")
