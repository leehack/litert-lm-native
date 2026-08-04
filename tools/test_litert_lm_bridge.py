from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BRIDGE_SOURCE = REPO_ROOT / "native" / "bridge" / "litert_lm_bridge.c"
BRIDGE_TEST_SOURCE = (
    REPO_ROOT / "native" / "bridge" / "litert_lm_bridge_test.c"
)


class LiteRtLmBridgeTest(unittest.TestCase):
    def test_legacy_callback_adapter(self) -> None:
        self._compile_and_run(stream_chunk_api=False)

    def test_stream_chunk_callback_adapter(self) -> None:
        self._compile_and_run(stream_chunk_api=True)

    def _compile_and_run(self, *, stream_chunk_api: bool) -> None:
        compiler = shutil.which("cc") or shutil.which("clang")
        if compiler is None:
            self.skipTest("A C compiler is required for bridge validation")

        with tempfile.TemporaryDirectory(prefix="litert-lm-bridge-test-") as temp:
            executable = Path(temp) / "bridge_test"
            command = [
                compiler,
                "-std=c11",
                "-Wall",
                "-Wextra",
                "-Werror",
            ]
            if stream_chunk_api:
                command.append("-DLITERT_LM_STREAM_CHUNK_API=1")
            command.extend(
                [
                    str(BRIDGE_SOURCE),
                    str(BRIDGE_TEST_SOURCE),
                    "-o",
                    str(executable),
                ]
            )
            subprocess.run(command, check=True)
            subprocess.run([str(executable)], check=True)


if __name__ == "__main__":
    unittest.main()
