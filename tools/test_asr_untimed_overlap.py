from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import build_upstream_runtime as build

REPO = Path(__file__).resolve().parents[1]


class AsrUntimedOverlapTest(unittest.TestCase):
    def test_patch_is_exact_idempotent_and_rejects_drift(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "omni/asr/timestamp_text_merger.cc"
            source.parent.mkdir(parents=True)
            original = (REPO / "tools/fixtures/timestamp_text_merger_v018.cc").read_bytes()
            source.write_bytes(original)
            build.patch_asr_untimed_overlap(root, "v0.17.1")
            self.assertEqual(source.read_bytes(), original)
            build.patch_asr_untimed_overlap(root, "v0.18.0")
            patched = source.read_bytes()
            self.assertNotEqual(patched, original)
            build.patch_asr_untimed_overlap(root, "v0.18.0")
            self.assertEqual(source.read_bytes(), patched)
            source.write_bytes(original + b"// drift\n")
            with self.assertRaisesRegex(RuntimeError, "requalify untimed overlap"):
                build.patch_asr_untimed_overlap(root, "v0.18.0")
            self.assertEqual(source.read_bytes(), original + b"// drift\n")

    def test_runtime_patches_before_bazel_including_source_root_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(build, "patch_asr_untimed_overlap", side_effect=RuntimeError("patch gate")) as gate:
                with self.assertRaisesRegex(RuntimeError, "patch gate"):
                    build.build_runtime(root, "macos", "arm64", "v0.18.0", "2")
                gate.assert_called_once_with(root, "v0.18.0")

    def test_patch_applies_inside_a_worktree_without_touching_its_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            upstream = root / ".tmp/upstream"
            source = upstream / "omni/asr/timestamp_text_merger.cc"
            source.parent.mkdir(parents=True)
            original = (REPO / "tools/fixtures/timestamp_text_merger_v018.cc").read_bytes()
            source.write_bytes(original)
            build.patch_asr_untimed_overlap(upstream, "v0.18.0")
            self.assertNotEqual(source.read_bytes(), original)
            self.assertFalse((root / "omni").exists())

    @unittest.skipUnless(os.environ.get("LITERT_LM_ASR_SOURCE"),
                         "Set LITERT_LM_ASR_SOURCE to run real upstream merger qualification")
    def test_real_upstream_merger_and_quantitative_replay(self):
        with tempfile.TemporaryDirectory() as temp:
            subprocess.run([os.sys.executable, str(REPO / "tools/qualify_asr_untimed_overlap.py"),
                            "--source-root", os.environ["LITERT_LM_ASR_SOURCE"],
                            "--work-dir", temp], check=True, stdout=subprocess.PIPE)
