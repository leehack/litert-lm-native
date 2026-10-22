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
    def test_missing_abseil_pkg_config_name_is_actionable(self):
        import qualify_asr_untimed_overlap as qualifier
        qualifier.abseil_flags.cache_clear()
        def probe(command, **kwargs):
            return subprocess.CompletedProcess(command, int(command[-1] == "absl_vlog_config_internal"))
        try:
            with patch.object(qualifier.subprocess, "run", side_effect=probe):
                with self.assertRaisesRegex(RuntimeError, "absl_vlog_config_internal; install/requalify"):
                    qualifier.abseil_flags()
        finally:
            qualifier.abseil_flags.cache_clear()

    def test_newer_and_unknown_versions_require_explicit_patch_decision(self):
        from asr_overlap_patch import source_patch_manifest
        for tag in ("v0.18.2", "v0.19.0", "v1.0.0", "v0.19.0-rc.1", "main"):
            with self.subTest(tag=tag):
                # Check before source I/O or build, and on the release manifest
                # path too. Updating a postimage hash cannot bypass this gate.
                for gate in (lambda: build.patch_asr_untimed_overlap(Path("missing"), tag),
                             lambda: source_patch_manifest(tag)):
                    with self.assertRaisesRegex(RuntimeError, "no explicit decision.*" + tag):
                        gate()

    def test_fast_evaluation_distance_matches_reference(self):
        import random
        from evaluate_asr_overlap import distance
        from sim import ops
        rng = random.Random(673)
        for _ in range(500):
            a = rng.choices("abcd", k=rng.randrange(40))
            b = rng.choices("abcd", k=rng.randrange(40))
            self.assertEqual(distance(a, b), sum(ops(a, b)))

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

    def test_crlf_and_autocrlf_application_and_postimage(self):
        # Extends the audit crlf.sh/crlf2.sh matrix: patch bytes stay LF;
        # pre/post image hashes compare normalized source, even on Windows.
        from asr_overlap_patch import POSTIMAGE_SHA256, source_sha256
        original = (REPO / "tools/fixtures/timestamp_text_merger_v018.cc").read_bytes()
        for autocrlf in ("true", "false"):
            for ending in (b"\n", b"\r\n"):
                with self.subTest(autocrlf=autocrlf, ending=ending), tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    config = root / "gitconfig"
                    config.write_text(f"[core]\n autocrlf = {autocrlf}\n")
                    source = root / "omni/asr/timestamp_text_merger.cc"
                    source.parent.mkdir(parents=True)
                    source.write_bytes(original.replace(b"\n", ending))
                    with patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": str(config)}):
                        build.patch_asr_untimed_overlap(root, "v0.18.0")
                        self.assertEqual(source_sha256(source.read_bytes()), POSTIMAGE_SHA256)
                        build.patch_asr_untimed_overlap(root, "v0.18.0")

    def test_patch_attributes_preserve_lf_on_windows_checkout(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            for name in (".gitattributes", "native/bridge/asr_untimed_overlap.patch"):
                dest = root / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes((REPO / name).read_bytes())
            subprocess.run(["git", "-c", "core.autocrlf=true", "add", "."], cwd=root, check=True)
            target = root / "native/bridge/asr_untimed_overlap.patch"
            target.unlink()
            subprocess.run(["git", "-c", "core.autocrlf=true", "checkout-index", "-a"], cwd=root, check=True)
            self.assertEqual(target.read_bytes(), (REPO / "native/bridge/asr_untimed_overlap.patch").read_bytes())
            self.assertNotIn(b"\r", target.read_bytes())

    def test_postimage_verification_rejects_incorrect_apply(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "omni/asr/timestamp_text_merger.cc"
            source.parent.mkdir(parents=True)
            source.write_bytes((REPO / "tools/fixtures/timestamp_text_merger_v018.cc").read_bytes())
            with patch.object(build.subprocess, "run"):
                with self.assertRaisesRegex(RuntimeError, "postimage mismatch"):
                    build.patch_asr_untimed_overlap(root, "v0.18.0")

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
