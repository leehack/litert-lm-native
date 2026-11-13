#!/usr/bin/env python3
from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import runtime_dependency_utils
from litert_lm_symbols import (
    ANDROID_OPENCL_SAMPLER_SYMBOLS,
    ANDROID_WEBGPU_SAMPLER_SYMBOLS,
    APPLE_METAL_SAMPLER_SYMBOLS,
    android_static_gpu_sampler_symbols,
)
from validate_runtime_dependencies import (
    newest_glibc_requirement,
    validate_elf_dependencies,
    validate_macho_dependencies,
)


def write_elf_with_flags(path: Path, flags: int | None) -> None:
    data = bytearray(160)
    data[:16] = b"\x7fELF\x02\x01\x01" + bytes(9)
    struct.pack_into(
        "<HHIQQQIHHHHHH",
        data,
        16,
        3,
        183,
        1,
        0,
        64,
        0,
        0,
        64,
        56,
        1,
        0,
        0,
        0,
    )
    struct.pack_into("<IIQQQQQQ", data, 64, 2, 0, 120, 0, 0, 32, 32, 8)
    if flags is None:
        struct.pack_into("<qQ", data, 120, 0, 0)
    else:
        struct.pack_into(
            "<qQ", data, 120, runtime_dependency_utils.DT_FLAGS_1, flags
        )
        struct.pack_into("<qQ", data, 136, 0, 0)
    path.write_bytes(data)


def write_elf_with_exports(path: Path, symbols: list[str]) -> None:
    string_table = bytearray(b"\0")
    name_offsets: list[int] = []
    for symbol in symbols:
        name_offsets.append(len(string_table))
        string_table.extend(symbol.encode("utf-8") + b"\0")

    section_header_offset = 64
    section_header_size = 64
    section_header_count = 3
    string_offset = section_header_offset + section_header_size * section_header_count
    symbol_offset = (string_offset + len(string_table) + 7) & ~7
    symbol_entry_size = 24
    symbol_table_size = symbol_entry_size * (len(symbols) + 1)
    data = bytearray(symbol_offset + symbol_table_size)
    data[:16] = b"\x7fELF\x02\x01\x01" + bytes(9)
    struct.pack_into(
        "<16sHHIQQQIHHHHHH",
        data,
        0,
        bytes(data[:16]),
        3,
        183,
        1,
        0,
        0,
        section_header_offset,
        0,
        64,
        0,
        0,
        section_header_size,
        section_header_count,
        0,
    )
    struct.pack_into(
        "<IIQQQQIIQQ",
        data,
        section_header_offset + section_header_size,
        0,
        3,
        0,
        0,
        string_offset,
        len(string_table),
        0,
        0,
        1,
        0,
    )
    struct.pack_into(
        "<IIQQQQIIQQ",
        data,
        section_header_offset + section_header_size * 2,
        0,
        11,
        0,
        0,
        symbol_offset,
        symbol_table_size,
        1,
        1,
        8,
        symbol_entry_size,
    )
    data[string_offset : string_offset + len(string_table)] = string_table
    for index, name_offset in enumerate(name_offsets, start=1):
        struct.pack_into(
            "<IBBHQQ",
            data,
            symbol_offset + index * symbol_entry_size,
            name_offset,
            (1 << 4) | 2,
            0,
            1,
            0,
            0,
        )
    path.write_bytes(data)


class RuntimeDependencyUtilsTest(unittest.TestCase):
    def test_newest_glibc_requirement_compares_numerically(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            library = Path(temp) / "lib.so"
            library.write_bytes(b"\0GLIBC_2.9\0GLIBC_2.39\0GLIBC_2.2.5\0")
            self.assertEqual(newest_glibc_requirement(library), (2, 39))
            library.write_bytes(b"\0")
            self.assertIsNone(newest_glibc_requirement(library))

    def test_linux_library_above_glibc_floor_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            library = root / "bin" / "linux" / "x64" / "libLiteRtLm.so"
            library.parent.mkdir(parents=True)
            write_elf_with_flags(library, None)
            library.write_bytes(library.read_bytes() + b"\0GLIBC_2.43\0")
            with self.assertRaisesRegex(SystemExit, "requires glibc 2.43"):
                validate_elf_dependencies(root, "v0.18.0")
            library.write_bytes(library.read_bytes().replace(b"GLIBC_2.43", b"GLIBC_2.39"))
            self.assertEqual(validate_elf_dependencies(root, "v0.18.0"), 1)

    def test_elf_has_global_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            library = Path(temp) / "libLiteRtLm.so"
            write_elf_with_flags(library, runtime_dependency_utils.DF_1_GLOBAL)
            self.assertTrue(runtime_dependency_utils.elf_has_global_flag(library))

    def test_elf_without_global_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            library = Path(temp) / "libLiteRtLm.so"
            write_elf_with_flags(library, 0)
            self.assertFalse(runtime_dependency_utils.elf_has_global_flag(library))

    def test_non_elf_does_not_have_global_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            library = Path(temp) / "not-elf.so"
            library.write_bytes(b"not an ELF")
            self.assertFalse(runtime_dependency_utils.elf_has_global_flag(library))

    def test_elf_exported_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            library = Path(temp) / "libSampler.so"
            write_elf_with_exports(library, ["Sampler_Create", "Sampler_Destroy"])

            self.assertEqual(
                runtime_dependency_utils.elf_exported_symbols(library),
                {"Sampler_Create", "Sampler_Destroy"},
            )

    def test_non_elf_has_no_exported_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            library = Path(temp) / "not-elf.so"
            library.write_bytes(b"not an ELF")

            self.assertEqual(
                runtime_dependency_utils.elf_exported_symbols(library),
                set(),
            )

    def test_android_opencl_sampler_requires_complete_plugin_api(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            library = (
                root
                / "bin"
                / "android"
                / "arm64"
                / "libLiteRtTopKOpenClSampler.so"
            )
            library.parent.mkdir(parents=True)
            write_elf_with_exports(library, ANDROID_OPENCL_SAMPLER_SYMBOLS[:-1])

            with self.assertRaisesRegex(
                SystemExit,
                "LiteRtTopKOpenClSampler_SetInferenceFuncAndInputTensors",
            ):
                validate_elf_dependencies(root, "v0.18.0")

    def test_android_opencl_sampler_accepts_complete_plugin_api(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            library = (
                root
                / "bin"
                / "android"
                / "x64"
                / "libLiteRtTopKOpenClSampler.so"
            )
            library.parent.mkdir(parents=True)
            write_elf_with_exports(library, ANDROID_OPENCL_SAMPLER_SYMBOLS)

            self.assertEqual(validate_elf_dependencies(root, "v0.18.0"), 1)

    def test_android_v019_runtime_requires_both_linked_gpu_samplers(self) -> None:
        # sampler_factory.cc resolves the same seven functions for each family.
        self.assertEqual(
            ANDROID_WEBGPU_SAMPLER_SYMBOLS,
            [symbol.replace("OpenCl", "WebGpu") for symbol in ANDROID_OPENCL_SAMPLER_SYMBOLS],
        )
        self.assertEqual(android_static_gpu_sampler_symbols("v0.18.1"), [])
        both = ANDROID_OPENCL_SAMPLER_SYMBOLS + ANDROID_WEBGPU_SAMPLER_SYMBOLS
        for tag in ("v0.19.0", "v0.19.1", "v0.20.0"):
            self.assertEqual(android_static_gpu_sampler_symbols(tag), both)
        # The published v0.19.1-4 shape: OpenCL functions plus the WebGPU
        # function pointers sampler_factory.cc always defines.
        published = ANDROID_OPENCL_SAMPLER_SYMBOLS + [
            f"{symbol}_Static" for symbol in ANDROID_WEBGPU_SAMPLER_SYMBOLS
        ]
        for arch in ("arm64", "x64"):
            with self.subTest(arch=arch), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                library = root / "bin" / "android" / arch / "libLiteRtLm.so"
                library.parent.mkdir(parents=True)
                write_elf_with_exports(library, published)
                with self.assertRaises(SystemExit) as raised:
                    validate_elf_dependencies(root, "v0.19.1")
                message = str(raised.exception)
                for symbol in ANDROID_WEBGPU_SAMPLER_SYMBOLS:
                    self.assertRegex(message, rf"{symbol}(,|$|\n)")
                self.assertNotIn("LiteRtTopKOpenClSampler", message)
                write_elf_with_exports(library, both)
                with self.assertRaises(SystemExit) as raised:
                    validate_elf_dependencies(root, "v0.19.1")
                self.assertNotIn("Sampler", str(raised.exception))
                write_elf_with_exports(library, ANDROID_WEBGPU_SAMPLER_SYMBOLS)
                with self.assertRaisesRegex(SystemExit, "LiteRtTopKOpenClSampler_Create"):
                    validate_elf_dependencies(root, "v0.19.1")
                write_elf_with_exports(library, published)
                with self.assertRaises(SystemExit) as raised:
                    validate_elf_dependencies(root, "v0.18.1")
                self.assertNotIn("Sampler", str(raised.exception))

    def test_ios_metal_sampler_requires_complete_plugin_api(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            library = (
                root
                / "bin"
                / "ios"
                / "arm64"
                / "LiteRtTopKMetalSampler.framework"
                / "LiteRtTopKMetalSampler"
            )
            library.parent.mkdir(parents=True)
            library.write_bytes(b"macho")
            with patch("validate_runtime_dependencies.shutil.which", return_value="nm"), \
                 patch("validate_runtime_dependencies.validate_framework_metadata"):
                with patch(
                    "validate_runtime_dependencies.macho_needed_libraries",
                    return_value=[],
                ):
                    with patch(
                        "validate_runtime_dependencies.unresolved_provider_symbols",
                        return_value={},
                    ):
                        with patch(
                            "validate_runtime_dependencies.macho_exported_symbols",
                            return_value=set(APPLE_METAL_SAMPLER_SYMBOLS[:-1]),
                        ):
                            with self.assertRaisesRegex(
                                SystemExit,
                                "LiteRtTopKMetalSampler_SetInferenceFuncAndInputTensors",
                            ):
                                validate_macho_dependencies(root)


if __name__ == "__main__":
    unittest.main()
