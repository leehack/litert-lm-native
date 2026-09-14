"""Bounded, read-only acquisition screening; never a release qualification gate."""
from __future__ import annotations

import argparse
import contextlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = "e9fd8c53ff968071774206163027dd84bedfe925"
INVESTIGATION = {"nativeCommit": "deef59818b0514c54929d7215c10ed6cba3b0f63", "upstreamCommit": UPSTREAM,
                 "runId": "34856149932", "correlationId": "litert-v017-deef598-20260914-retry1"}
BAZEL_VERSION = "7.6.1"
BAZELISK_PACKAGE = "@bazel/bazelisk@1.28.1"
USER_AGENT = "litert-lm-native-build"
ROUNDS = 3
INTERVAL_SECONDS = 300
ROUND_SECONDS = 240
PREFIX_BYTES = 64 * 1024
SMALL_ARCHIVE_BYTES = 2 * 1024 * 1024
RULES_URL = "https://github.com/bazelbuild/rules_shell/releases/download/v0.4.1/rules_shell-v0.4.1.tar.gz"
RULES_SHA256 = "bc61ef94facc78e20a645726f64756e5e285a045037c7a61f65af2941f4c25e1"
URLS = {
    "owner_source": f"https://github.com/google-ai-edge/LiteRT-LM/archive/{UPSTREAM}.tar.gz",
    "litert_source": "https://github.com/google-ai-edge/LiteRT/archive/9fe5be45564c868408e6514c8aabb83e211a0911.tar.gz",
    "rules_shell": RULES_URL,
    "rules_apple": "https://github.com/bazelbuild/rules_apple/releases/download/3.22.0/rules_apple.3.22.0.tar.gz",
    "rules_swift": "https://github.com/bazelbuild/rules_swift/releases/download/2.9.0/rules_swift.2.9.0.tar.gz",
    "rules_ml_toolchain": "https://github.com/google-ml-infra/rules_ml_toolchain/archive/2eddbc595cc0bbe650c2640204f66b14f015f1a8.tar.gz",
    "abseil": "https://github.com/abseil/abseil-cpp/archive/20260526.0.tar.gz",
}


def safe_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    # Deliberately omit userinfo, query, fragment and all unrecognized hosts.
    host = parsed.hostname or ""
    if host not in {"github.com", "codeload.github.com", "release-assets.githubusercontent.com"}:
        return "[other-host]"
    return f"https://{host}{parsed.path}"


def response_metadata(response) -> dict:
    result = {"status": response.code, "url": safe_url(response.url)}
    retry = response.headers.get("Retry-After", "")
    if retry.isdecimal() and len(retry) <= 8:
        result["retryAfterSeconds"] = int(retry)
    # Do not retain arbitrary server header text, cookies, auth or signed URLs.
    for header in ("X-GitHub-Request-Id", "X-Ms-Request-Id"):
        value = response.headers.get(header, "")
        if value and len(value) <= 80 and all(c in "0123456789abcdefABCDEF:-" for c in value):
            result[header] = value
    cache = response.headers.get("X-Cache", "").upper()
    if cache in {"HIT", "MISS", "HIT, HIT", "MISS, HIT"}:
        result["cache"] = cache
    return result


class Redirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, records: list):
        self.records = records

    def redirect_request(self, request, response, code, message, headers, new_url):
        self.records.append({"status": code, "from": safe_url(request.full_url), "to": safe_url(new_url)})
        return super().redirect_request(request, response, code, message, headers, new_url)


def screen(url: str) -> dict:
    records: list = []
    start = time.monotonic()
    result = {"scope": "bounded GET only; not complete artifact verification", "client": "urllib", "redirects": records}
    try:
        opener = urllib.request.build_opener(Redirects(records))
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with opener.open(request, timeout=10) as response:
            result.update(response_metadata(response))
            body = response.read(PREFIX_BYTES)
            expected_prefix = b"MZ" if url.endswith(".exe") else b"\x7fELF" if "bazel-7.6.1-linux-" in url else b"\xcf\xfa\xed\xfe" if "bazel-7.6.1-darwin-" in url else b"\x1f\x8b"
            result.update(bytesRead=len(body), prefixHex=body[:4].hex(), result="pass" if response.code == 200 and body.startswith(expected_prefix) else "fail")
    except urllib.error.HTTPError as error:
        result.update(response_metadata(error), result="fail", error="http")
        error.close()
    except Exception:
        result.update(result="fail", error="transport")
    result["seconds"] = round(time.monotonic() - start, 3)
    return result


class LimitedResponse:
    def __init__(self, response):
        self.response = response
        self.total = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.response.close()

    def read(self, size: int) -> bytes:
        body = self.response.read(min(size, SMALL_ARCHIVE_BYTES + 1 - self.total))
        self.total += len(body)
        if self.total > SMALL_ARCHIVE_BYTES:
            raise ValueError("Small archive byte bound exceeded")
        return body


def verify_checksum(path: Path) -> None:
    if hashlib.sha256(path.read_bytes()).hexdigest() != RULES_SHA256:
        raise ValueError("Pinned checksum mismatch")


def owner_download(directory: Path) -> dict:
    start = time.monotonic()
    # Invoke the existing production downloader without changing its retries,
    # timeout, User-Agent or redirect semantics; only cap diagnostic body size.
    sys.path.insert(0, str(ROOT / "tools"))
    from download_utils import download_to_path
    records: list = []
    opener = urllib.request.build_opener(Redirects(records))
    output = directory / "rules_shell.tar.gz"
    result = {"client": "production download_utils.download_to_path", "scope": "complete checksum-pinned small archive", "redirects": records}
    def open_bounded(request, timeout):
        try:
            response = opener.open(request, timeout=timeout)
            result["lastResponse"] = response_metadata(response)
            return LimitedResponse(response)
        except urllib.error.HTTPError as error:
            result["lastResponse"] = response_metadata(error)
            error.close()
            raise
    try:
        # Raw client exceptions/logs may contain signed URLs: never retain them.
        with contextlib.redirect_stderr(io.StringIO()), patch.object(urllib.request, "urlopen", side_effect=open_bounded):
            download_to_path(RULES_URL, output, headers={"User-Agent": USER_AGENT}, label="pinned rules_shell")
        try:
            verify_checksum(output)
        except ValueError:
            result.update(result="fail", error="checksum_mismatch")
        else:
            result.update(result="pass", sha256=RULES_SHA256, bytesRead=output.stat().st_size)
    except Exception:
        result.update(result="fail", error="http" if result.get("lastResponse", {}).get("status", 0) >= 400 else "transport_or_size_bound")
    result["seconds"] = round(time.monotonic() - start, 3)
    return result


def kill_tree(process: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        # Nested acquisition clients may start their own process groups. Kill
        # descendants as well as the worker so a deadline leaves no Bazel server.
        listing = subprocess.check_output(["ps", "-eo", "pid=,ppid="], text=True)
        parents = {int(pid): int(parent) for pid, parent in (line.split() for line in listing.splitlines())}
        descendants = [process.pid]
        for parent in descendants:
            descendants.extend(pid for pid, ppid in parents.items() if ppid == parent and pid not in descendants)
        for pid in reversed(descendants):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    process.wait()


def command(command: list[str], directory: Path, env: dict, seconds: int) -> dict:
    start = time.monotonic()
    # Capture only in memory, never upload or print raw client diagnostics.
    process = subprocess.Popen(command, cwd=directory, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=os.name != "nt")
    try:
        stdout, stderr = process.communicate(timeout=seconds)
        combined = (stdout + stderr).decode("utf-8", errors="replace")
        return {"result": "pass" if process.returncode == 0 else "fail", "exitCode": process.returncode,
                "bazel761": b"bazel 7.6.1" in stdout.lower(),
                "httpStatuses": sorted({int(code) for code in re.findall(r"(?:HTTP(?:/[^ ]+)?(?: (?:response|status))?(?: code)?[: ]+|GET returned[: ]+|status code[: ]+)([45][0-9]{2})\b", combined, re.I)}),
                "npmErrorCodes": sorted(set(re.findall(r"npm (?:error|ERR!) code (E[A-Z0-9_]{1,30})\b", combined))),
                "configurationErrorReported": bool(re.search(r"unknown startup option|unrecognized option|no match found for version|no such package", combined, re.I)),
                "timeoutReported": bool(re.search(r"timed? ?out|timeout", combined, re.I)),
                "checksumMismatchReported": bool(re.search(r"checksum.*mismatch|checksum.*does not match", combined, re.I)),
                "seconds": round(time.monotonic() - start, 3)}
    except subprocess.TimeoutExpired:
        kill_tree(process)
        process.stdout.close()
        process.stderr.close()
        return {"result": "fail", "error": "deadline", "seconds": round(time.monotonic() - start, 3)}


def bazel_command(directory: Path) -> list[str]:
    npx = shutil.which("npx")
    if not npx:
        raise RuntimeError("Node.js npx is required")
    prefix = [npx, "--yes", BAZELISK_PACKAGE]
    if os.name == "nt":
        prefix = ["cmd.exe", "/d", "/c", *prefix]
    return [*prefix, "--batch", "--ignore_all_rc_files", f"--output_user_root={directory / 'output'}"]


def repository_inventory(directory: Path) -> dict:
    files = list((directory / "repository-cache" / "content_addressable" / "sha256").glob("*/file"))
    valid = len(files) == 1 and files[0].stat().st_size <= SMALL_ARCHIVE_BYTES
    if valid:
        valid = hashlib.sha256(files[0].read_bytes()).hexdigest() == RULES_SHA256
    return {"result": "pass" if valid else "fail", "cachedArchiveCount": len(files),
            "onlyPinnedSmallArchive": valid}


def bazel_probes(directory: Path) -> dict:
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith(("BAZEL", "USE_BAZEL", "NPM_CONFIG", "NODE_OPTIONS"))
           and not any(word in key.upper() for word in ("TOKEN", "SECRET", "PASSWORD", "CREDENTIAL"))}
    env.update(USE_BAZEL_VERSION=BAZEL_VERSION, BAZELISK_HOME=str(directory / "bazelisk"),
               BAZELISK_SKIP_WRAPPER="true", npm_config_cache=str(directory / "npm"),
               npm_config_userconfig=str(directory / "empty-user.npmrc"),
               npm_config_globalconfig=str(directory / "empty-global.npmrc"),
               npm_config_registry="https://registry.npmjs.org")
    (directory / "empty-user.npmrc").write_text("")
    (directory / "empty-global.npmrc").write_text("")
    (directory / "WORKSPACE").write_text(
        'workspace(name = "download_diagnostic")\n'
        'load("@bazel_tools//tools/build_defs/repo:http.bzl", "http_archive")\n'
        f'http_archive(name="probe", url="{RULES_URL}", sha256="{RULES_SHA256}", '
        'strip_prefix="rules_shell-0.4.1", build_file_content="filegroup(name=\\\"downloaded\\\", srcs=[])\\n")\n')
    (directory / "BUILD").write_text("")
    base = bazel_command(directory)
    bootstrap = command([*base, "version", "--gnu_format"], directory, env, 75)
    if bootstrap["result"] != "pass" or not bootstrap.get("bazel761"):
        return {"bootstrap": bootstrap, "repository": {"result": "skipped"}}
    repository = command([*base, "query", "--enable_bzlmod=false", f"--repository_cache={directory / 'repository-cache'}", "@probe//:downloaded"], directory, env, 60)
    inventory = repository_inventory(directory)
    if inventory["result"] != "pass":
        repository["result"] = "fail"
    return {"bootstrap": bootstrap, "repository": repository, "repositoryInventory": inventory, "bazeliskPackage": BAZELISK_PACKAGE,
            "bazelVersion": BAZEL_VERSION, "repositorySha256": RULES_SHA256,
            "scope": "actual bootstrap and checksum-enforced http_archive query; no build"}


def host_bazel_url() -> str:
    key = (platform.system(), platform.machine().lower())
    names = {("Windows", "amd64"): "windows-x86_64.exe", ("Linux", "x86_64"): "linux-x86_64",
             ("Linux", "aarch64"): "linux-arm64", ("Darwin", "arm64"): "darwin-arm64"}
    if key not in names:
        raise ValueError("Unsupported diagnostic runner")
    return f"https://github.com/bazelbuild/bazel/releases/download/{BAZEL_VERSION}/bazel-{BAZEL_VERSION}-{names[key]}"


def write_report(path: Path, report: dict) -> None:
    report["investigatedRelease"] = INVESTIGATION
    report["diagnosticRun"] = {
        key: os.environ[name] for key, name, pattern in (
            ("headSha", "GITHUB_SHA", r"[0-9a-f]{40}"),
            ("runId", "GITHUB_RUN_ID", r"[0-9]{1,20}"),
            ("runAttempt", "GITHUB_RUN_ATTEMPT", r"[0-9]{1,6}"),
        ) if re.fullmatch(pattern, os.environ.get(name, ""))
    }
    path.write_text(json.dumps(report, indent=2) + "\n")


def run_round(report_path: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="litert-download-round-") as temporary:
        directory = Path(temporary)
        report = {"startedAtUtc": datetime.now(timezone.utc).isoformat(), "upstreamCommit": UPSTREAM, "platform": platform.system(), "arch": platform.machine(), "screens": {}}
        write_report(report_path, report)
        owner_path = directory / "owner.json"
        owner_status = command([sys.executable, str(Path(__file__).resolve()), "--owner-report", str(owner_path)], ROOT, dict(os.environ), 45)
        report["ownerSmallArchive"] = json.loads(owner_path.read_text()) if owner_path.exists() else owner_status
        write_report(report_path, report)
        report["actualBazel"] = bazel_probes(directory)
        write_report(report_path, report)
        samples = {**URLS, "bazel_binary": host_bazel_url()}
        with ThreadPoolExecutor(max_workers=4) as pool:
            for name, result in zip(samples, pool.map(screen, samples.values())):
                report["screens"][name] = result
                write_report(report_path, report)


def round_passed(report: dict) -> bool:
    screens = report.get("screens", {})
    bazel = report.get("actualBazel", {})
    return (
        set(screens) == {*URLS, "bazel_binary"}
        and all(item.get("result") == "pass" for item in screens.values())
        and report.get("ownerSmallArchive", {}).get("result") == "pass"
        and bazel.get("bootstrap", {}).get("result") == "pass"
        and bazel.get("bootstrap", {}).get("bazel761") is True
        and bazel.get("repository", {}).get("result") == "pass"
        and bazel.get("repositoryInventory", {}).get("onlyPinnedSmallArchive") is True
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--round-report", type=Path)
    mode.add_argument("--owner-report", type=Path)
    args = parser.parse_args()
    if args.owner_report:
        write_report(args.owner_report, owner_download(args.owner_report.parent))
        return 0
    if args.round_report:
        run_round(args.round_report)
        return 0
    output = ROOT / "diagnostic-results"
    output.mkdir(exist_ok=True)
    start = time.monotonic()
    summary = {"rounds": [], "intervalSeconds": INTERVAL_SECONDS, "roundDeadlineSeconds": ROUND_SECONDS,
               "scope": "runner acquisition screening; not publication approval or release qualification"}
    for index in range(ROUNDS):
        time.sleep(max(0, start + index * INTERVAL_SECONDS - time.monotonic()))
        path = output / f"round-{index + 1}.json"
        path.unlink(missing_ok=True)
        result = command([sys.executable, str(Path(__file__).resolve()), "--round-report", str(path)], ROOT, dict(os.environ), ROUND_SECONDS)
        complete = result["result"] == "pass" and path.exists() and round_passed(json.loads(path.read_text()))
        summary["rounds"].append({"round": index + 1, **result, "allAcquisitionsPassed": complete})
        write_report(output / "summary.json", summary)
    print("Diagnostic sampling finished; inspect sanitized reports. No recovery or release claim.")
    return 0 if all(item["allAcquisitionsPassed"] for item in summary["rounds"]) else 1


if __name__ == "__main__":
    # No traceback: arbitrary exception strings can contain redirect credentials.
    try:
        raise SystemExit(main())
    except Exception:
        print("Diagnostic failed; raw exception suppressed.", file=sys.stderr)
        raise SystemExit(1)
