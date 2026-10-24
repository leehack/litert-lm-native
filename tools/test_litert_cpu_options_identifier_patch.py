from __future__ import annotations

import hashlib
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import build_upstream_runtime as build
from asr_overlap_patch import source_patch_manifest, source_sha256
from litert_cpu_options_identifier_patch import (
    DYNAMIC_RUNTIMES,
    LITERT_REF,
    PATCH_PATH,
    SOURCE,
    SOURCES,
    cpu_options_identifier_patch_manifest,
    require_cpu_options_identifier_patch_decision,
    verify_dynamic_runtime,
)
from test_workspace_build_patch import stage_v0181

REPO = Path(__file__).resolve().parents[1]
PATCH = (REPO / PATCH_PATH).read_text(encoding="utf-8")
FIXTURE = REPO / "tools/fixtures/litert_cpu_options_ca21dc99.cc"


class CpuOptionsIdentifierPatchTest(unittest.TestCase):
    def test_decision_applies_only_to_v0181(self) -> None:
        for tag in ("v0.17.1", "v0.18.0"):
            self.assertFalse(require_cpu_options_identifier_patch_decision(tag))
            self.assertEqual(cpu_options_identifier_patch_manifest(tag), [])
        self.assertTrue(require_cpu_options_identifier_patch_decision("v0.18.1"))
        for tag in ("v0.18.2", "v0.19.0", "main"):
            with self.subTest(tag=tag), self.assertRaisesRegex(
                RuntimeError, "no explicit decision"
            ):
                require_cpu_options_identifier_patch_decision(tag)

    def test_patch_changes_only_the_identifier_to_the_prebuilt_one(self) -> None:
        self.assertEqual(re.findall(r"^diff --git a/(\S+) b/\1$", PATCH, re.MULTILINE), [SOURCE])
        removed = re.findall(r"^-(?!-- )(.*)$", PATCH, re.MULTILINE)
        added = [line for line in re.findall(r"^\+(?!\+\+ )(.*)$", PATCH, re.MULTILINE)
                 if not line.startswith("//")]
        self.assertEqual(removed, ['const char* LrtGetCpuOptionsIdentifier() { return "cpu_options"; }'])
        self.assertEqual(added, ['const char* LrtGetCpuOptionsIdentifier() { return "xnnpack"; }'])

    def test_patch_turns_the_pinned_preimage_into_the_postimage(self) -> None:
        preimage, postimage = SOURCES[SOURCE]
        self.assertEqual(source_sha256(FIXTURE.read_bytes()), preimage)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / SOURCE).parent.mkdir(parents=True)
            (root / SOURCE).write_bytes(FIXTURE.read_bytes())
            subprocess.run(["git", "apply", str(REPO / PATCH_PATH)], cwd=root, check=True)
            self.assertEqual(source_sha256((root / SOURCE).read_bytes()), postimage)

    def test_v0181_workspace_patches_the_litert_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stage_v0181(root)
            build.patch_workspace_build(root, "v0.18.1")
            build.patch_upstream_workspace(root, patch_cpu_options_identifier=True)
            workspace = (root / "WORKSPACE").read_text(encoding="utf-8")
        self.assertIn('"@//bridge:litert_cpu_options_identifier.patch"]', workspace)
        refs = re.findall(r'^LITERT_REF = "([0-9a-f]{40})"$', workspace, re.MULTILINE)
        self.assertEqual(refs[-1], LITERT_REF)
        self.assertIn('"litert_cpu_options_identifier.patch"',
                      (REPO / "native/bridge/BUILD.bazel").read_text(encoding="utf-8"))

    def test_dynamic_hosts_require_the_audited_prebuilt_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            name, _ = DYNAMIC_RUNTIMES[("linux", "arm64")]
            (root / name).parent.mkdir(parents=True)
            (root / name).write_bytes(b"newer runtime")
            with self.assertRaisesRegex(RuntimeError, "requalify"):
                verify_dynamic_runtime(root, "linux", "arm64")
            with self.assertRaisesRegex(RuntimeError, "requalify"):
                verify_dynamic_runtime(root, "windows", "x64")
            verify_dynamic_runtime(root, "macos", "arm64")
            verify_dynamic_runtime(root, "android", "arm64")
            with patch("litert_cpu_options_identifier_patch.DYNAMIC_RUNTIMES",
                       {("linux", "arm64"): (name, hashlib.sha256(b"newer runtime").hexdigest())}):
                verify_dynamic_runtime(root, "linux", "arm64")

    def test_build_checks_runtime_and_postimage_only_for_v0181(self) -> None:
        for tag, checked in (("v0.18.0", False), ("v0.18.1", True)):
            calls = MagicMock()
            with self.subTest(tag=tag), tempfile.TemporaryDirectory() as temp, \
                 patch.object(build, "patch_asr_untimed_overlap"), \
                 patch.object(build, "patch_asr_litertlm_container"), \
                 patch.object(build, "patch_stream_finish_reason"), \
                 patch.object(build, "materialize_git_lfs_libraries", return_value=0), \
                 patch.object(build, "bazel_command", return_value=["bazel"]), \
                 patch.object(build, "run", calls.run), \
                 patch.object(build, "verify_xnnpack_postimages"), \
                 patch.object(build, "verify_dynamic_runtime", calls.runtime), \
                 patch.object(build, "verify_cpu_options_identifier_postimage", calls.postimage):
                root = Path(temp)
                with self.assertRaisesRegex(RuntimeError, "Expected build output missing"):
                    build.build_runtime(root, "linux", "arm64", tag, "2")
                names = [name for name, _, _ in calls.mock_calls]
                self.assertEqual(names, ["runtime", "run", "postimage"] if checked else ["run"])
                if checked:
                    calls.runtime.assert_called_once_with(root / "prebuilt", "linux", "arm64")
                    calls.postimage.assert_called_once_with(root)

    def test_postimage_check_reads_the_bazel_litert_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output_base = Path(temp) / "output_base"
            source_root = Path(temp) / "source"
            exec_root = output_base / "execroot" / "litert_lm"
            (exec_root / "bazel-out").mkdir(parents=True)
            source_root.mkdir()
            (source_root / "bazel-out").symlink_to(exec_root / "bazel-out")
            source = output_base / "external" / "litert" / SOURCE
            source.parent.mkdir(parents=True)
            source.write_bytes(FIXTURE.read_bytes())
            with self.assertRaisesRegex(RuntimeError, "postimage mismatch"):
                build.verify_cpu_options_identifier_postimage(source_root)
            subprocess.run(["git", "apply", str(REPO / PATCH_PATH)],
                           cwd=output_base / "external" / "litert", check=True)
            build.verify_cpu_options_identifier_postimage(source_root)

    def test_manifest_records_the_rollback_last(self) -> None:
        records = source_patch_manifest("v0.18.1")
        self.assertEqual(records[-1:], cpu_options_identifier_patch_manifest("v0.18.1"))
        record = records[-1]
        self.assertEqual(record["id"], "litert-cpu-options-identifier")
        self.assertEqual(record["sha256"], hashlib.sha256((REPO / PATCH_PATH).read_bytes()).hexdigest())
        self.assertEqual(record["source"], f"LiteRT@{LITERT_REF}/{SOURCE}")
        self.assertEqual((record["preimageSha256Lf"], record["postimageSha256Lf"]), SOURCES[SOURCE])


if __name__ == "__main__":
    unittest.main()
