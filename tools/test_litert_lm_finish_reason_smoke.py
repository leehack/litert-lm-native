from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import litert_lm_finish_reason_smoke as smoke


class FinishReasonSmokeTest(unittest.TestCase):
    def test_allocation_status_probe_rejects_missing_and_unknown_extensions(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "lacks callback"):
            smoke.require_allocation_failure_abi(SimpleNamespace())
        with self.assertRaisesRegex(RuntimeError, "lacks callback"):
            smoke.require_allocation_failure_abi(SimpleNamespace(
                stream_proxy_allocation_failure_abi_version=Mock(return_value=1)))
        for version in (0, 2):
            library = SimpleNamespace(
                stream_proxy_allocation_failure_abi_version=Mock(return_value=version),
                stream_proxy_has_allocation_failure=Mock(return_value=0),
            )
            with self.subTest(version=version), self.assertRaisesRegex(
                    RuntimeError, "unsupported callback"):
                smoke.require_allocation_failure_abi(library)
        library = SimpleNamespace(
            stream_proxy_allocation_failure_abi_version=Mock(return_value=1),
            stream_proxy_has_allocation_failure=Mock(return_value=0),
        )
        smoke.require_allocation_failure_abi(library)
        library.stream_proxy_has_allocation_failure.assert_not_called()


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

    def test_abi_only_expects_version_one_only_for_patched_tags(self) -> None:
        self.assertEqual(smoke.expected_abi_version("v0.18.0"), 1)
        self.assertEqual(smoke.expected_abi_version("v0.17.1"), 0)
        with self.assertRaisesRegex(RuntimeError, "no explicit decision"):
            smoke.expected_abi_version("v0.19.2")


if __name__ == "__main__":
    unittest.main()
