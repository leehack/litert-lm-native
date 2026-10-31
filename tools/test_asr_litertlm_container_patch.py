from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import build_upstream_runtime as build
from asr_litertlm_container_patch import SOURCES, container_patch_manifest
from asr_overlap_patch import source_sha256

REPO = Path(__file__).resolve().parents[1]
FIXTURES = {
    "omni/asr/BUILD": "omni_asr_BUILD_v018.txt",
    "omni/asr/asr_engine.cc": "asr_engine_v018.cc",
    "omni/asr/asr_engine.h": "asr_engine_v018.h",
}


def stage_preimage(root: Path) -> None:
    for source, fixture in FIXTURES.items():
        path = root / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((REPO / "tools/fixtures" / fixture).read_bytes())


class AsrLitertLmContainerPatchTest(unittest.TestCase):
    def test_patch_is_exact_idempotent_and_routes_by_container_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stage_preimage(root)
            build.patch_asr_litertlm_container(root, "v0.17.1")
            for source, (preimage, _) in SOURCES.items():
                self.assertEqual(source_sha256((root / source).read_bytes()), preimage)

            build.patch_asr_litertlm_container(root, "v0.18.0")
            for source, (_, postimage) in SOURCES.items():
                self.assertEqual(source_sha256((root / source).read_bytes()), postimage)
            engine = (root / "omni/asr/asr_engine.cc").read_text()
            self.assertNotIn('absl::EndsWith(config.model_path, ".litertlm");\n  if (!use_litert_lm)', engine)
            self.assertIn("ResolveDecoderTypeFromLitertLm(*lm_resources, config);", engine)
            self.assertIn("AsrMetadata::TF_LITE_ENCODER_DECODER", engine)
            self.assertIn("model_resources_(std::move(model_resources))", engine)

            patched = {source: (root / source).read_bytes() for source in SOURCES}
            build.patch_asr_litertlm_container(root, "v0.18.0")
            for source, data in patched.items():
                self.assertEqual((root / source).read_bytes(), data)

    def test_rejects_drift_without_mutation(self):
        for drifted in SOURCES:
            with self.subTest(drifted=drifted), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                stage_preimage(root)
                path = root / drifted
                path.write_bytes(path.read_bytes() + b"# drift\n")
                before = {source: (root / source).read_bytes() for source in SOURCES}
                with self.assertRaisesRegex(RuntimeError, "requalify .litertlm container patch"):
                    build.patch_asr_litertlm_container(root, "v0.18.0")
                for source, data in before.items():
                    self.assertEqual((root / source).read_bytes(), data)

    def test_rejects_partial_postimage_without_mutation(self):
        for patched in SOURCES:
            with self.subTest(patched=patched), tempfile.TemporaryDirectory() as temp:
                complete = Path(temp) / "complete"
                stage_preimage(complete)
                build.patch_asr_litertlm_container(complete, "v0.18.0")
                root = Path(temp) / "partial"
                stage_preimage(root)
                (root / patched).write_bytes((complete / patched).read_bytes())
                before = {source: (root / source).read_bytes() for source in SOURCES}
                with self.assertRaisesRegex(RuntimeError, "requalify .litertlm container patch"):
                    build.patch_asr_litertlm_container(root, "v0.18.0")
                for source, data in before.items():
                    self.assertEqual((root / source).read_bytes(), data)

    def test_patch_applies_inside_a_worktree_without_touching_its_root(self):
        # Windows builds extract upstream under REPO_ROOT/.tmp, inside a checkout.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            upstream = root / ".tmp/upstream"
            stage_preimage(upstream)
            build.patch_asr_litertlm_container(upstream, "v0.18.0")
            for source, (_, postimage) in SOURCES.items():
                self.assertEqual(source_sha256((upstream / source).read_bytes()), postimage)
            self.assertFalse((root / "omni").exists())

    def test_postimage_verification_rejects_incorrect_apply(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stage_preimage(root)
            with patch.object(build.subprocess, "run"):
                with self.assertRaisesRegex(RuntimeError, "postimage mismatch"):
                    build.patch_asr_litertlm_container(root, "v0.18.0")

    def test_newer_and_unknown_versions_require_explicit_decision(self):
        for tag in ("v0.18.2", "v0.19.1", "main"):
            with self.subTest(tag=tag):
                for gate in (lambda: build.patch_asr_litertlm_container(Path("missing"), tag),
                             lambda: container_patch_manifest(tag)):
                    with self.assertRaisesRegex(RuntimeError, "no explicit decision.*" + tag):
                        gate()

    def test_runtime_applies_container_patch_before_bazel(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with (patch.object(build, "patch_asr_untimed_overlap"),
                  patch.object(build, "patch_asr_litertlm_container",
                               side_effect=RuntimeError("container gate")) as gate):
                with self.assertRaisesRegex(RuntimeError, "container gate"):
                    build.build_runtime(root, "macos", "arm64", "v0.18.0", "2")
                gate.assert_called_once_with(root, "v0.18.0")

    def test_manifest_records_every_patched_source(self):
        records = container_patch_manifest("v0.18.0")
        self.assertEqual([record["source"] for record in records], list(SOURCES))
        self.assertEqual({record["id"] for record in records}, {"asr-litertlm-container"})
        self.assertEqual(container_patch_manifest("v0.17.1"), [])


if __name__ == "__main__":
    unittest.main()
