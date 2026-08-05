#!/usr/bin/env python3
from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

import runtime_dependency_utils
from litert_lm_symbols import ANDROID_OPENCL_SAMPLER_SYMBOLS
from validate_runtime_dependencies import validate_elf_dependencies


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
                validate_elf_dependencies(root)

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

            self.assertEqual(validate_elf_dependencies(root), 1)


if __name__ == "__main__":
    unittest.main()
