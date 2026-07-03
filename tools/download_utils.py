from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from typing import Callable
from typing import TypeVar

DEFAULT_ATTEMPTS = 3
DEFAULT_CHUNK_SIZE = 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 60
T = TypeVar("T")


def fetch_json(
    url: str,
    *,
    headers: dict[str, str],
    attempts: int = DEFAULT_ATTEMPTS,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    return _with_retries(
        lambda: _fetch_json_once(url, headers, timeout_seconds),
        description=f"fetch {url}",
        attempts=attempts,
    )


def download_to_path(
    url: str,
    path: Path,
    *,
    headers: dict[str, str],
    label: str | None = None,
    attempts: int = DEFAULT_ATTEMPTS,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f"{path.name}.part")
    description = label or url

    def attempt_download() -> None:
        partial.unlink(missing_ok=True)
        request = urllib.request.Request(url, headers=headers)
        with (
            urllib.request.urlopen(request, timeout=timeout_seconds) as response,
            partial.open("wb") as file,
        ):
            while True:
                chunk = response.read(DEFAULT_CHUNK_SIZE)
                if not chunk:
                    break
                file.write(chunk)
        partial.replace(path)

    try:
        _with_retries(
            attempt_download,
            description=f"download {description}",
            attempts=attempts,
        )
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def _fetch_json_once(
    url: str,
    headers: dict[str, str],
    timeout_seconds: int,
) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        data = json.load(response)
    if not isinstance(data, dict):
        raise RuntimeError(f"Expected JSON object from {url}")
    return data


def _with_retries(
    operation: Callable[[], T],
    *,
    description: str,
    attempts: int,
) -> T:
    if attempts < 1:
        raise ValueError("attempts must be at least 1")

    last_error: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            if attempts > 1:
                print(
                    f"{description} (attempt {attempt}/{attempts})",
                    file=sys.stderr,
                    flush=True,
                )
            return operation()
        except (TimeoutError, urllib.error.URLError, OSError) as error:
            last_error = error
            if attempt == attempts:
                break
            wait_seconds = min(2 ** (attempt - 1), 10)
            print(
                f"{description} failed: {error}; retrying in {wait_seconds}s",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(wait_seconds)

    raise RuntimeError(f"Failed to {description} after {attempts} attempts") from last_error
