#!/usr/bin/env python3
from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

import runtime_dependency_utils


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


if __name__ == "__main__":
    unittest.main()
