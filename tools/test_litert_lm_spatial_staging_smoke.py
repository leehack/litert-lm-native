import unittest

from litert_lm_spatial_staging_smoke import LOOKAHEAD, PROBES, summarize

METAL_LOG = f"Selected adapter: Apple M4 Max, backend=Metal\n{LOOKAHEAD}\n"


def turn(content: str) -> dict:
    return {"content": content, "terminal_count": 1, "stream_errors": [],
            "callback_errors": [], "first_content_seconds": 0.1}


class SpatialStagingSmokeTest(unittest.TestCase):
    def test_candidate_requires_exact_output_metal_lookahead_and_no_dawn_errors(self) -> None:
        _, expected, wrong = PROBES["arithmetic"]
        result = {"turns": [turn(expected), turn(expected)]}
        passed = summarize("gpu", result, METAL_LOG, expected, wrong, 2, False)
        self.assertEqual(passed["exact"], 2)
        self.assertEqual(passed["failures"], [])

        for label, data, log in (
            ("wrong output", {"turns": [turn(expected), turn(wrong)]}, METAL_LOG),
            ("missing result", {"turns": [turn(expected)]}, METAL_LOG),
            ("missing lookahead", result, METAL_LOG.replace(LOOKAHEAD, "")),
            ("missing Metal", result, METAL_LOG.replace("backend=Metal", "")),
            ("Dawn error", result, METAL_LOG + "Validation error: invalid buffer"),
        ):
            with self.subTest(label=label):
                self.assertTrue(summarize("gpu", data, log, expected, wrong, 2, False)["failures"])

    def test_control_requires_the_exact_known_corruption(self) -> None:
        for _, expected, wrong in PROBES.values():
            with self.subTest(expected=expected):
                result = {"turns": [turn(expected), turn(wrong)]}
                control = summarize("gpu", result, METAL_LOG, expected, wrong, 2, True)
                self.assertEqual(control["exact"], 1)
                self.assertEqual(control["failures"], [])
                result["turns"][1] = turn(expected)
                self.assertTrue(summarize("gpu", result, METAL_LOG, expected, wrong, 2, True)["failures"])


if __name__ == "__main__":
    unittest.main()
