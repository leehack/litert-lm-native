from __future__ import annotations

import hashlib
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import build_upstream_runtime
from stream_finish_reason_patch import (
    BAZEL_DEFINE,
    PATCH_PATH,
    SOURCES,
    finish_reason_patch_manifest,
    require_finish_reason_patch_decision,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PATCH = (REPO_ROOT / PATCH_PATH).read_text(encoding="utf-8")
BRIDGE = (REPO_ROOT / "native/bridge/litert_lm_bridge.c").read_text(encoding="utf-8")
BRIDGE_BUILD = (REPO_ROOT / "native/bridge/BUILD.bazel").read_text(encoding="utf-8")


class StreamFinishReasonPatchTest(unittest.TestCase):
    def test_decision_applies_only_to_audited_v018(self) -> None:
        for tag in ("v0.15.0", "v0.16.1", "v0.17.1"):
            self.assertFalse(require_finish_reason_patch_decision(tag))
            self.assertEqual(finish_reason_patch_manifest(tag), [])
        for tag in ("v0.18.0", "v0.18.1"):
            self.assertTrue(require_finish_reason_patch_decision(tag))
        for tag in ("v0.18.2", "v0.19.1", "main"):
            with self.subTest(tag=tag), self.assertRaisesRegex(
                RuntimeError, "no explicit decision"
            ):
                require_finish_reason_patch_decision(tag)

    def test_patch_is_plain_and_touches_exactly_the_pinned_sources(self) -> None:
        targets = re.findall(r"^\+\+\+ b/(\S+)$", PATCH, re.MULTILINE)
        sources = re.findall(r"^--- a/(\S+)$", PATCH, re.MULTILINE)
        self.assertEqual(sorted(targets), sorted(SOURCES))
        self.assertEqual(sources, targets)
        self.assertNotRegex(PATCH, r"(?m)^(diff --git|index )")

    def test_runtime_and_bridge_share_finish_reason_wire_values(self) -> None:
        runtime = {
            name.lower(): int(value)
            for name, value in re.findall(
                r"^\+\s+kFinishReason(\w+) = (\d+),$", PATCH, re.MULTILINE
            )
        }
        bridge = {
            name.replace("_", "").lower(): int(value)
            for name, value in re.findall(
                r"STREAM_PROXY_FINISH_REASON_(\w+) = (\d+),", BRIDGE
            )
        }
        self.assertEqual(runtime, bridge)
        self.assertEqual(
            bridge,
            {"unknown": 0, "stop": 1, "length": 2, "contextexhausted": 3,
             "cancelled": 4, "error": 5},
        )

    def test_bazel_define_selects_the_bridge_finish_reason_api(self) -> None:
        define = BAZEL_DEFINE.removeprefix("--define=")
        key, value = define.split("=")
        self.assertIn(f'define_values = {{"{key}": "{value}"}}', BRIDGE_BUILD)
        self.assertIn('":finish_reason_api": ["LITERT_LM_FINISH_REASON_API=1"]',
                      BRIDGE_BUILD)
        self.assertIn('"stream_finish_reason.patch"', BRIDGE_BUILD)

    def test_build_applies_patch_and_define_only_for_v018(self) -> None:
        for tag, expected in (("v0.17.1", False), ("v0.18.0", True), ("v0.18.1", True)):
            with self.subTest(tag=tag), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                with patch.object(build_upstream_runtime, "materialize_git_lfs_libraries", return_value=0), \
                     patch.object(build_upstream_runtime, "patch_asr_untimed_overlap"), \
                     patch.object(build_upstream_runtime, "patch_asr_litertlm_container"), \
                     patch.object(build_upstream_runtime, "patch_upstream_ios_sampler_path"), \
                     patch.object(build_upstream_runtime, "patch_stream_finish_reason") as apply, \
                     patch.object(build_upstream_runtime, "bazel_command", return_value=["bazel"]), \
                     patch.object(build_upstream_runtime, "run", side_effect=RuntimeError("captured build")) as run:
                    with self.assertRaisesRegex(RuntimeError, "captured build"):
                        build_upstream_runtime.build_runtime(root, "macos", "arm64", tag, "3")
                apply.assert_called_once_with(root, tag)
                self.assertEqual(BAZEL_DEFINE in run.call_args.args[0], expected)

    def test_patch_fails_closed_on_unaudited_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in SOURCES:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("// not the audited v0.18.0 source\n")
            with self.assertRaisesRegex(RuntimeError, "requalify the stream finish-reason patch"):
                build_upstream_runtime.patch_stream_finish_reason(root, "v0.18.0")
            build_upstream_runtime.patch_stream_finish_reason(root, "v0.17.1")

    def _fake_sources(self, root: Path) -> dict[str, tuple[str, str]]:
        sources = {}
        for name in ("a.cc", "b.h"):
            sources[name] = (
                hashlib.sha256(f"pre {name}\n".encode()).hexdigest(),
                hashlib.sha256(f"post {name}\n".encode()).hexdigest(),
            )
        return sources

    def _apply(self, root: Path, contents: dict[str, str], git_apply_writes: str):
        sources = self._fake_sources(root)
        for name, prefix in contents.items():
            (root / name).write_text(f"{prefix} {name}\n")

        def git_apply(command, **_kwargs):
            if "--check" not in command:
                for name in sources:
                    (root / name).write_text(f"{git_apply_writes} {name}\n")

        with patch.object(build_upstream_runtime, "finish_reason_patch_sources", return_value=sources), \
             patch.object(build_upstream_runtime.subprocess, "run", side_effect=git_apply) as run:
            build_upstream_runtime.patch_stream_finish_reason(root, "v0.18.0")
        return run

    def test_patch_applies_to_preimage_and_checks_postimage(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = self._apply(Path(temp), {"a.cc": "pre", "b.h": "pre"}, "post")
            self.assertEqual(run.call_count, 2)

    def test_patch_rejects_an_unexpected_postimage(self) -> None:
        with tempfile.TemporaryDirectory() as temp, self.assertRaisesRegex(
            RuntimeError, "postimage mismatch"
        ):
            self._apply(Path(temp), {"a.cc": "pre", "b.h": "pre"}, "drifted")

    def test_patch_skips_only_when_every_source_is_patched(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = self._apply(Path(temp), {"a.cc": "post", "b.h": "post"}, "post")
            run.assert_not_called()
        with tempfile.TemporaryDirectory() as temp, self.assertRaisesRegex(
            RuntimeError, "requalify the stream finish-reason patch"
        ):
            self._apply(Path(temp), {"a.cc": "post", "b.h": "pre"}, "post")


if __name__ == "__main__":
    unittest.main()
