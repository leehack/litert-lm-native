from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import build_upstream_runtime
import package_upstream_prebuilts


class BuildUpstreamRuntimeTest(unittest.TestCase):
    def test_ios_framework_patch_applies_to_old_and_current_litert(self) -> None:
        patch_file = (
            build_upstream_runtime.REPO_ROOT
            / "native/bridge/litert_ios_framework_paths.patch"
        )
        for version in ("17", "18"):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                target = root / "litert/runtime/accelerators/gpu_registry.cc"
                target.parent.mkdir(parents=True)
                original = (
                    Path(__file__).parent
                    / f"fixtures/litert_v0_{version}_gpu_registry_excerpt.cc"
                ).read_text()
                target.write_text(original)
                subprocess.run(
                    ["git", "apply", "--unidiff-zero", "--check", str(patch_file)],
                    cwd=root,
                    check=True,
                    capture_output=True,
                )
                subprocess.run(
                    ["git", "apply", "--unidiff-zero", str(patch_file)],
                    cwd=root,
                    check=True,
                    capture_output=True,
                )
                patched = target.read_text()
                self.assertIn(
                    '"@executable_path/Frameworks/LiteRtMetalAccelerator.framework/"',
                    patched,
                )
                self.assertNotIn('"libLiteRtMetalAccelerator" SO_EXT', patched)
                self.assertIn('"libLiteRtWebGpuAccelerator" SO_EXT', patched)
                if version == "18":
                    self.assertIn("// Inside an Apple framework bundle", patched)
                    self.assertEqual(patched.count('"LiteRtMetalAccelerator",'), 2)
                # Unknown iOS layouts must still fail instead of silently dropping the path fix.
                target.write_text(
                    original.replace("#elif TARGET_OS_IPHONE", "#elif CHANGED_PLATFORM")
                )
                result = subprocess.run(
                    ["git", "apply", "--unidiff-zero", "--check", str(patch_file)],
                    cwd=root,
                    capture_output=True,
                )
                self.assertNotEqual(result.returncode, 0)

    def test_sentencepiece_patch_delimits_each_file_for_bazel(self) -> None:
        lines = (Path(__file__).resolve().parents[1] / "native/bridge/sentencepiece_bpe_null.patch").read_text().splitlines()
        files = []
        for index, line in enumerate(lines):
            if line.startswith("--- a/"):
                name = line.removeprefix("--- a/")
                self.assertEqual(lines[index - 1], f"diff --git a/{name} b/{name}")
                files.append(name)
        self.assertEqual(set(files), {"src/bpe_model.cc", "src/model_interface.cc", "src/model_interface.h"})

    def test_download_wires_bpe_compatibility_only_for_v017_and_later(self) -> None:
        affected = 'LITERT_REF = "9fe5be45564c868408e6514c8aabb83e211a0911"\n'
        for tag, workspace, enabled in [("v0.16.0", "", False), ("v0.17.0", affected, True), ("v0.17.1", affected, True)]:
            with self.subTest(tag=tag), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                source = root / "source"
                source.mkdir()
                (source / "WORKSPACE").write_text(workspace, encoding="utf-8")
                with patch.object(build_upstream_runtime, "download_to_path"), \
                     patch.object(build_upstream_runtime.tarfile, "open"), \
                     patch.object(build_upstream_runtime, "patch_upstream_workspace") as apply:
                    self.assertEqual(build_upstream_runtime.download_upstream(tag, tag, root), source)
                self.assertEqual(apply.call_args.kwargs["patch_bpe_null_piece"], enabled)
                self.assertEqual(apply.call_args.kwargs["patch_gpu_environment_teardown"], enabled)

    def test_workspace_applies_bpe_patch_and_preserves_file_on_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "WORKSPACE"
            text = ('http_archive(\n    name = "minizip",\n'
                    f'    url = "{build_upstream_runtime.ZLIB_URL}",\n)\n'
                    'http_archive(\n    name = "sentencepiece",\n'
                    '    sha256 = "92381f713e094a15a1ccff1ac4a5315a4c4b82a99ac1332d6ac53c9dc8e1bcf1",\n'
                    '    strip_prefix = "sentencepiece-0.2.2",\n'
                    '    url = "https://github.com/google/sentencepiece/archive/refs/tags/v0.2.2.tar.gz",\n)')
            path.write_text(text)
            build_upstream_runtime.patch_upstream_workspace(root, patch_ios_framework_paths=False, patch_bpe_null_piece=True)
            self.assertIn('patches = ["@//bridge:sentencepiece_bpe_null.patch"]', path.read_text())
            invalid = text.replace('92381f', '000000')
            path.write_text(invalid)
            with self.assertRaisesRegex(RuntimeError, "source changed"):
                build_upstream_runtime.patch_upstream_workspace(root, patch_ios_framework_paths=False, patch_bpe_null_piece=True)
            self.assertEqual(path.read_text(), invalid)

    def test_sentencepiece_patch_is_exact_source_and_idempotent(self) -> None:
        block = ('http_archive(\n    name = "sentencepiece",\n'
                 '    sha256 = "92381f713e094a15a1ccff1ac4a5315a4c4b82a99ac1332d6ac53c9dc8e1bcf1",\n'
                 '    strip_prefix = "sentencepiece-0.2.2",\n'
                 '    url = "https://github.com/google/sentencepiece/archive/refs/tags/v0.2.2.tar.gz",\n)')
        patched = build_upstream_runtime.patch_sentencepiece_bpe_null(block)
        self.assertIn('patches = ["@//bridge:sentencepiece_bpe_null.patch"]', patched)
        self.assertEqual(build_upstream_runtime.patch_sentencepiece_bpe_null(patched), patched)
        for invalid in (block.replace('92381f', '000000'),
                        block.replace('0.2.2', '0.2.3'),
                        block + '\n' + block,
                        block.replace('    sha256', '    patches = ["other.patch"],\n    sha256')):
            with self.subTest(invalid=invalid), self.assertRaises(RuntimeError):
                build_upstream_runtime.patch_sentencepiece_bpe_null(invalid)

    def test_runtime_selects_capabilities_owner_by_upstream_version(self) -> None:
        for tag, expected in [("v0.16.0", False), ("v0.17.0", True), ("v0.17.1", True)]:
            with self.subTest(tag=tag), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                with patch.object(build_upstream_runtime, "materialize_git_lfs_libraries", return_value=0), \
                     patch.object(build_upstream_runtime, "bazel_command", return_value=["bazel"]), \
                     patch.object(build_upstream_runtime, "run", side_effect=RuntimeError("captured build")) as run:
                    with self.assertRaisesRegex(RuntimeError, "captured build"):
                        build_upstream_runtime.build_runtime(root, "macos", "arm64", tag, "3")
                command = run.call_args.args[0]
                self.assertEqual("--define=litert_lm_capabilities_in_c_engine=true" in command, expected)

    def test_desktop_gpu_build_selects_shared_runtime_without_legacy_define(self) -> None:
        for platform, arch in build_upstream_runtime.RUNTIME_TARGETS:
            for tag in ("v0.15.0", "v0.16.0", "v0.17.0", "v0.17.1"):
                with self.subTest(platform=platform, arch=arch, tag=tag), tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    gate = root / "runtime/conversation/model_data_processor/BUILD"
                    gate.parent.mkdir(parents=True)
                    gate.write_bytes((Path(__file__).parent / "fixtures/ios_fst_gate.BUILD").read_bytes())
                    with patch.object(build_upstream_runtime, "materialize_git_lfs_libraries", return_value=0), \
                         patch.object(build_upstream_runtime, "patch_upstream_ios_sampler_path"), \
                         patch.object(build_upstream_runtime, "bazel_command", return_value=["bazel"]), \
                         patch.object(build_upstream_runtime, "run", side_effect=RuntimeError("captured build")) as run:
                        with self.assertRaisesRegex(RuntimeError, "captured build"):
                            build_upstream_runtime.build_runtime(root, platform, arch, tag, "3")
                    command = run.call_args.args[0]
                    self.assertEqual("--define=LITERT_LM_FST_CONSTRAINTS_DISABLED=1" in command, platform == "ios" and tag in {"v0.17.0", "v0.17.1"})
                    dynamic = platform in {"linux", "windows"} and tag != "v0.15.0"
                    self.assertEqual("--define=litert_runtime_link_mode=dynamic" in command, dynamic)
                    self.assertEqual("--define=litert_link_capi_so=true" in command, not dynamic)
                    self.assertIn("--define=resolve_symbols_in_exec=false", command)

    def test_linux_stages_matching_prebuilt_core_even_over_stale_copy(self) -> None:
        for arch, target in (("x64", "linux_x86_64"), ("arm64", "linux_arm64")):
            with self.subTest(arch=arch), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                stage = root / "bin" / "linux" / arch
                stage.mkdir(parents=True)
                host = stage / "libLiteRtLm.so"
                host.write_bytes(b"\x7fELFhost")
                core = stage / "libLiteRt.so"
                core.write_bytes(b"stale source-built core")
                prebuilt = root / "source" / "prebuilt" / target / "libLiteRt.so"
                prebuilt.parent.mkdir(parents=True)
                prebuilt.write_bytes(b"\x7fELFmatching upstream core")
                with patch.object(build_upstream_runtime, "BIN_DIR", root / "bin"), \
                     patch.object(build_upstream_runtime, "elf_needed_libraries", side_effect=lambda p: ["libLiteRt.so"] if p.name == "libLiteRtLm.so" else []), \
                     patch.object(build_upstream_runtime, "find_runtime_dependency") as fallback:
                    build_upstream_runtime.stage_runtime_dependencies(host, root / "source", "linux", arch)
                    self.assertEqual(core.read_bytes(), b"\x7fELFmatching upstream core")
                    fallback.assert_not_called()
                    prebuilt.write_bytes(b"version https://git-lfs.github.com/spec/v1")
                    with self.assertRaisesRegex(RuntimeError, "Matching upstream Linux"):
                        build_upstream_runtime.stage_runtime_dependencies(host, root / "source", "linux", arch)
                    prebuilt.unlink()
                    with self.assertRaisesRegex(RuntimeError, "Matching upstream Linux"):
                        build_upstream_runtime.stage_runtime_dependencies(host, root / "source", "linux", arch)
                    fallback.assert_not_called()

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

    def test_workspace_adds_gpu_environment_teardown_patch_for_v017(self) -> None:
        needs = build_upstream_runtime.needs_gpu_environment_teardown_patch
        affected = 'LITERT_REF = "9fe5be45564c868408e6514c8aabb83e211a0911"\n'
        reordered = 'LITERT_REF = "86112a3263efdbcf2183c48580c9aa1b89850c98"\n'
        self.assertTrue(needs(affected, "v0.17.0"))
        self.assertTrue(needs(affected, "v0.17.1"))
        # A development build keeps the stable compatibility tag.
        self.assertFalse(needs(reordered, "v0.17.1"))
        for ref, tag in [
            ("3cb830ad9c94f9922f0a88dd431b005413628919", "v0.15.0"),
            ("0ff28117f1cb5556d0e015bf80b773f74e2bee51", "v0.16.1"),
            ("761d99cb90e20c67efcb3fe1119a60c92381bd1a", "v0.17.0"),
        ]:
            self.assertTrue(needs(f'LITERT_REF = "{ref}"\n', tag), ref)
        self.assertFalse(needs("", "v0.16.1"))
        with self.assertRaisesRegex(RuntimeError, "LITERT_REF"):
            needs("", "v0.17.0")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "WORKSPACE"
            workspace.write_text(
                f'http_archive(\n    name = "minizip",\n    url = "{build_upstream_runtime.ZLIB_URL}",\n)\n'
                'http_archive(\n    name = "litert",\n)\n',
                encoding="utf-8",
            )

            for _ in range(2):
                build_upstream_runtime.patch_upstream_workspace(
                    root, patch_gpu_environment_teardown=True)

            patched = workspace.read_text(encoding="utf-8")
            self.assertEqual(
                patched.count(
                    '    patches = ["@//bridge:litert_ios_framework_paths.patch", '
                    '"@//bridge:litert_gpu_environment_destroy_callback.patch"],\n'
                ),
                1,
            )
            with self.assertRaisesRegex(RuntimeError, "Unexpected LiteRT patches"):
                build_upstream_runtime.patch_upstream_workspace(root)

    def test_real_v017_workspace_selects_and_takes_the_teardown_patch(self) -> None:
        # An excerpt of the upstream v0.17.0 WORKSPACE: LITERT_REF is not on
        # its first line, and the litert archive has its own patch_cmds.
        excerpt = (
            Path(build_upstream_runtime.__file__).parent
            / "fixtures"
            / "litert_lm_v0.17.0_workspace_excerpt.txt"
        ).read_text(encoding="utf-8")
        self.assertTrue(
            build_upstream_runtime.needs_gpu_environment_teardown_patch(
                excerpt, "v0.17.0"
            )
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "WORKSPACE").write_text(excerpt, encoding="utf-8")
            build_upstream_runtime.patch_upstream_workspace(
                root, patch_bpe_null_piece=True, patch_gpu_environment_teardown=True
            )
            patched = (root / "WORKSPACE").read_text(encoding="utf-8")
        self.assertIn(
            'http_archive(\n    name = "litert",\n    patch_args = ["-p1"],\n'
            '    patches = ["@//bridge:litert_ios_framework_paths.patch", '
            '"@//bridge:litert_gpu_environment_destroy_callback.patch"],\n'
            "    patch_cmds = [\n",
            patched,
        )
        self.assertIn(
            'LITERT_REF = "9fe5be45564c868408e6514c8aabb83e211a0911"\n', patched
        )

    def test_gpu_environment_teardown_patch_records_callback_before_opencl(self) -> None:
        patch = (
            build_upstream_runtime.BRIDGE_PACKAGE_ROOT
            / "bridge"
            / "litert_gpu_environment_destroy_callback.patch"
        ).read_text(encoding="utf-8")
        added = patch.index("+  options_ = CreateGpuEnvironmentOptions(environment_options);")
        opencl = patch.index("LITERT_RETURN_IF_ERROR(tflite::gpu::cl::LoadOpenCL().ok())")
        removed = patch.index("-  options_ = CreateGpuEnvironmentOptions(environment_options);")
        self.assertLess(added, opencl)
        self.assertLess(opencl, removed)
        self.assertIn(
            '"litert_gpu_environment_destroy_callback.patch"',
            (build_upstream_runtime.BRIDGE_PACKAGE_ROOT / "bridge" / "BUILD.bazel").read_text(
                encoding="utf-8"
            ),
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

            with patch.object(build_upstream_runtime, "BIN_DIR", output), \
                 patch.object(build_upstream_runtime, "stage_windows_dxc"):
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

    def test_v017_source_build_stages_the_pinned_dawn_correction(self) -> None:
        with patch.object(
            package_upstream_prebuilts, "apply_prebuilt_override"
        ) as apply_override:
            build_upstream_runtime.stage_runtime_overrides("v0.17.0", "android", "arm64")
        apply_override.assert_called_once()
        selected = apply_override.call_args.args[0]
        self.assertEqual(selected.target_path, "bin/android/arm64/libwebgpu_dawn.so")
        self.assertEqual(selected.sha256, "7282aacdb076ce89f0c9d93107a145b991b99eb1dfbd5b5746dd0d99466ab3c3")

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
