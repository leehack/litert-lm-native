from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import build_upstream_runtime


class BuildUpstreamRuntimeTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
