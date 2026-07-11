#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import package_ios_runtime


class PackageIosRuntimeTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
