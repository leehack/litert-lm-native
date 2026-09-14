from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.error

import runner_downloads as diagnostic


class DownloadDiagnosticTest(unittest.TestCase):
    def test_urls_and_clients_match_failed_transaction(self):
        self.assertEqual(diagnostic.UPSTREAM, "e9fd8c53ff968071774206163027dd84bedfe925")
        self.assertEqual(diagnostic.URLS["owner_source"], f"https://github.com/google-ai-edge/LiteRT-LM/archive/{diagnostic.UPSTREAM}.tar.gz")
        self.assertEqual(diagnostic.USER_AGENT, "litert-lm-native-build")
        self.assertEqual(diagnostic.BAZELISK_PACKAGE, "@bazel/bazelisk@1.28.1")
        self.assertEqual(diagnostic.BAZEL_VERSION, "7.6.1")
        self.assertEqual(diagnostic.RULES_SHA256, "bc61ef94facc78e20a645726f64756e5e285a045037c7a61f65af2941f4c25e1")
        for system, machine, suffix in [("Windows", "AMD64", "windows-x86_64.exe"), ("Linux", "x86_64", "linux-x86_64"), ("Linux", "aarch64", "linux-arm64"), ("Darwin", "arm64", "darwin-arm64")]:
            with self.subTest(system=system, machine=machine), patch.object(diagnostic.platform, "system", return_value=system), patch.object(diagnostic.platform, "machine", return_value=machine):
                self.assertEqual(diagnostic.host_bazel_url(), f"https://github.com/bazelbuild/bazel/releases/download/7.6.1/bazel-7.6.1-{suffix}")

    def test_redirect_and_error_metadata_never_expose_queries_or_headers(self):
        url = "https://user:password@release-assets.githubusercontent.com/path?signature=secret#token"
        self.assertEqual(diagnostic.safe_url(url), "https://release-assets.githubusercontent.com/path")
        self.assertEqual(diagnostic.safe_url("https://untrusted.invalid/secret?token=secret"), "[other-host]")
        records = []
        handler = diagnostic.Redirects(records)
        request = diagnostic.urllib.request.Request(diagnostic.RULES_URL)
        handler.redirect_request(request, None, 302, "Found", {}, url)
        self.assertNotIn("secret", json.dumps(records))
        error = urllib.error.HTTPError(url, 504, "private secret", {"Set-Cookie": "secret", "Location": url, "Retry-After": "2", "X-Cache": "HIT"}, None)
        with patch.object(diagnostic.urllib.request, "build_opener") as opener:
            opener.return_value.open.side_effect = error
            result = diagnostic.screen(diagnostic.RULES_URL)
        self.assertEqual(result["result"], "fail")
        self.assertEqual(result["status"], 504)
        self.assertEqual(result["retryAfterSeconds"], 2)
        self.assertNotIn("secret", json.dumps(result))
        self.assertNotIn("password", json.dumps(result))
        error.close()

    def test_get_is_bounded_and_wrong_body_fails(self):
        for body, expected in [(b"\x1f\x8btest", "pass"), (b"gateway error", "fail")]:
            response = Mock(code=200, url=diagnostic.RULES_URL, headers={})
            response.read.return_value = body
            opener = Mock()
            opener.open.return_value.__enter__ = Mock(return_value=response)
            opener.open.return_value.__exit__ = Mock(return_value=False)
            with patch.object(diagnostic.urllib.request, "build_opener", return_value=opener):
                result = diagnostic.screen(diagnostic.RULES_URL)
            self.assertEqual(result["result"], expected)
            response.read.assert_called_once_with(65536)
            request = opener.open.call_args.args[0]
            self.assertEqual(request.get_method(), "GET")
            self.assertEqual(request.get_header("User-agent"), diagnostic.USER_AGENT)

    def test_complete_download_uses_production_client_and_rejects_wrong_checksum(self):
        # Exercise the actual downloader over an in-memory transport, not network.
        data = b"small archive fixture"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            opener = Mock()
            def response(*args, **kwargs):
                body = io.BytesIO(data)
                body.code, body.url, body.headers = 200, diagnostic.RULES_URL, {}
                return body
            opener.open.side_effect = response
            with patch.object(diagnostic.urllib.request, "build_opener", return_value=opener), patch.object(diagnostic, "RULES_SHA256", hashlib.sha256(data).hexdigest()):
                self.assertEqual(diagnostic.owner_download(root)["result"], "pass")
            request = opener.open.call_args.args[0]
            self.assertEqual(request.full_url, diagnostic.RULES_URL)
            self.assertEqual(request.get_header("User-agent"), diagnostic.USER_AGENT)
            self.assertEqual(opener.open.call_args.kwargs["timeout"], 60)
            with patch.object(diagnostic.urllib.request, "build_opener", return_value=opener):
                self.assertEqual(diagnostic.owner_download(root)["result"], "fail")
            with self.assertRaisesRegex(ValueError, "checksum"):
                diagnostic.verify_checksum(root / "rules_shell.tar.gz")

    def test_small_download_byte_limit_fails_closed(self):
        response = diagnostic.LimitedResponse(io.BytesIO(b"x" * (diagnostic.SMALL_ARCHIVE_BYTES + 1)))
        response.read(diagnostic.SMALL_ARCHIVE_BYTES)
        with self.assertRaisesRegex(ValueError, "byte bound"):
            response.read(1)

    def test_bazel_fetch_is_pinned_fresh_batch_and_has_no_build(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(diagnostic.shutil, "which", return_value="npx"), patch.object(diagnostic, "command", side_effect=[{"result": "pass", "bazel761": True}, {"result": "pass"}]) as run, patch.object(diagnostic, "repository_inventory", return_value={"result": "pass", "onlyPinnedSmallArchive": True}):
                result = diagnostic.bazel_probes(root)
            self.assertEqual(result["repository"]["result"], "pass")
            commands = [call.args[0] for call in run.call_args_list]
            for command in commands:
                self.assertIn("--batch", command)
                self.assertIn("--ignore_all_rc_files", command)
                self.assertIn(diagnostic.BAZELISK_PACKAGE, command)
                self.assertIn(f"--output_user_root={root / 'output'}", command)
                self.assertNotIn("build", command)
                self.assertNotIn("run", command)
            self.assertIn("query", commands[1])
            self.assertIn("@probe//:downloaded", commands[1])
            self.assertIn(f"--repository_cache={root / 'repository-cache'}", commands[1])
            env = run.call_args.args[2]
            self.assertEqual(env["USE_BAZEL_VERSION"], "7.6.1")
            self.assertEqual(env["BAZELISK_HOME"], str(root / "bazelisk"))
            self.assertEqual(env["npm_config_cache"], str(root / "npm"))
            workspace = (root / "WORKSPACE").read_text()
            self.assertIn(f'sha256="{diagnostic.RULES_SHA256}"', workspace)
            self.assertIn(f'url="{diagnostic.RULES_URL}"', workspace)
            self.assertEqual(workspace.count("http_archive(name="), 1)

    def test_repository_inventory_rejects_wrong_hash_and_fetch_fanout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "repository-cache/content_addressable/sha256/fixture/file"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"fixture")
            self.assertEqual(diagnostic.repository_inventory(root)["result"], "fail")
            with patch.object(diagnostic, "RULES_SHA256", hashlib.sha256(b"fixture").hexdigest()):
                self.assertEqual(diagnostic.repository_inventory(root)["result"], "pass")
                extra = path.parents[1] / "extra/file"
                extra.parent.mkdir()
                extra.write_bytes(b"extra archive")
                self.assertEqual(diagnostic.repository_inventory(root)["result"], "fail")

    def test_wrong_bazel_version_cannot_pass_or_fetch(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(diagnostic.shutil, "which", return_value="npx"), patch.object(diagnostic, "command", return_value={"result": "pass", "bazel761": False}) as run:
            result = diagnostic.bazel_probes(Path(temporary))
            self.assertEqual(result["repository"]["result"], "skipped")
            self.assertEqual(run.call_count, 1)
        self.assertFalse(diagnostic.round_passed({}))

    def test_deadlines_kill_client_and_suppress_raw_errors(self):
        process = Mock()
        process.communicate.side_effect = subprocess.TimeoutExpired("secret signed URL", 1, output=b"token=secret")
        with patch.object(diagnostic.subprocess, "Popen", return_value=process), patch.object(diagnostic, "kill_tree") as kill:
            result = diagnostic.command(["client"], Path("."), {}, 1)
        kill.assert_called_once_with(process)
        self.assertEqual(result["error"], "deadline")
        self.assertNotIn("secret", json.dumps(result))
        self.assertEqual((diagnostic.ROUNDS, diagnostic.INTERVAL_SECONDS, diagnostic.ROUND_SECONDS), (3, 300, 240))

    def test_production_round_rejects_failed_owner_even_with_passing_report(self):
        passing_owner = {"result": "pass", "sha256": diagnostic.RULES_SHA256, "bytesRead": 22017}
        passing_bazel = {"bootstrap": {"result": "pass", "bazel761": True},
                         "repository": {"result": "pass"}, "repositoryInventory": {"onlyPinnedSmallArchive": True}}
        cases = [
            ({"result": "fail", "error": "deadline"}, passing_owner, False),
            ({"result": "fail", "exitCode": 1}, passing_owner, False),
            ({"result": "pass"}, None, False),
            ({"result": "pass"}, {"result": "pass"}, False),
            ({"result": "pass"}, passing_owner, True),
        ]
        for status, payload, expected in cases:
            with self.subTest(status=status, payload=payload), tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / "round.json"
                def owner_worker(command, *args):
                    path = Path(command[-1])
                    self.assertFalse(path.exists(), "Owner evidence must be fresh")
                    if payload is not None:
                        path.write_text(json.dumps(payload))
                    return status
                with patch.object(diagnostic, "command", side_effect=owner_worker), patch.object(diagnostic, "bazel_probes", return_value=passing_bazel), patch.object(diagnostic, "screen", return_value={"result": "pass"}), patch.object(diagnostic, "host_bazel_url", return_value="https://example.invalid/bazel"):
                    diagnostic.run_round(output)
                report = json.loads(output.read_text())
                self.assertEqual(diagnostic.round_passed(report), expected)
                if status["result"] == "fail":
                    self.assertEqual(report["ownerSmallArchive"], status)

    def test_worker_failure_and_stale_pass_report_cannot_pass(self):
        for worker_result in ("pass", "fail"):
            with self.subTest(worker_result=worker_result), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                output = root / "diagnostic-results"
                output.mkdir()
                stale = output / "round-1.json"
                stale.write_text('{"oldPassedEvidence": true}')
                def worker(*args):
                    self.assertFalse(stale.exists(), "Old report must be removed before launch")
                    if worker_result == "fail":
                        stale.write_text('{"newButIncomplete": true}')
                    return {"result": worker_result}
                with patch.object(diagnostic, "ROOT", root), patch.object(diagnostic, "ROUNDS", 1), patch.object(diagnostic, "command", side_effect=worker), patch.object(diagnostic, "round_passed", return_value=True), patch.object(diagnostic.time, "sleep"), patch.object(diagnostic.sys, "argv", ["diagnostic"]):
                    self.assertEqual(diagnostic.main(), 1)
                self.assertFalse(json.loads((output / "summary.json").read_text())["rounds"][0]["allAcquisitionsPassed"])

    def test_sanitized_client_errors_and_diagnostic_identity(self):
        process = Mock(returncode=1)
        process.communicate.return_value = (b"", b"HTTP 504 https://host/path?token=secret npm error code E404 checksum mismatch timeout")
        with patch.object(diagnostic.subprocess, "Popen", return_value=process):
            result = diagnostic.command(["client"], Path("."), {}, 1)
        self.assertEqual(result["httpStatuses"], [504])
        self.assertEqual(result["npmErrorCodes"], ["E404"])
        self.assertTrue(result["checksumMismatchReported"])
        self.assertTrue(result["timeoutReported"])
        self.assertNotIn("secret", json.dumps(result))
        with tempfile.TemporaryDirectory() as temporary, patch.dict(diagnostic.os.environ, {"GITHUB_SHA": "a" * 40, "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "2", "GITHUB_TOKEN": "secret"}):
            path = Path(temporary) / "report.json"
            diagnostic.write_report(path, {})
            report = json.loads(path.read_text())
            self.assertEqual(report["diagnosticRun"], {"headSha": "a" * 40, "runId": "123", "runAttempt": "2"})
            self.assertEqual(report["investigatedRelease"]["nativeCommit"], "deef59818b0514c54929d7215c10ed6cba3b0f63")
            self.assertNotIn("secret", path.read_text())

    def test_workflow_is_manual_read_only_and_has_only_diagnostic_command(self):
        source = (diagnostic.ROOT / ".github/workflows/runner_download_diagnostic.yml").read_text()
        self.assertEqual(source.split("on:\n", 1)[1].split("\npermissions:", 1)[0].strip(), "workflow_dispatch:")
        self.assertEqual(re.findall(r"^permissions:\n((?:  .+\n)+)", source, re.M), ["  contents: read\n"])
        self.assertNotRegex(source, r"(?m)^[ \t]+(permissions|environment|secrets):")
        self.assertEqual(re.findall(r"(?m)^\s+run: (.+)$", source), ["python diagnostics/runner_downloads.py"])
        self.assertNotRegex(source, r"(?m)^\s+run: [|>]")
        self.assertEqual(re.findall(r"(?m)^[ \t]+(?:- )?uses: (.+)$", source), ["actions/checkout@v6", "actions/setup-node@v4", "actions/upload-artifact@v4"])
        self.assertIn("uses: actions/upload-artifact@v4", source)
        self.assertIn("persist-credentials: false", source)
        self.assertIn("timeout-minutes: 17", source)
        self.assertIn("os: [windows-latest, ubuntu-latest, ubuntu-24.04-arm, macos-latest]", source)
        self.assertIn("path: diagnostic-results/*.json", source)
        self.assertNotIn("secrets.", source)
        self.assertNotIn("github.token", source)
        self.assertNotRegex(source, r"(?m)^[ \t]+env:")
        self.assertNotRegex(source, r"run: [^\n]+\n[ \t]{9,}[^ \t\n]")
        qualification = (diagnostic.ROOT / ".github/workflows/pr_release_qualification.yml").read_text().split("concurrency:", 1)[0]
        self.assertNotIn("diagnostics/", qualification)
        self.assertNotIn("runner_download_diagnostic.yml", qualification)


if __name__ == "__main__":
    unittest.main()
