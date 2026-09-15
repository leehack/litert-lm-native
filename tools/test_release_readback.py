import subprocess
import unittest
from unittest.mock import patch

import reconcile_release_tag as subject


class ReleaseReadbackTest(unittest.TestCase):
    def test_api_bounds_process_and_sanitizes_timeout(self):
        with patch.object(
            subject.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired("secret", 10),
        ) as run:
            with self.assertRaisesRegex(
                subject.ApiTransportError,
                "GET repos/owner/repo/releases/1: request timed out",
            ):
                subject.api("repos/owner/repo/releases/1")
        self.assertEqual(run.call_args.kwargs["timeout"], 10)

    def test_readback_attempt_and_request_limits(self):
        with patch.object(
            subject, "api", return_value=(404, {"message": "Not Found"})
        ) as api, patch.object(subject.time, "sleep") as sleep:
            with self.assertRaisesRegex(
                subject.PublicationStateError, "budget exhausted"
            ):
                subject.read_release({"GITHUB_REPOSITORY": "owner/repo"}, False, 1)
        self.assertEqual(api.call_count, 3)
        self.assertEqual(
            [call.kwargs["timeout"] for call in api.call_args_list], [10, 10, 10]
        )
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])

    def test_late_success_is_never_accepted(self):
        with patch.object(
            subject.time, "monotonic", side_effect=[0, 1, 31]
        ), patch.object(subject, "api", return_value=(200, {"id": 1})):
            with self.assertRaisesRegex(
                subject.PublicationStateError, "deadline exhausted"
            ):
                subject.read_release({"GITHUB_REPOSITORY": "owner/repo"}, False, 1)

    def test_malformed_and_transport_responses_are_safe(self):
        for output in ("", "HTTP/2 200 OK\n\nsecret-not-json"):
            with self.subTest(output=output), patch.object(
                subject.subprocess,
                "run",
                return_value=subprocess.CompletedProcess(
                    [], 1, output, "signed-secret-url"
                ),
            ):
                with self.assertRaises(subject.PublicationStateError) as caught:
                    subject.api("repos/owner/repo/releases/1")
                self.assertNotIn("secret", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
