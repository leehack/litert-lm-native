from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import validate_runtime_dependencies as validate


class DesktopLiteRtBundleTest(unittest.TestCase):
    def test_current_cli_rejects_separate_desktop_litert_and_accelerator(self) -> None:
        cases = (
            "linux/x64/libLiteRt.so",
            "linux/arm64/libLiteRtWebGpuAccelerator.so",
            "macos/arm64/libLiteRtWebGpuAccelerator.dylib",
            "windows/x64/libLiteRt.dll",
        )
        for library in cases:
            with self.subTest(library=library), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "bin" / library
                path.parent.mkdir(parents=True)
                path.touch()
                with patch.object(sys, "argv", [
                    "validate_runtime_dependencies.py", "--root", directory,
                    "--upstream-tag", "v0.20.0",
                ]), self.assertRaises(SystemExit) as failure:
                    validate.main()
                self.assertIn(f"bin/{library}", str(failure.exception))

    def test_accepts_legacy_companions_and_current_runtime_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "bin/linux/x64"
            runtime.mkdir(parents=True)
            companion = runtime / "libLiteRt.so"
            companion.touch()
            validate.validate_desktop_litert_bundle(root, "v0.19.1")
            companion.unlink()
            for name in ("libLiteRtLm.so", "libwebgpu_dawn.so",
                         "libGemmaModelConstraintProvider.so"):
                (runtime / name).touch()
            validate.validate_desktop_litert_bundle(root, "v0.20.0")
