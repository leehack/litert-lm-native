import unittest

from litert_lm_step_zero_smoke import PROMPT, grade

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
        "after_cancel": turn(reference),
        "cancelled": turn("1", cancel_requested=True, stream_errors=["CANCELLED: Task cancelled"]),
        "reused": [turn(reference), turn("You asked me to count to twenty.")],
        "private_cache_removed": True,
        **changes,
    }
    fresh = [{"independent": [turn(reference)], "private_cache_removed": True}] * 2
    return grade("cpu", "recurrent", repeated, fresh)


class StepZeroSmokeTest(unittest.TestCase):
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

    def test_requires_drain_and_clean_generation_after_cancel(self) -> None:
        clean = [REFERENCE] * 5
        no_drain = turn("1", cancel_requested=True, terminal_count=0, stream_errors=["CANCELLED"])
        self.assertIn("cancellation did not reach a cancelled terminal callback and drain",
                      grade_sequence(clean, cancelled=no_drain)["failures"])
        self.assertIn("incomplete independent or fresh stream",
                      grade_sequence(clean, after_cancel=turn(""))["failures"])
