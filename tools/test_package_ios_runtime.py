#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import package_ios_runtime


class PackageIosRuntimeTest(unittest.TestCase):
    def test_framework_executable_is_owner_writable_and_executable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp_dir = Path(temp)
            source = temp_dir / "source"
            destination = temp_dir / "destination"
            source.write_bytes(b"runtime")
            source.chmod(0o555)

            package_ios_runtime.copy_framework_executable(source, destination)

            self.assertEqual(destination.read_bytes(), b"runtime")
            self.assertEqual(destination.stat().st_mode & 0o777, 0o755)

    def test_v015_wrapper_enables_stream_chunk_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp_dir = Path(temp)
            with patch.object(package_ios_runtime, "run") as run:
                with patch.object(package_ios_runtime, "validate_bridge_symbols"):
                    package_ios_runtime.build_wrapper(
                        {
                            "sdk": "iphoneos",
                            "target_arch": "arm64",
                        },
                        temp_dir,
                        temp_dir / "CLiteRTLM",
                        "v0.15.0",
                    )

            command = run.call_args.args[0]
            self.assertIn("-DLITERT_LM_STREAM_CHUNK_API=1", command)

    def test_v014_wrapper_keeps_legacy_callback_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp_dir = Path(temp)
            with patch.object(package_ios_runtime, "run") as run:
                with patch.object(package_ios_runtime, "validate_bridge_symbols"):
                    package_ios_runtime.build_wrapper(
                        {
                            "sdk": "iphoneos",
                            "target_arch": "arm64",
                        },
                        temp_dir,
                        temp_dir / "CLiteRTLM",
                        "v0.14.0",
                    )

            command = run.call_args.args[0]
            self.assertNotIn("-DLITERT_LM_STREAM_CHUNK_API=1", command)

    def test_pinned_tag_rejects_missing_official_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "missing.zip"
            with self.assertRaisesRegex(RuntimeError, "official upstream iOS"):
                package_ios_runtime.package_ios_runtime(
                    archive,
                    clean=True,
                    upstream_tag="v0.14.0",
                )

    def test_official_framework_requires_metal_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            framework = Path(temp) / "CLiteRTLM"
            framework.write_bytes(package_ios_runtime.IOS_GPU_SYMBOLS[0])
            with patch.object(package_ios_runtime, "required_c_api_symbols", return_value=[]):
                with self.assertRaisesRegex(RuntimeError, "iOS Metal symbols"):
                    package_ios_runtime.validate_upstream_symbols(
                        framework,
                        "v0.14.0",
                    )

    def test_pinned_official_archive_rejects_checksum_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "CLiteRTLM.xcframework.zip"
            archive.write_bytes(b"unexpected")
            with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                package_ios_runtime.validate_official_archive_checksum(
                    archive,
                    "v0.14.0",
                )

    def test_v016_prefers_source_built_runtime_for_asr_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "CLiteRTLM.xcframework.zip"
            archive.write_bytes(b"official-runtime-without-asr")
            specs = [{"arch": "arm64", "framework_binary": Path(temp) / "source"}]
            with patch.object(
                package_ios_runtime,
                "discover_source_built_ios_slices",
                return_value=specs,
            ):
                with patch.object(
                    package_ios_runtime,
                    "stage_source_built_slice",
                    return_value=Path(temp) / "staged",
                ) as stage:
                    result = package_ios_runtime.package_ios_runtime(
                        archive,
                        clean=True,
                        upstream_tag="v0.16.0",
                    )

            self.assertEqual(result, [Path(temp) / "staged"])
            stage.assert_called_once_with(
                specs[0], clean=True, upstream_tag="v0.16.0"
            )


if __name__ == "__main__":
    unittest.main()
