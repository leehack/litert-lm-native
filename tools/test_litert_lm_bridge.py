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
    def test_asr_session_adapter_preserves_both_upstream_apis(self) -> None:
        compiler = shutil.which("c++") or shutil.which("clang++")
        if compiler is None:
            self.skipTest("A C++ compiler is required for ASR adapter validation")
        source = REPO_ROOT / "native/bridge/litert_lm_asr_session_adapter_test.cc"
        with tempfile.TemporaryDirectory() as temp:
            executable = Path(temp) / "asr_adapter_test"
            subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                            str(source), "-o", str(executable)], check=True)
            subprocess.run([str(executable)], check=True)

    def test_production_asr_processing_preserves_legacy_and_omni_lifecycle(self) -> None:
        compiler = shutil.which("c++") or shutil.which("clang++")
        if compiler is None:
            self.skipTest("A C++ compiler is required for ASR lifecycle validation")
        bridge = (REPO_ROOT / "native/bridge/litert_lm_asr_bridge.cc").read_text()
        start = bridge.index("LitertLmAsrStatus\nlitert_lm_asr_session_process_next(")
        end = bridge.index("LitertLmAsrStatus litert_lm_asr_session_reset(", start)
        body = bridge[start:end]
        harness = (REPO_ROOT / "native/bridge/litert_lm_asr_process_test.cc").read_text()
        for omni in (False, True):
            with self.subTest(omni=omni), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                source = root / "process_test.cc"
                source.write_text(harness.replace("// PRODUCTION_PROCESS_NEXT", body))
                executable = root / "process_test"
                subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                                f"-DTEST_OMNI_API={int(omni)}", "-I", str(REPO_ROOT / "native"),
                                str(source), "-o", str(executable)], check=True)
                subprocess.run([str(executable)], check=True)

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
