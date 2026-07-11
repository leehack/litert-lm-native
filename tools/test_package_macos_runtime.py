#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import package_macos_runtime


class PackageMacosRuntimeTest(unittest.TestCase):
    def test_pinned_tag_rejects_missing_official_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "missing.zip"
            with self.assertRaisesRegex(RuntimeError, "official upstream macOS"):
                package_macos_runtime.package_macos_runtime(
                    archive,
                    clean=True,
                    upstream_tag="v0.14.0",
                )

    def test_official_framework_requires_metal_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            framework = Path(temp) / "libCLiteRTLM_mac.dylib"
            framework.write_bytes(package_macos_runtime.MACOS_GPU_SYMBOLS[0])
            with patch.object(
                package_macos_runtime,
                "required_c_api_symbols",
                return_value=[],
            ):
                with patch.object(
                    package_macos_runtime,
                    "REQUIRED_PROVIDER_SYMBOLS",
                    [],
                ):
                    with self.assertRaisesRegex(RuntimeError, "macOS symbols"):
                        package_macos_runtime.validate_upstream_symbols(
                            framework,
                            "v0.14.0",
                        )

    def test_pinned_official_archive_rejects_checksum_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "CLiteRTLM_mac.xcframework.zip"
            archive.write_bytes(b"unexpected")
            with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                package_macos_runtime.validate_official_archive_checksum(
                    archive,
                    "v0.14.0",
                )


if __name__ == "__main__":
    unittest.main()
