from __future__ import annotations

import subprocess
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import litert_lm_cpu_threads_probe as probe


class CpuThreadsProbeTest(unittest.TestCase):
    def test_thread_count_sees_a_new_native_thread(self) -> None:
        release = threading.Event()
        before = probe.process_thread_count()
        worker = threading.Thread(target=release.wait)
        worker.start()
        try:
            self.assertEqual(probe.process_thread_count(), before + 1)
        finally:
            release.set()
            worker.join()

    def test_requires_one_worker_per_extra_thread(self) -> None:
        self.assertTrue(probe.evaluate(4, {1: 2, 4: 5})["passed"])
        self.assertTrue(probe.evaluate(4, {1: 2, 4: 6})["passed"])
        ignored = probe.evaluate(4, {1: 2, 4: 2})
        self.assertFalse(ignored["passed"])
        self.assertEqual((ignored["addedThreads"], ignored["requiredAddedThreads"]), (0, 3))
        self.assertFalse(probe.evaluate(4, {1: 2, 4: 4})["passed"])

    def test_cli_measures_each_count_in_its_own_process_and_fails_when_ignored(self) -> None:
        for counts, code in (({1: 1, 4: 1}, 1), ({1: 1, 4: 4}, 0)):
            with self.subTest(counts=counts), patch.object(
                probe, "measure_in_child", side_effect=lambda _l, _m, n: counts[n]
            ) as measure:
                self.assertEqual(probe.main(["--library", "lib", "--model", "m", "--threads", "4"]), code)
                self.assertEqual([call.args[2] for call in measure.call_args_list], [1, 4])
                self.assertEqual(measure.call_args_list[0].args[0], Path("lib").resolve())

    def test_child_failure_reports_its_output(self) -> None:
        failed = subprocess.CompletedProcess([], 1, stdout="", stderr="engine create failed")
        with patch.object(probe.subprocess, "run", return_value=failed), \
             self.assertRaisesRegex(RuntimeError, "num_threads=4 probe exited with 1:\nengine create failed"):
            probe.measure_in_child(Path("lib"), Path("m"), 4)

    def test_cli_rejects_a_single_thread_target(self) -> None:
        with self.assertRaises(SystemExit):
            probe.main(["--library", "lib", "--model", "m", "--threads", "1"])


if __name__ == "__main__":
    unittest.main()
