from __future__ import annotations

import unittest

import litert_lm_chat_smoke as smoke


class ChatSmokeTest(unittest.TestCase):
    def test_response_text_joins_text_parts(self) -> None:
        raw = '{"role":"assistant","content":[{"type":"text","text":"a"},{"type":"text","text":"b"}]}'
        self.assertEqual(smoke.response_text(raw), "ab")

    def test_answer_ignores_thinking(self) -> None:
        self.assertEqual(smoke.answer_after_thinking("<think>2 and 2</think>\n\n4"), "4")
        self.assertEqual(smoke.answer_after_thinking(" 4 "), "4")


if __name__ == "__main__":
    unittest.main()
