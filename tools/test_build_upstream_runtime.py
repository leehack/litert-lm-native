from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import subprocess
import tempfile
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import DEFAULT, MagicMock, patch

import build_upstream_runtime
import package_upstream_prebuilts
from bazel_repository_provenance import HTTP_ARCHIVE, UPSTREAM_REGISTRY
from litert_cpu_options_identifier_patch import (
    LITERT_ARCHIVE_SHA256 as CPU_OPTIONS_SHA256,
    LITERT_REF as CPU_OPTIONS_REF,
)
from litert_lm_symbols import ANDROID_OPENCL_SAMPLER_SYMBOLS, ANDROID_WEBGPU_SAMPLER_SYMBOLS
from litert_stage_spatial_tensors_patch import (
    LITERT_ARCHIVE_SHA256,
    LITERT_REF,
    PATCH_PATH as STAGING_PATCH,
)
from test_runtime_dependency_utils import write_elf_with_exports
from xnnpack_pf32_sme2_patch import (
    TENSORFLOW_ARCHIVE,
    V019_TENSORFLOW_REF,
    V019_XNNPACK_COMMIT,
    V019_XNNPACK_SHA256,
    V020_TENSORFLOW_REF,
    declare_patched_xnnpack,
)


def litert_workspace(ref: str, digest: str) -> str:
    return (
        f'LITERT_REF = "{ref}"\n'
        f'LITERT_SHA256 = "{digest}"\n'
        'http_archive(\n'
        '    name = "litert",\n'
        '    sha256 = LITERT_SHA256,\n'
        '    strip_prefix = "LiteRT-" + LITERT_REF,\n'
        '    url = "https://github.com/google-ai-edge/LiteRT/archive/" + LITERT_REF + ".tar.gz",\n'
        ')\n'
    )


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

    def test_desktop_build_selects_shared_runtime_only_for_v016_to_v018(self) -> None:
        for platform, arch in build_upstream_runtime.RUNTIME_TARGETS:
            for tag in ("v0.15.0", "v0.16.0", "v0.17.0", "v0.17.1", "v0.18.1", "v0.19.0", "v0.19.1"):
                with self.subTest(platform=platform, arch=arch, tag=tag), tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    gate = root / "runtime/conversation/model_data_processor/BUILD"
                    gate.parent.mkdir(parents=True)
                    gate.write_bytes((Path(__file__).parent / "fixtures/ios_fst_gate.BUILD").read_bytes())
                    with patch.object(build_upstream_runtime, "materialize_git_lfs_libraries", return_value=0), \
                         patch.object(build_upstream_runtime, "patch_upstream_ios_sampler_path"), \
                         patch.object(build_upstream_runtime, "patch_asr_untimed_overlap"), \
                         patch.object(build_upstream_runtime, "patch_asr_litertlm_container"), \
                         patch.object(build_upstream_runtime, "patch_stream_finish_reason"), \
                         patch.object(build_upstream_runtime, "patch_huggingface_token_bytes"), \
                         patch.object(build_upstream_runtime, "patch_step_zero_state") as apply_state, \
                         patch.object(build_upstream_runtime, "verify_carried_dependency_pins"), \
                         patch.object(build_upstream_runtime, "fetch_audited_archives"), \
                         patch.object(build_upstream_runtime, "apply_android_gpu_safety"), \
                         patch.object(build_upstream_runtime, "verify_dynamic_runtime"), \
                         patch.object(build_upstream_runtime, "bazel_command", return_value=["bazel"]), \
                         patch.object(build_upstream_runtime, "run", side_effect=RuntimeError("captured build")) as run:
                        with self.assertRaisesRegex(RuntimeError, "captured build"):
                            build_upstream_runtime.build_runtime(root, platform, arch, tag, "3")
                    apply_state.assert_called_once_with(root, tag)
                    command = run.call_args.args[0]
                    self.assertEqual("--define=LITERT_LM_FST_CONSTRAINTS_DISABLED=1" in command, platform == "ios" and tag not in {"v0.15.0", "v0.16.0"})
                    dynamic = platform in {"linux", "windows"} and tag not in {"v0.15.0", "v0.19.0", "v0.19.1"}
                    self.assertEqual("--define=litert_runtime_link_mode=dynamic" in command, dynamic)
                    self.assertEqual("--define=litert_link_capi_so=true" in command, not dynamic)
                    self.assertEqual("--define=litert_lm_in_process_litert=true" in command,
                                     tag in {"v0.19.0", "v0.19.1"})
                    self.assertIn("--define=resolve_symbols_in_exec=false", command)
                    self.assertIn("--nohome_rc", command)
                    self.assertIn("--nosystem_rc", command)
                    self.assertEqual("--noenable_bzlmod" in command,
                                     tag in {"v0.18.1", "v0.19.0", "v0.19.1"})
                    self.assertEqual("--define=litert_lm_android_webgpu_sampler=true" in command,
                                     platform == "android" and tag in {"v0.19.0", "v0.19.1"})

    def test_android_webgpu_sampler_define_links_the_static_sampler(self) -> None:
        bazel = (build_upstream_runtime.REPO_ROOT / "native/bridge/BUILD.bazel").read_text()
        setting = re.search(
            r'name = "android_webgpu_sampler",\s*constraint_values = \["@platforms//os:android"\],'
            r'\s*define_values = \{"([^"]+)": "true"\}', bazel)
        self.assertIsNotNone(setting)
        script = Path(build_upstream_runtime.__file__).read_text()
        self.assertIn(f'"--define={setting.group(1)}=true"', script)
        self.assertEqual(len(re.findall(
            r'":android_webgpu_sampler": \["//runtime/components:top_k_webgpu_sampler_static"\]',
            bazel)), 1)

    def test_android_v019_build_rejects_a_runtime_without_both_gpu_samplers(self) -> None:
        both = ANDROID_OPENCL_SAMPLER_SYMBOLS + ANDROID_WEBGPU_SAMPLER_SYMBOLS
        published = ANDROID_OPENCL_SAMPLER_SYMBOLS + [
            f"{symbol}_Static" for symbol in ANDROID_WEBGPU_SAMPLER_SYMBOLS]
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "libLiteRtLm.so"
            write_elf_with_exports(output, published)
            with self.assertRaisesRegex(RuntimeError, r"LiteRtTopKWebGpuSampler_Create,.*#120"):
                build_upstream_runtime.validate_android_gpu_samplers(output, "android", "v0.19.1")
            build_upstream_runtime.validate_android_gpu_samplers(output, "android", "v0.18.1")
            build_upstream_runtime.validate_android_gpu_samplers(output, "linux", "v0.19.1")
            write_elf_with_exports(output, both)
            build_upstream_runtime.validate_android_gpu_samplers(output, "android", "v0.19.1")
            with patch.object(build_upstream_runtime, "validate_exported_symbols"), \
                 patch.object(build_upstream_runtime, "validate_in_process_litert_linkage"), \
                 patch.object(build_upstream_runtime, "validate_android_global_visibility"), \
                 patch.object(build_upstream_runtime, "validate_android_protobuf_isolation"), \
                 patch.object(build_upstream_runtime, "validate_android_gpu_environment_teardown"):
                build_upstream_runtime.validate_runtime(output, "android", "v0.19.1")
                write_elf_with_exports(output, published)
                with self.assertRaisesRegex(RuntimeError, "#120"):
                    build_upstream_runtime.validate_runtime(output, "android", "v0.19.1")

    def test_in_process_litert_define_matches_bazel_config_setting(self) -> None:
        bazel = (build_upstream_runtime.REPO_ROOT / "native/bridge/BUILD.bazel").read_text()
        setting = re.search(
            r'name = "in_process_litert",\s*define_values = \{"([^"]+)": "true"\}', bazel)
        self.assertIsNotNone(setting)
        script = Path(build_upstream_runtime.__file__).read_text()
        self.assertIn(f'"--define={setting.group(1)}=true"', script)

    def test_v019_runtime_must_not_import_shared_litert(self) -> None:
        cases = (("linux", ["libLiteRt.so", "libc.so.6"], ["libwebgpu_dawn.so", "libc.so.6"]),
                 ("android", ["libLiteRt.so", "libc.so"], ["libwebgpu_dawn.so", "libc.so"]),
                 ("windows", {"libLiteRt.dll": frozenset()}, {"KERNEL32.dll": frozenset()}),
                 ("macos", ["@rpath/libLiteRtLm.dylib", "@rpath/libLiteRt.dylib"],
                  ["@rpath/libLiteRtLm.dylib", "@rpath/libwebgpu_dawn.dylib"]),
                 ("ios", ["@rpath/LiteRtLm.framework/LiteRtLm", "@rpath/LiteRt.framework/LiteRt"],
                  ["@rpath/LiteRtLm.framework/LiteRtLm", "/usr/lib/libc++.1.dylib"]))
        for platform, shared, static in cases:
            with self.subTest(platform=platform):
                output = Path("host")
                with self._imports(shared):
                    with self.assertRaisesRegex(RuntimeError, "#111"):
                        build_upstream_runtime.validate_in_process_litert_linkage(output, platform, "v0.19.1")
                    build_upstream_runtime.validate_in_process_litert_linkage(output, platform, "v0.18.1")
                with self._imports(static):
                    build_upstream_runtime.validate_in_process_litert_linkage(output, platform, "v0.19.1")

    def test_main_rejects_shared_litert_on_both_build_paths(self) -> None:
        for source_root in (True, False):
            with self.subTest(source_root=source_root), tempfile.TemporaryDirectory() as temp:
                argv = ["build_upstream_runtime.py", "--upstream-tag", "v0.19.1",
                        "--platform", "linux", "--arch", "x64"]
                if source_root:
                    argv += ["--source-root", temp]
                with patch("sys.argv", argv), \
                     patch.object(build_upstream_runtime, "download_upstream", return_value=Path(temp)), \
                     patch.object(build_upstream_runtime, "build_runtime", return_value=Path(temp) / "libLiteRtLm.so"), \
                     patch.object(build_upstream_runtime, "validate_exported_symbols"), \
                     patch.object(build_upstream_runtime, "stage_runtime") as stage, \
                     self._imports(["libLiteRt.so"]):
                    with self.assertRaisesRegex(RuntimeError, "#111"):
                        build_upstream_runtime.main()
                stage.assert_not_called()

    def _imports(self, imported):
        stack = ExitStack()
        stack.enter_context(patch.object(build_upstream_runtime, "elf_needed_libraries", return_value=imported))
        stack.enter_context(patch.object(build_upstream_runtime, "macho_needed_libraries", return_value=imported))
        stack.enter_context(patch.object(build_upstream_runtime.windows_runtime, "read_pe",
                                         return_value=SimpleNamespace(all_imports=lambda: imported)))
        return stack

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

    def test_workspace_applies_spatial_staging_only_to_the_audited_pin(self) -> None:
        original = litert_workspace(LITERT_REF, LITERT_ARCHIVE_SHA256) + (
            f'http_archive(\n    name = "minizip",\n    url = "{build_upstream_runtime.ZLIB_URL}",\n)\n'
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "WORKSPACE"
            workspace.write_text(original, encoding="utf-8")
            build_upstream_runtime.patch_upstream_workspace(root, patch_stage_spatial_tensors=True)
            build_upstream_runtime.patch_upstream_workspace(root, patch_stage_spatial_tensors=True)
            marker = f'"@//bridge:{Path(STAGING_PATCH).name}"'
            self.assertEqual(workspace.read_text(encoding="utf-8").count(marker), 1)

            for pin, digest in (("LITERT_REF", LITERT_REF),
                                ("LITERT_SHA256", LITERT_ARCHIVE_SHA256)):
                with self.subTest(pin=pin):
                    drift = original.replace(digest, "0" * len(digest))
                    workspace.write_text(drift, encoding="utf-8")
                    with self.assertRaisesRegex(RuntimeError, f"Unexpected {pin}"):
                        build_upstream_runtime.patch_upstream_workspace(
                            root, patch_stage_spatial_tensors=True,
                        )
                    self.assertEqual(workspace.read_text(encoding="utf-8"), drift)

    def test_windows_v020_uses_the_android_rules_and_engine_fd_patches(self) -> None:
        call = "tf_workspace2()\n"
        original = (
            f'TENSORFLOW_REF = "{V020_TENSORFLOW_REF}"\n'
            'load("@org_tensorflow//tensorflow:workspace2.bzl", "tf_workspace2")\n\n'
            + call
        )
        with tempfile.TemporaryDirectory() as temp, patch.multiple(
            build_upstream_runtime,
            verify_carried_dependency_pins=DEFAULT,
            patch_asr_untimed_overlap=DEFAULT,
            patch_stream_finish_reason=DEFAULT,
            patch_huggingface_token_bytes=DEFAULT,
            patch_step_zero_state=DEFAULT,
            apply_android_gpu_safety=DEFAULT,
            patch_windows_engine_fd=DEFAULT,
            materialize_git_lfs_libraries=DEFAULT,
            bazel_command=DEFAULT,
            prepare_bridge_package=DEFAULT,
            fetch_audited_archives=DEFAULT,
            run=DEFAULT,
        ) as calls:
            root = Path(temp)
            workspace = root / "WORKSPACE"
            fd_patch = calls["patch_windows_engine_fd"]
            calls["bazel_command"].return_value = ["bazel"]
            calls["materialize_git_lfs_libraries"].return_value = 0
            calls["prepare_bridge_package"].return_value = []
            calls["run"].side_effect = RuntimeError("Bazel reached")
            for platform, tag in (("windows", "v0.20.0"), ("linux", "v0.20.0"),
                                  ("windows", "v0.19.1")):
                with self.subTest(platform=platform, tag=tag):
                    workspace.write_text(original, encoding="utf-8")
                    fd_patch.reset_mock()
                    for _ in range(2):
                        with self.assertRaisesRegex(RuntimeError, "Bazel reached"):
                            build_upstream_runtime.build_runtime(root, platform, "x64", tag, None)
                    text = workspace.read_text(encoding="utf-8")
                    if (platform, tag) == ("windows", "v0.20.0"):
                        self.assertEqual([call.args for call in fd_patch.call_args_list],
                                         [(root, tag), (root, tag)])
                        name = 'name = "build_bazel_rules_android"'
                        self.assertEqual(text.count(name), 1)
                        self.assertLess(text.index(name), text.index(call))
                        self.assertIn('patch_args = ["-p1"]', text)
                        self.assertIn('patches = ["@//bridge:rules_android_tensorflow_v020.patch"]', text)
                        self.assertIn('sha256 = "af84b69ab3d16dd1a41056286e6511f147a94ccea995603e13e934c915c1631c"', text)
                        self.assertNotIn("patch_cmds", text)
                    else:
                        fd_patch.assert_not_called()
                        self.assertEqual(text, original)

    def test_source_root_verifies_resolved_archives_before_compilation(self) -> None:
        workspace = litert_workspace(LITERT_REF, LITERT_ARCHIVE_SHA256) + declare_patched_xnnpack(
            f'TENSORFLOW_REF = "{V019_TENSORFLOW_REF}"\n' + TENSORFLOW_ARCHIVE + ")\n"
        )

        tree_hash = (
            "c9120d92534177495742ddadfe47ad41e013b170cf24f283cbc37993caed5dcc"
            if os.name == "nt" else
            "3489273db3277fb16b56b64c093c6bebb8344a98838149fe93b71ebc41caccb9"
        )

        def resolved_archive(name: str, digest: str, prefix: str,
                             reported_tree_hash: str = tree_hash) -> dict:
            return {
                "original_rule_class": HTTP_ARCHIVE,
                "original_attributes": {"name": name},
                "repositories": [{
                    "rule_class": HTTP_ARCHIVE,
                    "output_tree_hash": reported_tree_hash,
                    "attributes": {"name": name, "sha256": digest, "strip_prefix": prefix},
                }],
            }

        litert = resolved_archive("litert", LITERT_ARCHIVE_SHA256, f"LiteRT-{LITERT_REF}")
        xnnpack = resolved_archive("XNNPACK", V019_XNNPACK_SHA256, f"XNNPACK-{V019_XNNPACK_COMMIT}")
        wrong = resolved_archive("litert", "0" * 64, f"LiteRT-{LITERT_REF}")
        wrong_tree = resolved_archive("litert", LITERT_ARCHIVE_SHA256, f"LiteRT-{LITERT_REF}", "f" * 64)
        local = {**litert, "original_rule_class": "local_repository"}
        archive_cases = (
            ("pinned", [litert, xnnpack], "compilation reached"),
            ("override", [xnnpack], "Bazel did not resolve @litert from its pinned archive"),
            ("digest mismatch", [wrong, xnnpack], "Bazel resolved @litert from an unexpected archive"),
            ("tree hash mismatch", [wrong_tree, xnnpack], "Bazel output tree hash mismatch for @litert"),
            ("changed tree", [litert, xnnpack], "Bazel output tree hash mismatch for @XNNPACK"),
            ("missing tree", [litert, xnnpack], "Could not hash Bazel output tree for @XNNPACK"),
            ("wrong rule", [local, xnnpack], "Bazel resolved @litert from an unexpected archive"),
            ("missing XNNPACK", [litert], "Bazel did not resolve @XNNPACK from its pinned archive"),
        )
        link_cases = {
            "dangling absolute link": None,
            "absolute link stat failure": ("stat", errno.EIO),
            "absolute link open failure": ("open", errno.EACCES),
            "absolute link disappeared after stat": ("open", errno.ENOENT),
            "absolute link read failure": ("read", errno.EIO),
            "Windows absolute link loop": ("stat", errno.EINVAL, 1921),
        }
        link_archive_cases = [(label, [], "compilation reached") for label in link_cases]
        for label, records, message in (*archive_cases, *link_archive_cases):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp, patch.multiple(
                build_upstream_runtime,
                patch_asr_untimed_overlap=DEFAULT,
                patch_stream_finish_reason=DEFAULT,
                patch_huggingface_token_bytes=DEFAULT,
                patch_step_zero_state=DEFAULT,
                apply_android_gpu_safety=DEFAULT,
                materialize_git_lfs_libraries=DEFAULT,
                run=DEFAULT,
            ) as calls, ExitStack() as faults:
                root = Path(temp)
                output_base = root / "bazel output"
                target = root / "referent"
                fault = link_cases.get(label)
                if label in link_cases:
                    if fault:
                        target.write_bytes(b"referent contents\n")
                    target_text = target.as_posix() if os.name == "nt" else os.fsencode(target).decode("latin-1")
                    # A link-only report would let an incorrectly suppressed fault reach compilation.
                    child_hash = hashlib.sha256(f"source.txtl{target_text}".encode("utf-16-le")).hexdigest()
                    link_hash = hashlib.sha256(f"coded{child_hash}".encode("utf-16-le")).hexdigest()
                    records = [
                        resolved_archive("litert", LITERT_ARCHIVE_SHA256, f"LiteRT-{LITERT_REF}", link_hash),
                        xnnpack,
                    ]
                for name in ("litert", "XNNPACK"):
                    if label == "missing tree" and name == "XNNPACK":
                        continue
                    directory = output_base / "external" / name / "code"
                    directory.mkdir(parents=True)
                    source = directory / "source.txt"
                    if label in link_cases and name == "litert":
                        source.symlink_to(target)
                        continue
                    contents = b"changed\n" if label == "changed tree" and name == "XNNPACK" else b"archive contents\n"
                    source.write_bytes(contents)
                    source.chmod(0o644)
                if fault:
                    operation, error_number, *windows_error = fault
                    if not windows_error:
                        message = rf"Could not hash Bazel output tree for @litert: \[Errno {error_number}\]"
                    real_stat, real_open = Path.stat, Path.open

                    def stat_path(path, *args, **kwargs):
                        if path == target:
                            error = OSError(error_number, os.strerror(error_number), str(path))
                            if windows_error:
                                error.winerror = windows_error[0]
                            raise error
                        return real_stat(path, *args, **kwargs)

                    def open_path(path, *args, **kwargs):
                        if path != target:
                            return real_open(path, *args, **kwargs)
                        if operation == "open":
                            raise OSError(error_number, os.strerror(error_number), str(path))
                        stream = MagicMock()
                        stream.__enter__.return_value.read.side_effect = OSError(
                            error_number, os.strerror(error_number),
                        )
                        return stream

                    if operation == "stat":
                        faults.enter_context(patch.object(Path, "stat", autospec=True, side_effect=stat_path))
                    else:
                        faults.enter_context(patch.object(Path, "open", autospec=True, side_effect=open_path))
                (root / "WORKSPACE").write_text(workspace, encoding="utf-8")
                (root / ".bazelrc").write_text(
                    f"common {UPSTREAM_REGISTRY}\n"
                    "try-import %workspace%/.bazelrc.user\n"
                    "build:macos --cxxopt=-std=c++20\n"
                    "build --repo_env=HERMETIC_PYTHON_VERSION=3.13\n",
                    encoding="utf-8",
                )
                (root / ".bazelrc.user").write_text(
                    "common --override_repository=litert=alternate_repo\n", encoding="utf-8",
                )
                calls["materialize_git_lfs_libraries"].return_value = 0

                def run(command, cwd, *, capture_output=False):
                    self.assertEqual(cwd, root.resolve())
                    self.assertIn("--nohome_rc", command)
                    self.assertIn("--nosystem_rc", command)
                    self.assertIn("--noworkspace_rc", command)
                    self.assertIn("--noenable_bzlmod", command)
                    cfg = next(arg.split("=", 1)[1] for arg in command if arg.startswith("--bazelrc="))
                    rc = Path(cfg).read_text(encoding="utf-8")
                    self.assertIn("build:macos --cxxopt=-std=c++20", rc)
                    self.assertIn("sync --repo_env=HERMETIC_PYTHON_VERSION=3.13", rc)
                    self.assertNotIn("--registry", rc)
                    self.assertNotIn(".bazelrc.user", rc)
                    if "build" in command:
                        raise RuntimeError("compilation reached")
                    if "info" in command:
                        self.assertTrue(capture_output)
                        self.assertEqual(command[-1], "output_base")
                        return subprocess.CompletedProcess(command, 0, stdout=f"{output_base}\n")
                    self.assertIn("sync", command)
                    self.assertIn("--only=litert", command)
                    self.assertIn("--only=XNNPACK", command)
                    resolved = next(
                        arg.split("=", 1)[1] for arg in command
                        if arg.startswith("--experimental_repository_resolved_file=")
                    )
                    report = json.dumps(records, indent=5)
                    # Bazel emits internal Starlark objects for unrelated rules.
                    report = report[:-2] + ',\n     {"unrelated": <unknown object>}\n]'
                    Path(resolved).write_text("resolved = " + report + "\n", encoding="utf-8")

                calls["run"].side_effect = run
                args = ["build_upstream_runtime.py", "--source-root", str(root),
                        "--upstream-tag", "v0.19.1", "--platform", "macos", "--arch", "arm64"]
                with patch("sys.argv", args), self.assertRaisesRegex(RuntimeError, message) as failure:
                    build_upstream_runtime.main()
                compilations = [call for call in calls["run"].call_args_list if "build" in call.args[0]]
                self.assertEqual(len(compilations), int(message == "compilation reached"))
                if fault and not windows_error:
                    self.assertIn(repr(str(target)), str(failure.exception))
                    cause = failure.exception.__cause__
                    self.assertIsInstance(cause, OSError)
                    self.assertEqual(cause.errno, error_number)
                    self.assertEqual(cause.filename, str(target))

    def test_source_root_rejects_workspace_rc_repository_overrides_before_bazel(self) -> None:
        workspace = litert_workspace(LITERT_REF, LITERT_ARCHIVE_SHA256) + declare_patched_xnnpack(
            f'TENSORFLOW_REF = "{V019_TENSORFLOW_REF}"\n' + TENSORFLOW_ARCHIVE + ")\n"
        )
        fixtures = (
            ("build --override_repository=litert=alternate_repo", "override_repository"),
            ("build:macos --override_repository XNNPACK=alternate_repo", "override_repository"),
            ("common --registry=https://example.invalid/registry", "registry"),
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "WORKSPACE").write_text(workspace, encoding="utf-8")
            args = ["build_upstream_runtime.py", "--source-root", str(root),
                    "--upstream-tag", "v0.19.1", "--platform", "macos", "--arch", "arm64"]
            for fixture, option in fixtures:
                with self.subTest(fixture=fixture), patch("sys.argv", args), patch.multiple(
                    build_upstream_runtime,
                    patch_asr_untimed_overlap=DEFAULT,
                    patch_stream_finish_reason=DEFAULT,
                    patch_huggingface_token_bytes=DEFAULT,
                    patch_step_zero_state=DEFAULT,
                    apply_android_gpu_safety=DEFAULT,
                    materialize_git_lfs_libraries=DEFAULT,
                    run=DEFAULT,
                ) as calls:
                    calls["materialize_git_lfs_libraries"].return_value = 0
                    calls["run"].side_effect = RuntimeError("Bazel reached")
                    (root / ".bazelrc").write_text(fixture + "\n", encoding="utf-8")
                    with self.assertRaisesRegex(RuntimeError, rf"Unexpected Bazel rc option --{option}"):
                        build_upstream_runtime.main()
                    calls["run"].assert_not_called()

    def test_build_routes_reject_identical_workspace_files_before_patching(self) -> None:
        workspace = litert_workspace(LITERT_REF, LITERT_ARCHIVE_SHA256) + declare_patched_xnnpack(
            f'TENSORFLOW_REF = "{V019_TENSORFLOW_REF}"\n' + TENSORFLOW_ARCHIVE + ")\n"
        )
        with tempfile.TemporaryDirectory() as temp:
            work_dir = Path(temp)
            root = work_dir / "source"
            root.mkdir()
            for name in ("WORKSPACE", "WORKSPACE.bazel"):
                (root / name).write_text(workspace, encoding="utf-8")
            message = "both WORKSPACE and WORKSPACE.bazel"

            args = ["build_upstream_runtime.py", "--source-root", str(root),
                    "--upstream-tag", "v0.19.1", "--platform", "macos", "--arch", "arm64"]
            with self.subTest(route="prepared"), patch("sys.argv", args), patch.object(
                build_upstream_runtime, "patch_asr_untimed_overlap",
                side_effect=RuntimeError("reached source patching"),
            ) as patch_source, patch.object(build_upstream_runtime, "run") as run:
                with self.assertRaisesRegex(RuntimeError, message):
                    build_upstream_runtime.main()
                patch_source.assert_not_called()
                run.assert_not_called()

            with self.subTest(route="archive"), patch.object(
                build_upstream_runtime, "download_to_path",
            ), patch.object(build_upstream_runtime.tarfile, "open"), patch.object(
                build_upstream_runtime, "patch_workspace_build",
                side_effect=RuntimeError("reached workspace patching"),
            ) as patch_workspace:
                with self.assertRaisesRegex(RuntimeError, message):
                    build_upstream_runtime.download_upstream("v0.19.1", "v0.19.1", work_dir)
                patch_workspace.assert_not_called()

            with self.subTest(route="verifier"), self.assertRaisesRegex(RuntimeError, message):
                build_upstream_runtime.verify_carried_dependency_pins(
                    root, "v0.19.1", spatial_staging=True, cpu_options=False, xnnpack=True,
                )

            for name in ("WORKSPACE", "WORKSPACE.bazel"):
                self.assertEqual((root / name).read_text(encoding="utf-8"), workspace)

    def test_source_root_rejects_dependency_archive_drift_before_bazel(self) -> None:
        parent_ref = "d0ef0ad58bd87565a92000feef5be758505af84f"
        parent_sha = "778916714cd43383f2204bc2f5114e18a25035b3f84b157776898e788bb2d49f"
        litert = litert_workspace(LITERT_REF, LITERT_ARCHIVE_SHA256).replace(
            '    name = "litert",\n',
            f'    name = "litert",\n    patches = ["@//bridge:{Path(STAGING_PATCH).name}"],\n',
        )
        xnnpack = declare_patched_xnnpack(
            f'TENSORFLOW_REF = "{V019_TENSORFLOW_REF}"\n' + TENSORFLOW_ARCHIVE + ")\n"
        )
        cases = (
            ("alternate LiteRT archive", "v0.19.1", litert.replace(LITERT_REF, parent_ref)
             .replace(LITERT_ARCHIVE_SHA256, parent_sha) + xnnpack, "Unexpected LITERT_REF"),
            ("changed LiteRT digest", "v0.19.1",
             litert.replace(LITERT_ARCHIVE_SHA256, parent_sha) + xnnpack, "Unexpected LITERT_SHA256"),
            ("archive overrides digest", "v0.19.1",
             litert.replace("sha256 = LITERT_SHA256,", f'sha256 = "{parent_sha}",') + xnnpack,
             "Unexpected LiteRT archive sha256"),
            ("shadowed LiteRT revision", "v0.19.1",
             f'LITERT_REF="{parent_ref}"\n' + litert + xnnpack, "Unexpected LITERT_REF"),
            ("CPU options LiteRT pin drift", "v0.18.1",
             litert_workspace(CPU_OPTIONS_REF, CPU_OPTIONS_SHA256).replace(CPU_OPTIONS_REF, LITERT_REF),
             "Unexpected LITERT_REF for LiteRT CPU options"),
            ("XNNPACK digest drift", "v0.19.1",
             litert + xnnpack.replace(V019_XNNPACK_SHA256, "0" * 64), "Unexpected XNNPACK archive"),
            ("XNNPACK archive missing", "v0.19.0", litert, "Unexpected XNNPACK archive"),
        )
        for label, tag, workspace, message in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp, patch.multiple(
                build_upstream_runtime,
                patch_asr_untimed_overlap=DEFAULT,
                patch_asr_litertlm_container=DEFAULT,
                patch_stream_finish_reason=DEFAULT,
                patch_huggingface_token_bytes=DEFAULT,
                patch_step_zero_state=DEFAULT,
                apply_android_gpu_safety=DEFAULT,
                materialize_git_lfs_libraries=DEFAULT,
                run=DEFAULT,
            ) as calls:
                root = Path(temp)
                args = ["build_upstream_runtime.py", "--source-root", str(root),
                        "--upstream-tag", tag, "--platform", "macos", "--arch", "arm64"]
                calls["materialize_git_lfs_libraries"].return_value = 0
                calls["run"].side_effect = RuntimeError("Bazel reached")
                (root / "WORKSPACE").write_text(workspace, encoding="utf-8")
                with patch("sys.argv", args), self.assertRaisesRegex(RuntimeError, message):
                    build_upstream_runtime.main()
                calls["run"].assert_not_called()
                calls["patch_step_zero_state"].assert_not_called()

    def test_spatial_staging_postimages_fail_on_drift_or_missing_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output_base = Path(temp) / "output_base"
            source_root = Path(temp) / "source"
            exec_root = output_base / "execroot" / "litert_lm"
            (exec_root / "bazel-out").mkdir(parents=True)
            source_root.mkdir()
            (source_root / "bazel-out").symlink_to(exec_root / "bazel-out", target_is_directory=True)
            sources = {}
            files = []
            for name in build_upstream_runtime.stage_spatial_tensors_identity("v0.19.1")[3]:
                postimage = name.encode() + b"\n"
                sources[name] = ("", build_upstream_runtime.source_sha256(postimage))
                file = output_base / "external" / "litert" / name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(postimage.replace(b"\n", b"\r\n"))
                files.append(file)

            with patch.object(build_upstream_runtime, "stage_spatial_tensors_identity",
                              return_value=("", "", "", sources)):
                build_upstream_runtime.verify_stage_spatial_tensors_postimages(source_root)
                for file in files:
                    with self.subTest(file=file.name):
                        original = file.read_bytes()
                        file.write_bytes(b"wrong postimage")
                        with self.assertRaisesRegex(RuntimeError, f"postimage mismatch for .*{file.name}"):
                            build_upstream_runtime.verify_stage_spatial_tensors_postimages(source_root)
                        file.unlink()
                        with self.assertRaisesRegex(RuntimeError, f"postimage mismatch for .*{file.name}"):
                            build_upstream_runtime.verify_stage_spatial_tensors_postimages(source_root)
                        file.write_bytes(original)

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

    def test_v018_workspace_keeps_tokenizer_and_ios_fixes_without_teardown_patch(self) -> None:
        excerpt = (Path(__file__).parent / "fixtures/litert_lm_v0.18.0_workspace_excerpt.txt").read_text()
        needs = build_upstream_runtime.needs_gpu_environment_teardown_patch(excerpt, "v0.18.0")
        self.assertFalse(needs)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "WORKSPACE").write_text(excerpt)
            build_upstream_runtime.patch_upstream_workspace(
                root, patch_bpe_null_piece=True, patch_gpu_environment_teardown=needs)
            patched = (root / "WORKSPACE").read_text()
        self.assertIn('patches = ["@//bridge:litert_ios_framework_paths.patch"]', patched)
        self.assertIn('patches = ["@//bridge:sentencepiece_bpe_null.patch"]', patched)
        self.assertNotIn('litert_gpu_environment_destroy_callback.patch', patched)
        self.assertIn('LITERT_REF = "26895c9fbcc25c43faa8c1a98cd1fd28951602c3"', patched)

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
