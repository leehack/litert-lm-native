from __future__ import annotations

import hashlib
import io
import re
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import build_upstream_runtime as build
from asr_overlap_patch import source_patch_manifest
from test_workspace_build_patch import FIXTURES, stage_v0181
from xnnpack_pf32_sme2_patch import (
    ARCHIVE,
    PATCH_PATH,
    SOURCES,
    TENSORFLOW_REF,
    XNNPACK_COMMIT,
    XNNPACK_SHA256,
    declare_patched_xnnpack,
    require_xnnpack_pf32_patch_decision,
    xnnpack_pf32_patch_manifest,
)

REPO = Path(__file__).resolve().parents[1]
PATCH = (REPO / PATCH_PATH).read_text(encoding="utf-8")
TF_ARCHIVE = 'http_archive(\n    name = "org_tensorflow",\n'


def repaired_v0181_workspace() -> str:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        stage_v0181(root)
        build.patch_workspace_build(root, "v0.18.1")
        return (root / "WORKSPACE").read_text(encoding="utf-8")


class XnnpackPf32Sme2PatchTest(unittest.TestCase):
    def test_decision_applies_only_to_v0181(self) -> None:
        for tag in ("v0.17.1", "v0.18.0"):
            self.assertFalse(require_xnnpack_pf32_patch_decision(tag))
            self.assertEqual(xnnpack_pf32_patch_manifest(tag), [])
        self.assertTrue(require_xnnpack_pf32_patch_decision("v0.18.1"))
        for tag in ("v0.18.2", "v0.19.0", "main"):
            with self.subTest(tag=tag), self.assertRaisesRegex(
                RuntimeError, "no explicit decision"
            ):
                require_xnnpack_pf32_patch_decision(tag)

    def test_patch_restores_only_the_previous_pf32_sme2_kernels(self) -> None:
        files = re.findall(r"^diff --git a/(\S+) b/\1$", PATCH, re.MULTILINE)
        self.assertEqual(files, list(SOURCES))
        self.assertEqual(re.findall(r"^--- a/(\S+)$", PATCH, re.MULTILINE), files)
        self.assertEqual(re.findall(r"^\+\+\+ b/(\S+)$", PATCH, re.MULTILINE), files)
        self.assertNotRegex(PATCH, r"(?m)^index ")
        sections = dict(zip(files, re.split(r"(?m)^diff --git .*\n", PATCH)[1:]))

        def changed(section: str, sign: str) -> list[str]:
            return re.findall(rf"^\{sign}(?!\{sign}\{sign} )(.*)$", section, re.MULTILINE)

        config = sections["src/configs/gemm-config.c"]
        self.assertEqual(len(re.findall(r"^@@ ", config, re.MULTILINE)), 1)
        self.assertEqual([line.replace("_sme2;", "_sme;") for line in changed(config, "-")],
                         changed(config, "+"))
        self.assertIn("xnn_pf32_igemm_minmax_ukernel_32x32__neonsme2", config)
        kernels = "".join(sections[name] for name in files[1:])
        added, removed = "\n".join(changed(kernels, "+")), "\n".join(changed(kernels, "-"))
        for previous in ("kai_run_matmul_clamp_f32_f32_f32p2vlx1b_1x16vl_sme2_mla(",
                         "kai_run_matmul_clamp_f32_f32p2vlx1_f32p2vlx1biasf32_sme2_mopa(",
                         "kai_run_lhs_pack_f32p2vlx1_f32_sme(",
                         "kai_get_lhs_packed_size_lhs_pack_f32p2vlx1_f32_sme(",
                         "kai_get_lhs_packed_offset_lhs_pack_f32p2vlx1_f32_sme("):
            self.assertIn(previous, added)
        for current in ("kai_matmul_clamp_f32_f32_f32p4vsx1bf32_1x32vs_sme2_mla()",
                        "kai_matmul_clamp_f32_f32p4vsx1_f32p4vsx1bf32_8vsx8vs_sme2_mopa()",
                        "kai_matmul_pack_lhs_mxk_x32p4vsx1_x32_sme()"):
            self.assertIn(current, removed)
            self.assertNotIn(current, added)
        self.assertNotIn("Copyright", added + removed)

    def test_workspace_declares_the_tensorflow_pinned_xnnpack_before_tensorflow(self) -> None:
        workspace = repaired_v0181_workspace()
        patched = declare_patched_xnnpack(workspace)
        self.assertEqual(declare_patched_xnnpack(patched), patched)
        self.assertEqual(patched.replace(ARCHIVE, "", 1), workspace)
        self.assertEqual(patched.count('name = "XNNPACK"'), 1)
        self.assertLess(patched.index(ARCHIVE), patched.index(TF_ARCHIVE))
        self.assertLess(patched.index('load("@bazel_tools//tools/build_defs/repo:http.bzl"'),
                        patched.index(ARCHIVE))
        self.assertLess(patched.index(ARCHIVE), patched.index("tf_workspace2()"))
        for expected in (f'sha256 = "{XNNPACK_SHA256}"',
                         f'strip_prefix = "XNNPACK-{XNNPACK_COMMIT}"',
                         f'"https://github.com/google/XNNPACK/archive/{XNNPACK_COMMIT}.zip"',
                         '"@//bridge:xnnpack_pf32_sme2.patch",'):
            self.assertIn(expected, ARCHIVE)
        self.assertIn('"xnnpack_pf32_sme2.patch"',
                      (REPO / "native/bridge/BUILD.bazel").read_text(encoding="utf-8"))

    def test_workspace_declaration_fails_closed(self) -> None:
        workspace = repaired_v0181_workspace()
        moved = workspace.replace(TENSORFLOW_REF, "0" * 40)
        existing = workspace.replace(TF_ARCHIVE, 'http_archive(\n    name = "XNNPACK",\n)\n' + TF_ARCHIVE)
        missing = workspace.replace("# TensorFlow\n", "")
        for text, message in ((moved, "TensorFlow pin changed"),
                              (existing, "Unexpected XNNPACK archive"),
                              (missing, "Expected one TensorFlow archive")):
            with self.subTest(message=message), self.assertRaisesRegex(RuntimeError, message):
                declare_patched_xnnpack(text)

    def test_download_declares_xnnpack_only_for_v0181(self) -> None:
        def fake_download(_url, path, **_kwargs):
            with tarfile.open(path, "w:gz") as archive:
                for source, fixture in FIXTURES.items():
                    data = (REPO / "tools/fixtures" / fixture).read_bytes()
                    info = tarfile.TarInfo(f"LiteRT-LM-v0.18.1/{source}")
                    info.size = len(data)
                    archive.addfile(info, io.BytesIO(data))

        with tempfile.TemporaryDirectory() as temp, \
             patch.object(build, "download_to_path", side_effect=fake_download):
            root = build.download_upstream("v0.18.1", "v0.18.1", Path(temp))
            self.assertIn(ARCHIVE, (root / "WORKSPACE").read_text(encoding="utf-8"))
        for tag, enabled in (("v0.18.0", False), ("v0.18.1", True)):
            with self.subTest(tag=tag), tempfile.TemporaryDirectory() as temp:
                source = Path(temp) / "source"
                source.mkdir()
                (source / "WORKSPACE").write_text("", encoding="utf-8")
                with patch.object(build, "download_to_path"), \
                     patch.object(build.tarfile, "open"), \
                     patch.object(build, "patch_workspace_build"), \
                     patch.object(build, "needs_gpu_environment_teardown_patch", return_value=False), \
                     patch.object(build, "patch_upstream_workspace") as apply:
                    build.download_upstream(tag, tag, Path(temp))
                self.assertEqual(apply.call_args.kwargs["patch_xnnpack_pf32_sme2"], enabled)

    def test_postimage_check_reads_every_source_in_the_bazel_external_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output_base = Path(temp)
            source_root = output_base / "execroot" / "litert_lm"
            (source_root / "bazel-out").mkdir(parents=True)
            repository = output_base / "external" / "XNNPACK"
            digest = hashlib.sha256(b"patched\n").hexdigest()
            fake = {"a.c": ("0" * 64, digest), "b/c.c": ("0" * 64, digest)}
            fake = {name: postimage for name, (_, postimage) in fake.items()}
            with patch.object(build, "XNNPACK_POSTIMAGES", fake):
                with self.assertRaisesRegex(RuntimeError, "postimage mismatch"):
                    build.verify_xnnpack_postimages(source_root)
                for name in fake:
                    (repository / name).parent.mkdir(parents=True, exist_ok=True)
                    (repository / name).write_bytes(b"patched\r\n")
                build.verify_xnnpack_postimages(source_root)
                (repository / "b/c.c").write_bytes(b"unpatched\n")
                with self.assertRaisesRegex(RuntimeError, "postimage mismatch"):
                    build.verify_xnnpack_postimages(source_root)

    def test_build_checks_the_postimage_after_bazel_only_for_v0181(self) -> None:
        for tag, checked in (("v0.18.0", False), ("v0.18.1", True)):
            calls = MagicMock()
            with self.subTest(tag=tag), tempfile.TemporaryDirectory() as temp, \
                 patch.object(build, "patch_asr_untimed_overlap"), \
                 patch.object(build, "patch_asr_litertlm_container"), \
                 patch.object(build, "patch_stream_finish_reason"), \
                 patch.object(build, "materialize_git_lfs_libraries", return_value=0), \
                 patch.object(build, "bazel_command", return_value=["bazel"]), \
                 patch.object(build, "run", calls.run), \
                 patch.object(build, "verify_xnnpack_postimages", calls.verify), \
                 patch.object(build, "verify_cpu_options_identifier_postimage"):
                root = Path(temp)
                with self.assertRaisesRegex(RuntimeError, "Expected build output missing"):
                    build.build_runtime(root, "macos", "arm64", tag, "2")
                names = [name for name, _, _ in calls.mock_calls]
                self.assertEqual(names, ["run", "verify"] if checked else ["run"])
                if checked:
                    calls.verify.assert_called_once_with(root)

    def test_manifest_records_each_xnnpack_source_before_the_qc4w_opt_out(self) -> None:
        records = [r for r in source_patch_manifest("v0.18.1")
                   if r["id"] not in {"xnnpack-pqs8-qc4w-sme2", "litert-cpu-options-identifier"}]
        self.assertEqual(records[-len(SOURCES):], xnnpack_pf32_patch_manifest("v0.18.1"))
        patch_sha256 = hashlib.sha256((REPO / PATCH_PATH).read_bytes()).hexdigest()
        for record, (source, hashes) in zip(records[-len(SOURCES):], SOURCES.items()):
            self.assertEqual(record["id"], "xnnpack-pf32-sme2")
            self.assertEqual(record["path"], PATCH_PATH)
            self.assertEqual(record["sha256"], patch_sha256)
            self.assertEqual(record["source"], f"XNNPACK@{XNNPACK_COMMIT}/{source}")
            self.assertEqual((record["preimageSha256Lf"], record["postimageSha256Lf"]), hashes)
        self.assertNotIn("xnnpack-pf32-sme2", {r["id"] for r in source_patch_manifest("v0.18.0")})

if __name__ == "__main__":
    unittest.main()
