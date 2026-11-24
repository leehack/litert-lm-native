from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import litert_lm_gpu_logging_smoke as smoke

ADAPTER = b"I0000 environment.cc:564] Selected adapter: Apple M4 Max, backend=Metal"
DELEGATE = b"I0000 delegate_webgpu.cc:755] # of threads to upload weights = 2"


class GpuLoggingSmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.enterContext(patch.object(smoke.platform, "system", return_value="Darwin"))
        self.enterContext(patch.object(smoke.platform, "machine", return_value="arm64"))
        self.enterContext(patch.object(smoke, "sha256_file", return_value="digest"))
        self.enterContext(patch("builtins.print"))
        self.enterContext(patch.object(sys, "argv", [
            smoke.__file__, "--library", "runtime.dylib", "--model", "model.litertlm",
        ]))

    def test_rejects_native_stderr_at_quiet_level(self) -> None:
        with patch.object(smoke, "capture_create", side_effect=[[ADAPTER, DELEGATE], [DELEGATE]]):
            with self.assertRaisesRegex(RuntimeError, "wrote to stderr at level 1000"):
                smoke.main()

    def test_requires_a_metal_and_webgpu_info_control(self) -> None:
        with patch.object(smoke, "capture_create", side_effect=[[ADAPTER], []]):
            with self.assertRaisesRegex(RuntimeError, "Info control did not log"):
                smoke.main()

    def test_counts_only_engine_create_stderr_after_a_successful_worker(self) -> None:
        stderr = (b"before\n" + smoke.CREATE_START + DELEGATE + b"\n"
                  + smoke.CREATE_END + b"after\n")
        result = subprocess.CompletedProcess([], 0, stderr=stderr)
        with patch.object(smoke.subprocess, "run", return_value=result):
            self.assertEqual(smoke.capture_create(Path("runtime"), Path("model"), 0), [DELEGATE])
            result.returncode = 1
            with self.assertRaisesRegex(RuntimeError, "exit 1"):
                smoke.capture_create(Path("runtime"), Path("model"), 0)
