#!/usr/bin/env python3
"""Check native stderr during packaged macOS Metal engine creation."""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

from litert_lm_c_api import CApi
from validate_artifacts import sha256_file

CREATE_START = b"BEGIN_ENGINE_CREATE\n"
CREATE_END = b"END_ENGINE_CREATE\n"
INFO_LEVEL = 0
QUIET_LEVEL = 1000


def create_engine(library: Path, model: Path, level: int) -> None:
    api = CApi(library)
    api.set_min_log_level(level)
    with tempfile.TemporaryDirectory(prefix="litert-lm-gpu-logging-") as cache:
        settings = api.engine_settings_create(str(model), "gpu")
        engine = None
        try:
            api.engine_settings_set_cache_dir(settings, cache)
            os.write(2, CREATE_START)
            engine = api.engine_create(settings)
            os.write(2, CREATE_END)
        finally:
            if engine:
                api.library.litert_lm_engine_delete(engine)
            api.library.litert_lm_engine_settings_delete(settings)


def capture_create(library: Path, model: Path, level: int) -> list[bytes]:
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--library", str(library),
         "--model", str(model), "--worker", str(level)],
        capture_output=True, timeout=120,
        env={**os.environ, "DYLD_LIBRARY_PATH": str(library.parent)},
    )
    _, start, following = result.stderr.partition(CREATE_START)
    create_stderr, end, _ = following.partition(CREATE_END)
    if result.returncode or not start or not end:
        raise RuntimeError(f"GPU engine create probe failed at level {level} "
                           f"(exit {result.returncode}):\n{result.stderr.decode(errors='replace')}")
    return create_stderr.splitlines()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--worker", type=int, choices=(INFO_LEVEL, QUIET_LEVEL), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if (platform.system(), platform.machine()) != ("Darwin", "arm64"):
        parser.error("this smoke qualifies macOS arm64 Metal")
    library, model = args.library.resolve(), args.model.resolve()
    if args.worker is not None:
        create_engine(library, model, args.worker)
        return 0

    info = capture_create(library, model, INFO_LEVEL)
    quiet = capture_create(library, model, QUIET_LEVEL)
    info_lines = [line for line in info if line.startswith(b"I0000 ")]
    print(json.dumps({
        "host": platform.platform(),
        "library_sha256": sha256_file(library),
        "model_sha256": sha256_file(model),
        "stderr_line_counts": {INFO_LEVEL: len(info), QUIET_LEVEL: len(quiet)},
        "info_line_counts": {INFO_LEVEL: len(info_lines),
                             QUIET_LEVEL: sum(line.startswith(b"I0000 ") for line in quiet)},
    }))
    if (not any(b"Selected adapter:" in line and b"backend=Metal" in line for line in info_lines)
            or not any(b"delegate_webgpu.cc:" in line for line in info_lines)):
        raise RuntimeError("Info control did not log Metal adapter selection and WebGPU delegate creation")
    if quiet:
        detail = b"\n".join(quiet).decode(errors="replace")
        raise RuntimeError(f"GPU engine create wrote to stderr at level {QUIET_LEVEL}:\n{detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
