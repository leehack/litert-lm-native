from __future__ import annotations

import json
import unittest

import litert_lm_finish_reason_smoke as smoke


class FinishReasonSmokeTest(unittest.TestCase):
    def test_scenarios_cover_budget_natural_end_and_cancellation(self) -> None:
        expected = {scenario.expected for scenario in smoke.SCENARIOS}
        self.assertEqual(expected, {"length", "stop", "cancelled"})
        budget, natural = (
            next(s for s in smoke.SCENARIOS if s.expected == name)
            for name in ("length", "stop")
        )
        # The natural end must use the budget prompt so only the cap differs.
        self.assertEqual(budget.prompt, natural.prompt)
        self.assertLess(budget.max_output_tokens, natural.max_output_tokens)

    def test_mismatches_report_only_unexpected_reasons(self) -> None:
        results = [
            {"scenario": "a", "expected": "stop", "finishReason": "stop"},
            {"scenario": "b", "expected": "length", "finishReason": "stop"},
        ]
        self.assertEqual(smoke.mismatches(results),
                         ["b: expected length, got stop"])

    def test_wire_names_match_bridge_values(self) -> None:
        self.assertEqual(
            smoke.FINISH_REASONS,
            {0: "unknown", 1: "stop", 2: "length", 3: "context_exhausted",
             4: "cancelled", 5: "error"},
        )

    def test_message_is_a_single_user_text_turn(self) -> None:
        self.assertEqual(
            json.loads(smoke.message_json("hi")),
            {"role": "user", "content": [{"type": "text", "text": "hi"}]},
        )


if __name__ == "__main__":
    unittest.main()
