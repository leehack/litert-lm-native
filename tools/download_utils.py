from __future__ import annotations

import hashlib
import errno
import http.client
import json
import math
import sys
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, TypeVar

DEFAULT_ATTEMPTS = 3
DEFAULT_CHUNK_SIZE = 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 60
MAX_RETRY_DELAY_SECONDS = 30
RETRYABLE_HTTP_STATUSES = {429, 500, 502, 503, 504}
RETRYABLE_NETWORK_ERRNOS = {
    errno.ENETUNREACH,
    errno.EHOSTUNREACH,
    errno.ECONNRESET,
    errno.ETIMEDOUT,
    errno.ECONNREFUSED,
    errno.EPIPE,
    errno.ECONNABORTED,
}
T = TypeVar("T")


class DownloadError(RuntimeError):
    """Safe asset-level diagnostic with no remote URL or exception chain."""


class ChecksumMismatch(DownloadError):
    pass


def fetch_json(
    url: str,
    *,
    headers: dict[str, str],
    attempts: int = DEFAULT_ATTEMPTS,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    return _with_retries(
        lambda: _fetch_json_once(url, headers, timeout_seconds),
        description="fetch JSON document",
        attempts=attempts,
    )


def _remaining(deadline: float | None, timeout: float) -> float:
    if deadline is None:
        return timeout
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("download deadline exhausted")
    return min(timeout, remaining)


def download_to_path(
    url: str,
    path: Path,
    *,
    headers: dict[str, str],
    label: str | None = None,
    attempts: int = DEFAULT_ATTEMPTS,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    deadline_seconds: float | None = None,
    expected_sha256: str | None = None,
) -> None:
    options = dict(
        headers=headers,
        label=label,
        attempts=attempts,
        timeout_seconds=timeout_seconds,
        deadline_seconds=deadline_seconds,
        expected_sha256=expected_sha256,
    )
    if deadline_seconds is None:
        _download_to_path(url, path, **options)
        return
    if not math.isfinite(deadline_seconds) or deadline_seconds <= 0:
        raise ValueError("deadline_seconds must be positive and finite")
    started = time.monotonic()
    path.with_name(f"{path.name}.part").unlink(missing_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    # A socket timeout cannot bound DNS, redirects or trickling HTTP headers.
    # Isolate deadline-enabled transfers; subprocess.run kills and waits on
    # timeout. Only this parent can promote verified bytes to the destination.
    with tempfile.TemporaryDirectory(prefix=".download-", dir=path.parent) as directory:
        staged = Path(directory) / path.name
        request = dict(url=url, path=str(staged), **options)
        try:
            result = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--download-worker"],
                input=json.dumps(request),
                text=True,
                capture_output=True,
                timeout=max(0.001, deadline_seconds - (time.monotonic() - started)),
            )
        except subprocess.TimeoutExpired:
            raise DownloadError(
                f"Failed to download {label or path.name}: deadline exhausted"
            ) from None
        if time.monotonic() - started >= deadline_seconds:
            raise DownloadError(
                f"Failed to download {label or path.name}: deadline exhausted"
            )
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
        if result.returncode != 0:
            try:
                message = json.loads(result.stdout)["error"]
            except (json.JSONDecodeError, KeyError, TypeError):
                message = f"Failed to download {label or path.name}: worker failed"
            raise DownloadError(message)
        if not staged.is_file() or staged.is_symlink():
            raise DownloadError(
                f"Failed to download {label or path.name}: invalid staged asset"
            )
        staged.replace(path)


def _download_to_path(
    url: str,
    path: Path,
    *,
    headers: dict[str, str],
    label: str | None = None,
    attempts: int = DEFAULT_ATTEMPTS,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    deadline_seconds: float | None = None,
    expected_sha256: str | None = None,
) -> None:
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive and finite")
    if deadline_seconds is not None and (
        not math.isfinite(deadline_seconds) or deadline_seconds <= 0
    ):
        raise ValueError("deadline_seconds must be positive and finite")
    deadline = None if deadline_seconds is None else time.monotonic() + deadline_seconds
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f"{path.name}.part")
    description = label or path.name

    def attempt_download() -> None:
        partial.unlink(missing_ok=True)
        request = urllib.request.Request(url, headers=headers)
        with (
            urllib.request.urlopen(
                request, timeout=_remaining(deadline, timeout_seconds)
            ) as response,
            partial.open("wb") as file,
        ):
            digest = hashlib.sha256()
            received = 0
            while True:
                timeout = _remaining(deadline, timeout_seconds)
                # urllib's HTTPResponse wraps a buffered socket. Refresh its
                # timeout per read so streaming progress cannot reset the total
                # budget. read1 returns available bytes instead of waiting to
                # fill a chunk from a continuously trickling peer.
                raw = getattr(getattr(response, "fp", None), "raw", None)
                sock = getattr(raw, "_sock", None)
                if sock is not None:
                    sock.settimeout(timeout)
                reader = getattr(response, "read1", response.read)
                chunk = reader(DEFAULT_CHUNK_SIZE)
                if not chunk:
                    break
                file.write(chunk)
                digest.update(chunk)
                received += len(chunk)
            length = (
                response.headers.get("Content-Length")
                if hasattr(response, "headers")
                else None
            )
            if length is not None and received != int(length):
                raise http.client.IncompleteRead(b"", max(0, int(length) - received))
        _remaining(deadline, timeout_seconds)
        if expected_sha256 is not None and digest.hexdigest() != expected_sha256:
            raise ChecksumMismatch(f"Checksum mismatch for {description}")
        partial.replace(path)

    try:
        _with_retries(
            attempt_download,
            description=f"download {description}",
            attempts=attempts,
            deadline=deadline,
        )
    finally:
        partial.unlink(missing_ok=True)


def _fetch_json_once(
    url: str,
    headers: dict[str, str],
    timeout_seconds: int,
) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        data = json.load(response)
    if not isinstance(data, dict):
        raise RuntimeError("Expected a JSON object")
    return data


def _retry_delay(error: BaseException, attempt: int) -> float:
    fallback = min(2 ** (attempt - 1), 10)
    if not isinstance(error, urllib.error.HTTPError):
        return fallback
    value = error.headers.get("Retry-After") if error.headers is not None else None
    if not isinstance(value, str) or not value or len(value) > 128:
        return fallback
    try:
        if value.isascii() and value.isdecimal():
            delay = int(value)
        else:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                return fallback
            delay = date.timestamp() - time.time()
        if not math.isfinite(delay) or delay < 0:
            return fallback
        return min(delay, MAX_RETRY_DELAY_SECONDS)
    except (ValueError, TypeError, OverflowError):
        return fallback


def _with_retries(
    operation: Callable[[], T],
    *,
    description: str,
    attempts: int,
    deadline: float | None = None,
) -> T:
    if type(attempts) is not int or not 1 <= attempts <= 10:
        raise ValueError("attempts must be between 1 and 10")
    reason = "attempt budget exhausted"
    for attempt in range(1, attempts + 1):
        if deadline is not None and time.monotonic() >= deadline:
            reason = "deadline exhausted"
            break
        try:
            return operation()
        except urllib.error.HTTPError as error:
            status = error.code
            if status not in RETRYABLE_HTTP_STATUSES:
                error.close()
                raise DownloadError(f"Failed to {description}: HTTP {status}") from None
            reason = f"HTTP {status}"
            delay = _retry_delay(error, attempt)
            error.close()
        except (
            TimeoutError,
            ConnectionError,
            urllib.error.URLError,
            http.client.HTTPException,
        ):
            reason = "transport failure"
            delay = min(2 ** (attempt - 1), 10)
        except OSError as error:
            if error.errno not in RETRYABLE_NETWORK_ERRNOS:
                raise
            reason = "transport failure"
            delay = min(2 ** (attempt - 1), 10)
        if attempt == attempts:
            break
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= delay:
                reason = "deadline exhausted"
                break
        print(
            f"{description}: {reason}; retrying in {delay:g}s (attempt {attempt + 1}/{attempts})",
            file=sys.stderr,
            flush=True,
        )
        time.sleep(delay)
    raise DownloadError(
        f"Failed to {description}: {reason}; retry budget exhausted"
    ) from None


def _worker_main() -> int:
    label = "asset"
    try:
        request = json.load(sys.stdin)
        request["path"] = Path(request["path"])
        label = request.get("label") or request["path"].name
        _download_to_path(**request)
    except DownloadError as error:
        print(json.dumps({"error": str(error)}))
        return 1
    except Exception:
        # Transport/library/file errors can embed redirect URLs. The parent
        # receives a bounded diagnostic, never the raw exception or traceback.
        print(
            json.dumps(
                {"error": f"Failed to download {label}: worker or local I/O failure"}
            )
        )
        return 1
    return 0


if __name__ == "__main__":
    if sys.argv[1:] != ["--download-worker"]:
        raise SystemExit("internal download worker only")
    raise SystemExit(_worker_main())
