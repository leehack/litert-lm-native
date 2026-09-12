from __future__ import annotations

import unittest
from unittest.mock import patch

from verify_qualification_source import main, verify_source


OLD_COMMIT = "945edf38faa78b4ead9d09ec5b07f266ee2029c1"
COMMIT = "e9fd8c53ff968071774206163027dd84bedfe925"


class VerifyQualificationSourceTest(unittest.TestCase):
    def test_cli_accepts_exact_tag_commit(self) -> None:
        with patch("sys.argv", ["verify_qualification_source.py", "--tag", "v0.17.0", "--commit", COMMIT]), patch(
            "verify_qualification_source.resolve_upstream_commit", return_value=COMMIT
        ) as resolve:
            self.assertEqual(main(), 0)
        resolve.assert_called_once_with("v0.17.0")

    def test_retag_rejects_previously_qualified_commit(self) -> None:
        with patch("verify_qualification_source.resolve_upstream_commit", return_value=COMMIT):
            with self.assertRaisesRegex(ValueError, "moved.*rerun all builds"):
                verify_source("v0.17.0", OLD_COMMIT)

    def test_future_retag_rejects_current_pin(self) -> None:
        with patch("verify_qualification_source.resolve_upstream_commit", return_value="a" * 40):
            with self.assertRaisesRegex(ValueError, "moved"):
                verify_source("v0.17.0", COMMIT)

    def test_malformed_pin_fails_before_network(self) -> None:
        with patch("verify_qualification_source.resolve_upstream_commit") as resolve:
            with self.assertRaisesRegex(ValueError, "40-hex"):
                verify_source("v0.17.0", COMMIT[:12])
        resolve.assert_not_called()

    def test_resolution_failure_fails_closed(self) -> None:
        with patch("verify_qualification_source.resolve_upstream_commit", side_effect=RuntimeError("unavailable")):
            with self.assertRaisesRegex(RuntimeError, "unavailable"):
                verify_source("v0.17.0", COMMIT)
