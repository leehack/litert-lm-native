#!/usr/bin/env python3
"""Checks that a built Android libLiteRtLm.so can destroy its WebGPU environment.

LiteRT's GpuEnvironment::Initialize must record the environment options, which
carry the WebGPU delegate's destroy callback, before it tries to load OpenCL.
In the affected LiteRT commits an OpenCL load failure returns first, the
callback is lost, and deleting an engine never releases its graphics memory.
The check reads the order of the two calls from the disassembly of the built
library, so it holds whichever way the ordering got there: the patch in
native/bridge or an upstream LiteRT that already has it.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

INITIALIZE_SYMBOL = (
    "_ZN6litert8internal14GpuEnvironment10Initialize"
    "ERK25LiteRtEnvironmentOptionsT"
)
RECORD_OPTIONS_SYMBOL = (
    "_ZN6litert8internal27CreateGpuEnvironmentOptions"
    "ERK25LiteRtEnvironmentOptionsT"
)
# LiteRT 9c8ae4e0fc moved the OpenCL setup, and with it the LoadOpenCL call,
# into GpuEnvironment::InitializeOpenCl.
OPENCL_SETUP_SYMBOLS = frozenset(
    {
        "_ZN6tflite3gpu2cl10LoadOpenCLEv",
        "_ZN6litert8internal14GpuEnvironment16InitializeOpenClEv",
    }
)

_FUNCTION_HEADER = re.compile(r"^[0-9a-f]+ <([^>]+)>:\s*$")
# arm64 `bl`, x86_64 `callq` (`call` in Intel syntax); the target may be a
# PLT stub.
_CALL = re.compile(
    r"^\s*[0-9a-f]+:\s+(?:bl|callq?)\s+0x[0-9a-f]+\s+<([^>+@]+)(?:@plt)?>\s*$"
)


def check_initialize_disassembly(disassembly: str) -> None:
    """Raises unless the options are recorded before OpenCL is set up.

    `disassembly` is `llvm-objdump -d --no-show-raw-insn
    --disassemble-symbols=INITIALIZE_SYMBOL` output. A missing function or a
    missing call is an error, not a pass: the order cannot be shown.
    """
    calls: list[str] = []
    found = in_function = False
    for line in disassembly.splitlines():
        header = _FUNCTION_HEADER.match(line)
        if header:
            in_function = header.group(1) == INITIALIZE_SYMBOL
            found = found or in_function
            continue
        if not in_function:
            continue
        call = _CALL.match(line)
        if call:
            calls.append(call.group(1))
    if not found:
        raise RuntimeError(
            "GpuEnvironment::Initialize was not found in the disassembly; "
            "the WebGPU teardown ordering cannot be checked"
        )
    record = next(
        (index for index, name in enumerate(calls) if name == RECORD_OPTIONS_SYMBOL),
        None,
    )
    opencl = next(
        (index for index, name in enumerate(calls) if name in OPENCL_SETUP_SYMBOLS),
        None,
    )
    if record is None or opencl is None:
        missing = "CreateGpuEnvironmentOptions" if record is None else "OpenCL setup"
        raise RuntimeError(
            f"GpuEnvironment::Initialize has no call to {missing}; "
            "the WebGPU teardown ordering cannot be checked"
        )
    if opencl < record:
        raise RuntimeError(
            "GpuEnvironment::Initialize sets up OpenCL before it records the "
            "environment options, so an OpenCL load failure drops the WebGPU "
            "destroy callback and engine deletes leak graphics memory. Add the "
            "pinned LiteRT commit to LITERT_REFS_WITHOUT_GPU_TEARDOWN_ORDERING "
            "in tools/build_upstream_runtime.py after confirming that "
            "native/bridge/litert_gpu_environment_destroy_callback.patch applies."
        )


def find_ndk_llvm_objdump(ndk_home: str | None) -> Path:
    if not ndk_home:
        raise RuntimeError(
            "ANDROID_NDK_HOME is required to check the WebGPU teardown ordering"
        )
    candidates = sorted(
        Path(ndk_home).glob("toolchains/llvm/prebuilt/*/bin/llvm-objdump*")
    )
    if not candidates:
        raise RuntimeError(f"No llvm-objdump under {ndk_home}")
    return candidates[0]


def validate_library(library: Path, objdump: Path) -> None:
    result = subprocess.run(
        [
            str(objdump),
            "-d",
            "--no-show-raw-insn",
            f"--disassemble-symbols={INITIALIZE_SYMBOL}",
            str(library),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        check_initialize_disassembly(result.stdout)
    except RuntimeError as error:
        raise RuntimeError(f"{library}: {error}") from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("library", type=Path, help="Android libLiteRtLm.so")
    parser.add_argument(
        "--objdump",
        type=Path,
        help="llvm-objdump to use; defaults to the one in ANDROID_NDK_HOME",
    )
    args = parser.parse_args()
    try:
        objdump = args.objdump or find_ndk_llvm_objdump(
            os.environ.get("ANDROID_NDK_HOME")
        )
        validate_library(args.library, objdump)
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1
    print(
        f"{args.library}: GpuEnvironment::Initialize records the environment "
        "options before OpenCL setup"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
