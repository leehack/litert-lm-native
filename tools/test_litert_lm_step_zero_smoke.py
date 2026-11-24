import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import litert_lm_step_zero_smoke as smoke

from litert_lm_step_zero_smoke import MARKER, PROMPT, grade

REFERENCE = "Here are the numbers from one to twenty in English:\n\n1, 2, 3, 4, 5, 6, 7,"
DRIFT = "Here are the numbers from one to twenty in English:\n\n1. 2. 3. 4. 5. 6. 7."


def turn(content: str, **state) -> dict:
    return {
        "content": content,
        "terminal_count": 1,
        "callback_errors": [],
        "stream_errors": [],
        "first_content_seconds": 0.2,
        **state,
    }


def grade_sequence(contents: list[str], reference: str = REFERENCE, **changes) -> dict:
    repeated = {
        "independent": [turn(content) for content in contents],
        "reloaded": turn(reference),
        "marker": turn(MARKER),
        "after_marker": turn(reference),
        "after_cancel": turn(reference),
        "cancelled": turn("1", cancel_requested=True, stream_errors=["CANCELLED: Task cancelled"]),
        "reused": [turn(reference), turn("You asked me to count to twenty.")],
        "private_cache_removed": True,
        **changes,
    }
    fresh = [{"independent": [turn(reference)], "private_cache_removed": True}] * 2
    return grade("cpu", "recurrent", repeated, fresh)


class StepZeroSmokeTest(unittest.TestCase):
    def test_c_api_admission_checks_major_minor_and_patch(self) -> None:
        with patch.object(smoke, "CApi") as api:
            for version in ((1, 0, 0), (1, 1, 2)):
                api.return_value.api_version.return_value = version
                self.assertEqual(smoke.Runtime(Path("runtime")).version, version)
            api.return_value._bind.reset_mock()
            for version in ((0, 20, 0), (1, 2, 0), (1, 1, -1)):
                with self.subTest(version=version):
                    api.return_value.api_version.return_value = version
                    with self.assertRaisesRegex(RuntimeError, "Expected C API"):
                        smoke.Runtime(Path("runtime"))
            api.return_value._bind.assert_not_called()

    def test_requires_exact_independent_content_even_if_it_still_counts(self) -> None:
        clean = [REFERENCE] * 5
        self.assertEqual(grade_sequence(clean)["failures"], [])
        drift = [REFERENCE, REFERENCE, DRIFT, DRIFT, DRIFT]
        self.assertEqual(grade_sequence(drift)["failures"],
                         ["Qwen3.5 content differs from its fresh reference"])

    def test_rejects_an_echo_reference_even_if_every_answer_matches(self) -> None:
        self.assertIn("independent request echoed the input",
                      grade_sequence([PROMPT] * 5, reference=PROMPT)["failures"])
        self.assertIn("independent or fresh answer failed counting semantics",
                      grade_sequence(["OK"] * 5, reference="OK")["failures"])

    def test_rejects_duplicate_leading_digit_in_warm_and_post_marker_answers(self) -> None:
        duplicate = "1, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10"
        clean = [REFERENCE] * 5
        result = grade_sequence([REFERENCE, REFERENCE, duplicate, REFERENCE, REFERENCE])
        self.assertEqual(result["independent_outside_fresh"], [3])
        self.assertIn("independent or fresh answer failed counting semantics", result["failures"])
        result = grade_sequence(clean, after_marker=turn("1, 1, 1, 1, 2, 3, 4, 5, 6, 7, 8,"))
        self.assertEqual(result["independent_outside_fresh"], [6])
        self.assertIn("Qwen3.5 content differs from its fresh reference", result["failures"])

    def test_requires_drain_and_clean_generation_after_cancel(self) -> None:
        clean = [REFERENCE] * 5
        no_drain = turn("1", cancel_requested=True, terminal_count=0, stream_errors=["CANCELLED"])
        self.assertIn("cancellation did not reach a cancelled terminal callback and drain",
                      grade_sequence(clean, cancelled=no_drain)["failures"])
        self.assertIn("incomplete independent or fresh stream",
                      grade_sequence(clean, after_cancel=turn(""))["failures"])


class StepZeroSmokeInputTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.recurrent = self.root / "recurrent.litertlm"
        self.recurrent.write_bytes(b"recurrent model")
        self.attention = self.root / "attention.litertlm"
        self.attention.write_bytes(b"attention model")
        self.archive = self.root / "runtime.tar.gz"
        self.archive.write_bytes(b"runtime archive")
        self.evidence = self.root / "evidence"
        self.enterContext(patch.dict(smoke.MODELS, {
            "recurrent": smoke.sha256_file(self.recurrent),
            "attention": smoke.sha256_file(self.attention),
        }))
        self.enterContext(patch.object(smoke.platform, "system", return_value="Darwin"))
        self.enterContext(patch.object(smoke.platform, "machine", return_value="arm64"))
        self.extract = self.enterContext(patch.object(
            smoke.tarfile, "open",
            side_effect=AssertionError("invalid inputs reached runtime extraction"),
        ))

    def assert_model_rejected(self, recurrent: Path, attention: Path, message: str) -> None:
        argv = [
            smoke.__file__,
            "--archive", str(self.archive),
            "--archive-sha256", smoke.sha256_file(self.archive),
            "--library-sha256", "unused",
            "--model", str(recurrent),
            "--attention-model", str(attention),
            "--backend", "cpu",
            "--evidence", str(self.evidence),
        ]
        with patch.object(sys, "argv", argv):
            with self.assertRaisesRegex(RuntimeError, message):
                smoke.main()
        self.extract.assert_not_called()
        self.assertFalse(self.evidence.exists())

    def test_rejects_one_model_path_for_both_roles(self) -> None:
        self.assert_model_rejected(self.attention, self.attention, "same model file")

    def test_rejects_model_paths_that_resolve_to_the_same_file(self) -> None:
        alias = self.root / "alias.litertlm"
        alias.symlink_to(self.attention)
        self.assert_model_rejected(alias, self.attention, "same model file")

    def test_rejects_hard_link_to_the_same_model_file(self) -> None:
        alias = self.root / "hard-link.litertlm"
        os.link(self.attention, alias)
        self.assert_model_rejected(alias, self.attention, "same model file")

    def test_rejects_wrong_recurrent_model_at_a_distinct_path(self) -> None:
        self.recurrent.write_bytes(self.attention.read_bytes())
        self.assert_model_rejected(self.recurrent, self.attention, "--model SHA-256 mismatch")

    def test_rejects_wrong_attention_model_at_a_distinct_path(self) -> None:
        self.attention.write_bytes(self.recurrent.read_bytes())
        self.assert_model_rejected(self.recurrent, self.attention, "--attention-model SHA-256 mismatch")
