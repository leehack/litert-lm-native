from __future__ import annotations

import contextlib
import errno
import hashlib
import io
import tempfile
import threading
import time
import unittest
import urllib.error
from datetime import datetime, timezone
from email.message import Message
from email.utils import format_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import download_utils as downloads
import fetch_litert_lm_asr_smoke_assets as assets

PAYLOAD = b"verified model bytes"


class DownloadHTTPTest(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.responses = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.requests.append(self.path)
                item = outer.responses.pop(0)
                if item.get("slow_headers"):
                    try:
                        for byte in b"HTTP/1.1 200 OK\r\nContent-Length: 20\r\n\r\n":
                            self.connection.sendall(bytes([byte]))
                            time.sleep(0.025)
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                    return
                status = item.get("status", 200)
                self.send_response(status)
                for name, value in item.get("headers", {}).items():
                    self.send_header(name, value)
                body = item.get("body", PAYLOAD if status == 200 else b"")
                self.send_header("Content-Length", str(item.get("length", len(body))))
                self.end_headers()
                try:
                    if item.get("stall"):
                        time.sleep(item["stall"])
                    if item.get("drip"):
                        for byte in body:
                            self.wfile.write(bytes([byte]))
                            self.wfile.flush()
                            time.sleep(item["drip"])
                    else:
                        self.wfile.write(body)
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                self.close_connection = True

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.url = (
            f"http://127.0.0.1:{self.server.server_port}/asset?signature=DO-NOT-LOG"
        )
        self.path = self.root / "model.tflite"

    def download(self, **kwargs):
        downloads.download_to_path(
            self.url,
            self.path,
            headers={},
            label="model.tflite",
            expected_sha256=hashlib.sha256(PAYLOAD).hexdigest(),
            **kwargs,
        )

    def test_actual_asr_call_retries_429_then_verifies_and_reuses_cache(self):
        self.responses = [{"status": 429, "headers": {"Retry-After": "0"}}, {}]
        asset = assets.Asset(
            "model.tflite", self.url, hashlib.sha256(PAYLOAD).hexdigest()
        )
        assets.fetch_asset(asset, self.root)
        assets.fetch_asset(asset, self.root)
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.path.read_bytes(), PAYLOAD)
        self.assertFalse(self.path.with_name("model.tflite.part").exists())

    def test_exhausted_attempts_and_permanent_error_are_safe(self):
        for status, count in ((429, 3), (503, 3), (404, 1), (403, 1), (501, 1)):
            with self.subTest(status=status):
                self.requests.clear()
                self.responses = [
                    {"status": status, "headers": {"Retry-After": "0"}}
                ] * count
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr), self.assertRaises(
                    RuntimeError
                ) as raised:
                    self.download()
                self.assertEqual(len(self.requests), count)
                self.assertNotIn(
                    "DO-NOT-LOG", stderr.getvalue() + str(raised.exception)
                )
                self.assertIsNone(raised.exception.__cause__)
                self.assertFalse(self.path.exists())
                self.assertFalse(self.path.with_name("model.tflite.part").exists())

    def test_checksum_failure_does_not_retry_or_replace_existing_file(self):
        self.path.write_bytes(b"old corrupt cache")
        self.responses = [{"body": b"wrong checksum"}]
        with self.assertRaisesRegex(RuntimeError, "Checksum mismatch"):
            self.download()
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.path.read_bytes(), b"old corrupt cache")
        self.assertFalse(self.path.with_name("model.tflite.part").exists())

    def test_actual_asr_worker_rejects_checksum_failure_without_retry(self):
        self.path.write_bytes(b"corrupt cache")
        self.responses = [{"body": b"wrong checksum"}]
        asset = assets.Asset(
            "model.tflite", self.url, hashlib.sha256(PAYLOAD).hexdigest()
        )
        with self.assertRaisesRegex(RuntimeError, "Checksum mismatch"):
            assets.fetch_asset(asset, self.root)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.path.read_bytes(), b"corrupt cache")
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_truncated_download_retries_from_empty_partial(self):
        self.responses = [{"body": b"cut", "length": len(PAYLOAD)}, {}]
        with patch.object(downloads.time, "sleep"):
            self.download()
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.path.read_bytes(), PAYLOAD)
        self.assertFalse(self.path.with_name("model.tflite.part").exists())

    def test_truncated_exhaustion_cleans_partial_and_preserves_cache(self):
        self.path.write_bytes(b"existing")
        self.path.with_name("model.tflite.part").write_bytes(b"stale partial")
        self.responses = [{"body": b"cut", "length": len(PAYLOAD)}] * 2
        with patch.object(downloads.time, "sleep"), self.assertRaises(RuntimeError):
            self.download(attempts=2)
        self.assertEqual(self.path.read_bytes(), b"existing")
        self.assertFalse(self.path.with_name("model.tflite.part").exists())

    def test_retry_after_cannot_exceed_total_budget(self):
        self.responses = [{"status": 429, "headers": {"Retry-After": "999999999"}}]
        with patch.object(downloads.time, "sleep") as sleep, self.assertRaisesRegex(
            RuntimeError, "deadline"
        ):
            self.download(deadline_seconds=0.8)
        sleep.assert_not_called()
        self.assertEqual(len(self.requests), 1)

    def test_socket_stall_and_drip_are_bounded_by_deadline(self):
        for response in ({"stall": 0.8}, {"drip": 0.08}):
            with self.subTest(response=response):
                self.requests.clear()
                self.responses = [response]
                started = time.monotonic()
                with self.assertRaises(RuntimeError):
                    self.download(timeout_seconds=0.2, deadline_seconds=0.5, attempts=1)
                self.assertLess(time.monotonic() - started, 1.5)
                self.assertFalse(self.path.exists())
                self.assertFalse(self.path.with_name("model.tflite.part").exists())

    def test_slow_headers_are_killed_before_promotion_and_leave_no_worker_files(self):
        self.responses = [{"slow_headers": True}]
        started = time.monotonic()
        with self.assertRaisesRegex(RuntimeError, "deadline"):
            self.download(timeout_seconds=0.2, deadline_seconds=0.5)
        self.assertLess(time.monotonic() - started, 0.8)
        self.assertEqual(list(self.root.iterdir()), [])
        # No abandoned child may later finish and promote its output.
        time.sleep(0.2)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_redirect_header_stall_is_inside_the_same_deadline(self):
        self.responses = [
            {"status": 302, "headers": {"Location": "/redirected"}},
            {"slow_headers": True},
        ]
        with self.assertRaisesRegex(RuntimeError, "deadline"):
            self.download(timeout_seconds=0.2, deadline_seconds=0.5)
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_fetch_json_shared_retry_preserves_shape_and_sanitizes_permanent_failure(
        self,
    ):
        self.responses = [
            {"status": 503, "headers": {"Retry-After": "0"}},
            {"body": b'{"ok": true}'},
        ]
        self.assertEqual(downloads.fetch_json(self.url, headers={}), {"ok": True})
        self.responses = [{"status": 401}]
        with self.assertRaises(RuntimeError) as raised:
            downloads.fetch_json(self.url, headers={})
        self.assertNotIn("DO-NOT-LOG", str(raised.exception))


class RetryHeaderTest(unittest.TestCase):
    def delay(self, value):
        headers = Message()
        headers["Retry-After"] = value
        error = urllib.error.HTTPError(
            "https://secret.invalid/signed", 429, "bad", headers, None
        )
        try:
            with patch.object(downloads.time, "time", return_value=1000):
                return downloads._retry_delay(error, 2)
        finally:
            error.close()

    def test_retry_budget_never_sleeps_past_deadline(self):
        headers = Message()
        headers["Retry-After"] = "999999"
        error = urllib.error.HTTPError(
            "https://secret.invalid", 429, "bad", headers, None
        )

        def operation():
            raise error

        with patch.object(downloads.time, "sleep") as sleep, self.assertRaisesRegex(
            RuntimeError, "deadline"
        ):
            downloads._with_retries(
                operation,
                description="asset",
                attempts=3,
                deadline=time.monotonic() + 0.5,
            )
        sleep.assert_not_called()

    def test_network_oserror_retries_but_local_disk_error_does_not(self):
        for number, expected in ((errno.ENETUNREACH, 2), (errno.ENOSPC, 1)):
            operation = unittest.mock.Mock(
                side_effect=[OSError(number, "private details"), "ok"]
            )
            with patch.object(downloads.time, "sleep"):
                if expected == 2:
                    self.assertEqual(
                        downloads._with_retries(
                            operation, description="asset", attempts=2
                        ),
                        "ok",
                    )
                else:
                    with self.assertRaises(OSError):
                        downloads._with_retries(
                            operation, description="asset", attempts=2
                        )
            self.assertEqual(operation.call_count, expected)

    def test_bounded_seconds_dates_and_malformed_headers(self):
        for value, expected in (
            ("0", 0),
            ("5", 5),
            ("999999999", 30),
            ("-1", 2),
            ("NaN", 2),
            ("inf", 2),
            ("1e100000", 2),
            ("9" * 200, 2),
            ("malformed", 2),
            ("１２", 2),
        ):
            with self.subTest(value=value):
                self.assertEqual(self.delay(value), expected)
        self.assertEqual(
            self.delay(format_datetime(datetime.fromtimestamp(1007, timezone.utc))), 7
        )
        self.assertEqual(
            self.delay(format_datetime(datetime.fromtimestamp(999, timezone.utc))), 2
        )
        self.assertEqual(
            self.delay(format_datetime(datetime.fromtimestamp(999999, timezone.utc))),
            30,
        )


if __name__ == "__main__":
    unittest.main()
