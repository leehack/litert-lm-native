#!/usr/bin/env python3
"""Run the production v0.19 push source against exact upstream stage headers."""
from __future__ import annotations

import argparse
from pathlib import Path
import shlex
import subprocess

from qualify_asr_untimed_overlap import REPO, compiler_command, abseil_flags


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    protobuf_cflags, protobuf_libs = (
        shlex.split(subprocess.check_output(["pkg-config", flag, "protobuf"], text=True))
        for flag in ("--cflags", "--libs")
    )
    _, libs = abseil_flags()
    output = args.work_dir / "omni_input_test"
    subprocess.run([
        *compiler_command(args.source_root, args.work_dir), *protobuf_cflags,
        "-I", str(REPO / "native"),
        str(REPO / "native/bridge/litert_lm_asr_omni_input_source.cc"),
        str(REPO / "native/bridge/litert_lm_asr_omni_input_source_test.cc"),
        *libs, *protobuf_libs, "-o", str(output),
    ], check=True, timeout=120)
    subprocess.run([str(output.resolve())], check=True, timeout=30)


if __name__ == "__main__":
    main()
