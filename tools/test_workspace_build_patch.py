from __future__ import annotations

import io
import re
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import build_upstream_runtime as build
from asr_overlap_patch import source_patch_manifest, source_sha256
from workspace_build_patch import (
    PATCH_PATH,
    SOURCES,
    require_workspace_build_patch_decision,
    workspace_build_patch_manifest,
)

REPO = Path(__file__).resolve().parents[1]
PATCH = (REPO / PATCH_PATH).read_text(encoding="utf-8")
FIXTURES = {
    "WORKSPACE": "litert_lm_v0.18.1_WORKSPACE",
    ".bazelrc": "litert_lm_v0.18.1.bazelrc",
}


def stage_v0181(root: Path) -> None:
    for source, fixture in FIXTURES.items():
        (root / source).write_bytes((REPO / "tools/fixtures" / fixture).read_bytes())


class WorkspaceBuildPatchTest(unittest.TestCase):
    def test_decision_applies_only_to_v0181(self) -> None:
        for tag in ("v0.17.1", "v0.18.0"):
            self.assertFalse(require_workspace_build_patch_decision(tag))
            self.assertEqual(workspace_build_patch_manifest(tag), [])
        self.assertTrue(require_workspace_build_patch_decision("v0.18.1"))
        for tag in ("v0.18.2", "v0.19.1", "main"):
            with self.subTest(tag=tag), self.assertRaisesRegex(
                RuntimeError, "no explicit decision"
            ):
                require_workspace_build_patch_decision(tag)

    def test_patch_is_plain_and_touches_exactly_the_pinned_files(self) -> None:
        targets = re.findall(r"^\+\+\+ b/(\S+)$", PATCH, re.MULTILINE)
        self.assertEqual(sorted(targets), sorted(SOURCES))
        self.assertEqual(re.findall(r"^--- a/(\S+)$", PATCH, re.MULTILINE), targets)
        self.assertNotRegex(PATCH, r"(?m)^(diff --git|index )")

    def test_fixtures_are_the_audited_preimages(self) -> None:
        for source, fixture in FIXTURES.items():
            digest = source_sha256((REPO / "tools/fixtures" / fixture).read_bytes())
            self.assertEqual(digest, SOURCES[source][0])

    def test_repair_loads_compatibility_proxy_and_keeps_effective_pins(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stage_v0181(root)
            before = (root / "WORKSPACE").read_text(encoding="utf-8")
            build.patch_workspace_build(root, "v0.18.1")
            after = (root / "WORKSPACE").read_text(encoding="utf-8")
            for source, (_, post) in SOURCES.items():
                self.assertEqual(source_sha256((root / source).read_bytes()), post)
            for name in ("LITERT_REF", "LITERT_SHA256", "TENSORFLOW_REF", "TENSORFLOW_SHA256"):
                pattern = rf'^{name} = "([0-9a-f]+)"$'
                self.assertEqual(re.findall(pattern, after, re.MULTILINE),
                                 re.findall(pattern, before, re.MULTILINE)[-1:])
            self.assertIn('load("@rules_cc//cc:extensions.bzl", "compatibility_proxy_repo")', after)
            self.assertLess(after.index("tf_workspace3()"), after.index("compatibility_proxy_repo()"))
            self.assertLess(after.index("compatibility_proxy_repo()"), after.index("go_rules_dependencies()"))
            self.assertIn("build:windows --define=xnn_enable_avx512bf16=false",
                          (root / ".bazelrc").read_text(encoding="utf-8"))
            # The owner WORKSPACE edits still find their anchors afterwards.
            self.assertFalse(build.needs_gpu_environment_teardown_patch(after, "v0.18.1"))
            build.patch_upstream_workspace(root, patch_bpe_null_piece=True)

    def test_repair_fails_closed_on_drift_and_reapplication(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stage_v0181(root)
            build.patch_workspace_build(root, "v0.18.1")
            with self.assertRaisesRegex(RuntimeError, "requalify the WORKSPACE build repair"):
                build.patch_workspace_build(root, "v0.18.1")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stage_v0181(root)
            with (root / ".bazelrc").open("a", encoding="utf-8") as bazelrc:
                bazelrc.write("# drift\n")
            with self.assertRaisesRegex(RuntimeError, "requalify the WORKSPACE build repair"):
                build.patch_workspace_build(root, "v0.18.1")
        build.patch_workspace_build(Path("missing"), "v0.18.0")

    def test_repair_fails_when_the_applied_postimage_is_wrong(self) -> None:
        wrong = {name: (pre, "0" * 64) for name, (pre, _) in SOURCES.items()}
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(build, "WORKSPACE_BUILD_PATCH_SOURCES", wrong):
            root = Path(temp)
            stage_v0181(root)
            with self.assertRaisesRegex(RuntimeError, "postimage mismatch"):
                build.patch_workspace_build(root, "v0.18.1")

    def test_download_repairs_workspace_before_owner_workspace_edits(self) -> None:
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
            self.assertEqual(source_sha256((root / ".bazelrc").read_bytes()), SOURCES[".bazelrc"][1])
            workspace = (root / "WORKSPACE").read_text(encoding="utf-8")
            self.assertIn("compatibility_proxy_repo()", workspace)
            self.assertIn("@//bridge:sentencepiece_bpe_null.patch", workspace)

    def test_manifest_records_both_files_after_the_other_carries(self) -> None:
        records = [r for r in source_patch_manifest("v0.18.1")
                   if r["id"] not in {"xnnpack-pf32-sme2", "xnnpack-pqs8-qc4w-sme2",
                                       "litert-cpu-options-identifier"}]
        self.assertEqual(records[-2:], workspace_build_patch_manifest("v0.18.1"))
        self.assertEqual([record["source"] for record in records[-2:]], list(SOURCES))
        self.assertNotIn("workspace-build", {r["id"] for r in source_patch_manifest("v0.18.0")})


if __name__ == "__main__":
    unittest.main()
