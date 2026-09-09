from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import build_upstream_runtime


class BuildUpstreamRuntimeTest(unittest.TestCase):
    def test_workspace_accepts_upstream_v017_zlib_mirrors(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "WORKSPACE"
            text = ('http_archive(\n    name = "minizip",\n    urls = [\n'
                    '        "https://mirror.bazel.build/zlib.net/fossils/zlib-1.3.1.tar.gz",\n'
                    f'        "{build_upstream_runtime.ZLIB_URL}",\n    ],\n)\n')
            workspace.write_text(text)
            build_upstream_runtime.patch_upstream_workspace(
                root, patch_ios_framework_paths=False)
            self.assertEqual(workspace.read_text(), text)
            workspace.write_text(text.replace(build_upstream_runtime.ZLIB_URL, "https://invalid.example/zlib"))
            with self.assertRaisesRegex(RuntimeError, "Expected zlib URL"):
                build_upstream_runtime.patch_upstream_workspace(
                    root, patch_ios_framework_paths=False)

    def test_source_archive_filename_never_contains_the_raw_ref_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = build_upstream_runtime.source_archive_path(
                root, "refs/tags/x/../../escape"
            )

            self.assertEqual(archive.parent, root)
            self.assertNotIn("refs", archive.name)
            self.assertNotIn("..", archive.name)
            self.assertRegex(archive.name, r"^LiteRT-LM-[0-9a-f]{64}\.tar\.gz$")

    def test_workspace_adds_litert_apple_framework_patch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "WORKSPACE"
            workspace.write_text(
                "\n".join(
                    [
                        "http_archive(",
                        '    name = "minizip",',
                        f'    url = "{build_upstream_runtime.ZLIB_URL}",',
                        ")",
                        "http_archive(",
                        '    name = "litert",',
                        ")",
                    ]
                ),
                encoding="utf-8",
            )

            build_upstream_runtime.patch_upstream_workspace(root)
            build_upstream_runtime.patch_upstream_workspace(root)

            patched = workspace.read_text(encoding="utf-8")
            self.assertEqual(
                patched.count("litert_ios_framework_paths.patch"),
                1,
            )
            self.assertIn(
                build_upstream_runtime.ZLIB_GITHUB_MIRROR_URL,
                patched,
            )

    def test_legacy_workspace_keeps_litert_archive_unpatched(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "WORKSPACE"
            workspace.write_text(
                "\n".join(
                    [
                        "http_archive(",
                        '    name = "minizip",',
                        f'    url = "{build_upstream_runtime.ZLIB_URL}",',
                        ")",
                        "http_archive(",
                        '    name = "litert",',
                        ")",
                    ]
                ),
                encoding="utf-8",
            )

            build_upstream_runtime.patch_upstream_workspace(
                root,
                patch_ios_framework_paths=False,
            )

            patched = workspace.read_text(encoding="utf-8")
            self.assertNotIn("litert_ios_framework_paths.patch", patched)
            self.assertIn(build_upstream_runtime.ZLIB_GITHUB_MIRROR_URL, patched)

    def test_ios_sampler_uses_embedded_framework_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sampler = root / "runtime" / "components" / "sampler_factory.cc"
            sampler.parent.mkdir(parents=True)
            sampler.write_text(
                'auto path = "libLiteRtTopKMetalSampler.dylib";\n',
                encoding="utf-8",
            )

            build_upstream_runtime.patch_upstream_ios_sampler_path(root)

            self.assertIn(
                "@executable_path/Frameworks/"
                "LiteRtTopKMetalSampler.framework/LiteRtTopKMetalSampler",
                sampler.read_text(encoding="utf-8"),
            )

    def test_windows_stages_materialized_runtime_dlls_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_dir = root / "source" / "prebuilt" / "windows_x86_64"
            source_dir.mkdir(parents=True)
            (source_dir / "LiteRt.dll").write_bytes(b"runtime")
            (source_dir / "LiteRt.lib").write_bytes(b"link-library")
            output = root / "bin"

            with patch.object(build_upstream_runtime, "BIN_DIR", output):
                build_upstream_runtime.stage_windows_runtime_dependencies(
                    root / "source",
                    "x64",
                )

            self.assertEqual(
                (output / "windows" / "x64" / "LiteRt.dll").read_bytes(),
                b"runtime",
            )
            self.assertFalse(
                (output / "windows" / "x64" / "LiteRt.lib").exists()
            )

    def test_runtime_override_is_filtered_to_the_target(self) -> None:
        with patch.object(
            build_upstream_runtime,
            "apply_prebuilt_overrides",
            return_value=1,
        ) as apply_overrides:
            build_upstream_runtime.stage_runtime_overrides(
                "v0.16.0",
                "android",
                "arm64",
            )

        apply_overrides.assert_called_once_with(
            "v0.16.0",
            platform="android",
            arch="arm64",
        )


if __name__ == "__main__":
    unittest.main()
