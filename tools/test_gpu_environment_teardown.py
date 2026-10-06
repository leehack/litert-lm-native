#!/usr/bin/env python3
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import build_upstream_runtime
import gpu_environment_teardown as teardown

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "gpu_environment_initialize"

# llvm-objdump output for a library that does not define the function.
NO_SYMBOL = "\nlibwebgpu_dawn.so:\tfile format elf64-littleaarch64\n"

# The shape LiteRT 9c8ae4e0fc gives the function: the OpenCL setup, with its
# LoadOpenCL call, sits behind GpuEnvironment::InitializeOpenCl. Written by
# hand from that source; no library with this shape has been built here.
REORDERED_UPSTREAM = """
libLiteRtLm.so:\tfile format elf64-littleaarch64

Disassembly of section .text:

0000000000001000 <{initialize}>:
    1000:      \tstp\tx29, x30, [sp, #-0x30]!
    1004:      \tbl\t0x2000 <{record}@plt>
    1008:      \tbl\t0x3000 <_ZN6litert8internal14GpuEnvironment16InitializeOpenClEv>
    100c:      \tret
""".format(
    initialize=teardown.INITIALIZE_SYMBOL, record=teardown.RECORD_OPTIONS_SYMBOL
)


def fixture(name: str) -> str:
    return (FIXTURES / f"{name}.txt").read_text(encoding="utf-8")


class GpuEnvironmentTeardownTest(unittest.TestCase):
    def test_published_v017_libraries_set_up_opencl_first(self) -> None:
        for arch in ("arm64", "x64"):
            with self.subTest(arch=arch):
                with self.assertRaisesRegex(RuntimeError, "sets up OpenCL before"):
                    teardown.check_initialize_disassembly(
                        fixture(f"android_{arch}_v0.17.0-7")
                    )

    def test_patched_libraries_record_the_options_first(self) -> None:
        for arch in ("arm64", "x64"):
            with self.subTest(arch=arch):
                teardown.check_initialize_disassembly(fixture(f"android_{arch}_patched"))

    def test_reordered_upstream_shape_passes_and_its_reverse_fails(self) -> None:
        teardown.check_initialize_disassembly(REORDERED_UPSTREAM)
        lines = REORDERED_UPSTREAM.splitlines()
        lines[7], lines[8] = lines[8], lines[7]
        with self.assertRaisesRegex(RuntimeError, "sets up OpenCL before"):
            teardown.check_initialize_disassembly("\n".join(lines))

    def test_missing_function_or_call_is_an_error(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "was not found"):
            teardown.check_initialize_disassembly(NO_SYMBOL)
        patched = fixture("android_arm64_patched")
        for symbol, missing in (
            (teardown.RECORD_OPTIONS_SYMBOL, "CreateGpuEnvironmentOptions"),
            ("_ZN6tflite3gpu2cl10LoadOpenCLEv", "OpenCL setup"),
        ):
            with self.subTest(missing=missing):
                without = "\n".join(
                    line for line in patched.splitlines() if f"<{symbol}" not in line
                )
                with self.assertRaisesRegex(RuntimeError, f"no call to {missing}"):
                    teardown.check_initialize_disassembly(without)

    def test_calls_outside_the_function_are_ignored(self) -> None:
        other = (
            "\n0000000000000900 <_ZN5other4funcEv>:\n"
            f"     900:      \tbl\t0x2000 <{teardown.RECORD_OPTIONS_SYMBOL}@plt>\n"
        )
        with self.assertRaisesRegex(RuntimeError, "sets up OpenCL before"):
            teardown.check_initialize_disassembly(
                other + fixture("android_arm64_v0.17.0-7")
            )

    def test_objdump_lookup_needs_the_ndk(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "ANDROID_NDK_HOME"):
            teardown.find_ndk_llvm_objdump(None)
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(RuntimeError, "No llvm-objdump"):
                teardown.find_ndk_llvm_objdump(temp)
            tool = Path(temp) / "toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-objdump"
            tool.parent.mkdir(parents=True)
            tool.touch()
            self.assertEqual(teardown.find_ndk_llvm_objdump(temp), tool)

    @unittest.skipIf(os.name == "nt", "the stand-in objdump is a shell script")
    def test_android_build_fails_on_the_old_ordering(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            library = root / "libLiteRtLm.so"
            library.touch()
            tool = root / "ndk/toolchains/llvm/prebuilt/host/bin/llvm-objdump"
            tool.parent.mkdir(parents=True)

            def validate(name: str, platform: str = "android") -> None:
                tool.write_text(f'#!/bin/sh\ncat "{FIXTURES / name}.txt"\n')
                tool.chmod(0o755)
                saved = os.environ.get("ANDROID_NDK_HOME")
                os.environ["ANDROID_NDK_HOME"] = str(root / "ndk")
                try:
                    build_upstream_runtime.validate_android_gpu_environment_teardown(
                        library, platform
                    )
                finally:
                    if saved is None:
                        del os.environ["ANDROID_NDK_HOME"]
                    else:
                        os.environ["ANDROID_NDK_HOME"] = saved

            validate("android_x64_patched")
            with self.assertRaisesRegex(RuntimeError, "libLiteRtLm.so: .*before"):
                validate("android_x64_v0.17.0-7")
            validate("android_x64_v0.17.0-7", platform="linux")


if __name__ == "__main__":
    unittest.main()
