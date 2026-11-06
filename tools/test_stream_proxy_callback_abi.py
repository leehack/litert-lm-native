from __future__ import annotations

from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

import build_upstream_runtime
from generate_schema2_contract_fixture import (
    NATIVE_COMMIT,
    RELEASE_TAG,
    UPSTREAM_COMMIT,
    UPSTREAM_TAG,
    generate_manifest,
)
import litert_lm_symbols
import package_ios_runtime
import package_macos_runtime
import package_release
from validate_release_manifest import validate_schema_2_payload


ROOT = Path(__file__).resolve().parents[1]
VERSIONS = (("v0.14.0", 1), ("v0.15.0", 2), ("v0.18.1", 2), ("v0.19.0", 2))


def source_getter_abi(stream_chunk: bool) -> int:
    """Read the independent C branches, without compiling or loading a library."""
    source = (ROOT / "native/bridge/litert_lm_bridge.c").read_text()
    getter = re.search(
        r"int32_t stream_proxy_callback_abi_version\(void\)\s*\{\s*"
        r"#if defined\(LITERT_LM_STREAM_CHUNK_API\)\s*return (\d+);\s*"
        r"#else\s*return (\d+);\s*#endif\s*\}",
        source,
    )
    if getter is None:
        raise AssertionError("Review callback getter source-mode mapping")
    return int(getter[1 if stream_chunk else 2])


def manifest_for(tag: str, *, development: bool = False) -> dict:
    with tempfile.TemporaryDirectory() as temp, ExitStack() as mocks:
        mocks.enter_context(patch.object(package_release, "iter_artifacts", return_value=[]))
        mocks.enter_context(patch.object(package_release, "validate_ios_directory"))
        mocks.enter_context(patch.object(package_release, "validate_ios_archives"))
        mocks.enter_context(patch.object(package_release, "SHA256SUMS_PATH", Path(temp) / "sums"))
        return package_release.build_manifest(
            upstream_tag=None if development else tag,
            upstream_commit=UPSTREAM_COMMIT,
            compatibility_tag=tag,
            release_tag=f"g{UPSTREAM_COMMIT[:12]}" if development else f"{tag}-1",
            native_commit=NATIVE_COMMIT,
            official_upstream_assets=not development,
        )


class StreamProxyCallbackAbiTest(unittest.TestCase):
    def test_generator_describes_modern_c_getter_not_legacy_constant(self) -> None:
        manifest = manifest_for("v0.15.0")
        self.assertEqual(manifest["abi"]["streamProxyCallback"], source_getter_abi(True))

    def test_validator_accepts_actual_modern_mode_and_rejects_wrong_metadata(self) -> None:
        manifest = generate_manifest()
        manifest["abi"]["streamProxyCallback"] = source_getter_abi(True)

        def validate(value: dict) -> None:
            validate_schema_2_payload(
                value,
                upstream_tag=UPSTREAM_TAG,
                upstream_commit=UPSTREAM_COMMIT,
                compatibility_tag=UPSTREAM_TAG,
                native_commit=NATIVE_COMMIT,
                release_tag=RELEASE_TAG,
            )

        validate(manifest)
        for wrong in (source_getter_abi(False), 0, 3, "2"):
            with self.subTest(wrong=wrong):
                changed = deepcopy(manifest)
                changed["abi"]["streamProxyCallback"] = wrong
                with self.assertRaisesRegex(SystemExit, "ABI declaration"):
                    validate(changed)
        changed = deepcopy(manifest)
        changed["capabilities"]["streamChunkAccessors"] = False
        with self.assertRaisesRegex(SystemExit, "capability declaration"):
            validate(changed)

    def test_version_boundary_and_development_compatibility_are_explicit(self) -> None:
        self.assertEqual(source_getter_abi(False), 1)
        self.assertEqual(source_getter_abi(True), 2)
        for tag, expected in VERSIONS:
            with self.subTest(tag=tag):
                self.assertEqual(litert_lm_symbols.stream_proxy_callback_abi_version(tag), expected)
                self.assertEqual(litert_lm_symbols.uses_stream_chunk_api(tag), expected == 2)
                for development in (False, True):
                    manifest = manifest_for(tag, development=development)
                    self.assertEqual(manifest["abi"]["streamProxyCallback"], expected)
                    self.assertEqual(manifest["capabilities"]["streamChunkAccessors"], expected == 2)
                    self.assertEqual(set(manifest["abi"]), {"upstreamC", "streamProxyCallback", "asrBridge"})
                    self.assertEqual(manifest["abi"]["asrBridge"], 1 if tag in {"v0.18.1", "v0.19.0"} else None)
                    arguments = dict(
                        upstream_tag=None if development else tag,
                        upstream_commit=UPSTREAM_COMMIT,
                        compatibility_tag=tag,
                        native_commit=NATIVE_COMMIT,
                        release_tag=manifest["release"]["tag"],
                    )
                    with self.assertRaisesRegex(SystemExit, "exactly .* platform bundles"):
                        validate_schema_2_payload(manifest, **arguments)
                    wrong = deepcopy(manifest)
                    wrong["abi"]["streamProxyCallback"] = 2 if expected == 1 else 1
                    with self.assertRaisesRegex(SystemExit, "ABI declaration"):
                        validate_schema_2_payload(wrong, **arguments)

    def test_legacy_candidate_rejects_modern_callback_metadata(self) -> None:
        manifest = manifest_for("v0.14.0")
        arguments = dict(
            upstream_tag="v0.14.0", upstream_commit=UPSTREAM_COMMIT,
            compatibility_tag="v0.14.0", native_commit=NATIVE_COMMIT,
            release_tag="v0.14.0-1",
        )
        # This focused metadata fixture deliberately has no platform payloads.
        # Correct ABI1 reaches the later inventory gate; ABI2 must fail earlier.
        with self.assertRaisesRegex(SystemExit, "exactly .* platform bundles"):
            validate_schema_2_payload(manifest, **arguments)
        manifest["abi"]["streamProxyCallback"] = 2
        with self.assertRaisesRegex(SystemExit, "ABI declaration"):
            validate_schema_2_payload(manifest, **arguments)

    def test_apple_compile_modes_agree_with_metadata_and_c_source(self) -> None:
        for tag, expected in VERSIONS:
            with self.subTest(tag=tag), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                with patch.object(package_macos_runtime, "run") as mac, patch.object(
                    package_macos_runtime, "validate_exported_symbols"
                ):
                    package_macos_runtime.build_wrapper(root / "upstream", root, ["arm64"], tag)
                with patch.object(package_ios_runtime, "run") as ios, patch.object(
                    package_ios_runtime, "validate_bridge_symbols"
                ):
                    package_ios_runtime.build_wrapper(
                        {"sdk": "iphoneos", "target_arch": "arm64"}, root, root / "upstream", tag
                    )
                for command in (mac.call_args.args[0], ios.call_args.args[0]):
                    mode = "-DLITERT_LM_STREAM_CHUNK_API=1" in command
                    self.assertEqual(mode, expected == 2)
                    self.assertEqual(source_getter_abi(mode), manifest_for(tag)["abi"]["streamProxyCallback"])

    def test_all_bazel_targets_select_the_metadata_callback_mode(self) -> None:
        source = (ROOT / "native/bridge/BUILD.bazel").read_text()
        self.assertIn('define_values = {"litert_lm_stream_chunk_api": "true"}', source)
        self.assertIn('\":stream_chunk_api\": [\"LITERT_LM_STREAM_CHUNK_API=1\"]', source)
        for platform, arch in build_upstream_runtime.RUNTIME_TARGETS:
            for tag, expected in (("v0.14.0", 1), ("v0.15.0", 2), ("v0.19.0", 2)):
                with self.subTest(platform=platform, arch=arch, tag=tag), tempfile.TemporaryDirectory() as temp, ExitStack() as mocks:
                    for name in (
                        "patch_asr_untimed_overlap", "patch_asr_litertlm_container",
                        "patch_stream_finish_reason", "patch_huggingface_token_bytes",
                        "apply_android_gpu_safety", "patch_upstream_ios_sampler_path",
                        "verify_upstream_fst_gate",
                    ):
                        mocks.enter_context(patch.object(build_upstream_runtime, name))
                    mocks.enter_context(patch.object(build_upstream_runtime, "materialize_git_lfs_libraries", return_value=0))
                    mocks.enter_context(patch.object(build_upstream_runtime, "require_cpu_options_identifier_patch_decision", return_value=False))
                    mocks.enter_context(patch.object(build_upstream_runtime, "require_finish_reason_patch_decision", return_value=False))
                    mocks.enter_context(patch.object(build_upstream_runtime, "prepare_bridge_package", return_value=[]))
                    mocks.enter_context(patch.object(build_upstream_runtime, "bazel_command", return_value=["bazel"]))
                    run = mocks.enter_context(patch.object(build_upstream_runtime, "run", side_effect=RuntimeError("captured build")))
                    with self.assertRaisesRegex(RuntimeError, "captured build"):
                        build_upstream_runtime.build_runtime(Path(temp), platform, arch, tag, None)
                    mode = "--define=litert_lm_stream_chunk_api=true" in run.call_args.args[0]
                    self.assertEqual(mode, expected == 2)
                    self.assertEqual(source_getter_abi(mode), manifest_for(tag)["abi"]["streamProxyCallback"])


if __name__ == "__main__":
    unittest.main()
