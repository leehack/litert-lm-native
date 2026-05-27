from __future__ import annotations

import re
import struct
from pathlib import Path

ELF_MAGIC = b"\x7fELF"
PT_LOAD = 1
PT_DYNAMIC = 2
DT_NULL = 0
DT_NEEDED = 1
DT_STRTAB = 5
DT_STRSZ = 10

ANDROID_SYSTEM_LIBRARIES = {
    "libandroid.so",
    "libdl.so",
    "libEGL.so",
    "libGLESv3.so",
    "libjnigraphics.so",
    "liblog.so",
    "libm.so",
    "libOpenSLES.so",
    "libz.so",
    "libc.so",
}

LINUX_SYSTEM_PATTERNS = [
    re.compile(r"^ld-linux.*\.so(?:\.\d+)*$"),
    re.compile(r"^libc\.so(?:\.\d+)*$"),
    re.compile(r"^libdl\.so(?:\.\d+)*$"),
    re.compile(r"^libgcc_s\.so(?:\.\d+)*$"),
    re.compile(r"^libm\.so(?:\.\d+)*$"),
    re.compile(r"^libpthread\.so(?:\.\d+)*$"),
    re.compile(r"^librt\.so(?:\.\d+)*$"),
    re.compile(r"^libstdc\+\+\.so(?:\.\d+)*$"),
]


def is_elf(path: Path) -> bool:
    try:
        with path.open("rb") as file:
            return file.read(4) == ELF_MAGIC
    except OSError:
        return False


def elf_needed_libraries(path: Path) -> list[str]:
    data = path.read_bytes()
    if len(data) < 64 or not data.startswith(ELF_MAGIC):
        return []
    if data[4] != 2:
        raise ValueError(f"{path} is not a 64-bit ELF file")
    if data[5] == 1:
        endian = "<"
    elif data[5] == 2:
        endian = ">"
    else:
        raise ValueError(f"{path} has an unknown ELF endianness")

    header = struct.unpack_from(endian + "16sHHIQQQIHHHHHH", data, 0)
    program_header_offset = header[5]
    program_header_size = header[9]
    program_header_count = header[10]
    loads: list[tuple[int, int, int, int]] = []
    dynamic: tuple[int, int] | None = None

    for index in range(program_header_count):
        offset = program_header_offset + index * program_header_size
        fields = struct.unpack_from(endian + "IIQQQQQQ", data, offset)
        segment_type = fields[0]
        segment_offset = fields[2]
        virtual_address = fields[3]
        file_size = fields[5]
        memory_size = fields[6]
        if segment_type == PT_LOAD:
            loads.append((virtual_address, memory_size, segment_offset, file_size))
        elif segment_type == PT_DYNAMIC:
            dynamic = (segment_offset, file_size)

    if dynamic is None:
        return []

    dynamic_offset, dynamic_size = dynamic
    strtab_address: int | None = None
    strtab_size: int | None = None
    needed_offsets: list[int] = []
    for offset in range(dynamic_offset, dynamic_offset + dynamic_size, 16):
        tag, value = struct.unpack_from(endian + "qQ", data, offset)
        if tag == DT_NULL:
            break
        if tag == DT_NEEDED:
            needed_offsets.append(value)
        elif tag == DT_STRTAB:
            strtab_address = value
        elif tag == DT_STRSZ:
            strtab_size = value

    if strtab_address is None:
        return []
    strtab_offset = _virtual_address_to_file_offset(strtab_address, loads)
    if strtab_offset is None:
        raise ValueError(f"{path} has a DT_STRTAB outside loadable segments")

    names: list[str] = []
    max_string_offset = strtab_offset + (strtab_size or 0)
    for needed_offset in needed_offsets:
        start = strtab_offset + needed_offset
        end = data.find(b"\0", start)
        if end < 0:
            raise ValueError(f"{path} has an unterminated DT_NEEDED entry")
        if strtab_size is not None and end > max_string_offset:
            raise ValueError(f"{path} has a DT_NEEDED entry past DT_STRSZ")
        names.append(data[start:end].decode("utf-8"))
    return names


def elf_load_alignments(path: Path) -> list[int]:
    data = path.read_bytes()
    if len(data) < 64 or not data.startswith(ELF_MAGIC):
        return []
    if data[4] != 2:
        raise ValueError(f"{path} is not a 64-bit ELF file")
    endian = "<" if data[5] == 1 else ">"
    header = struct.unpack_from(endian + "16sHHIQQQIHHHHHH", data, 0)
    program_header_offset = header[5]
    program_header_size = header[9]
    program_header_count = header[10]

    alignments: list[int] = []
    for index in range(program_header_count):
        offset = program_header_offset + index * program_header_size
        fields = struct.unpack_from(endian + "IIQQQQQQ", data, offset)
        if fields[0] == PT_LOAD:
            alignments.append(fields[7])
    return alignments


def is_system_needed(platform: str, library_name: str) -> bool:
    if platform == "android":
        return library_name in ANDROID_SYSTEM_LIBRARIES
    if platform == "linux":
        return any(pattern.match(library_name) for pattern in LINUX_SYSTEM_PATTERNS)
    return False


def _virtual_address_to_file_offset(
    address: int,
    loads: list[tuple[int, int, int, int]],
) -> int | None:
    for virtual_address, memory_size, file_offset, file_size in loads:
        if virtual_address <= address < virtual_address + memory_size:
            relative = address - virtual_address
            if relative >= file_size:
                return None
            return file_offset + relative
    return None
