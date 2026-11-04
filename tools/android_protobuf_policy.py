"""Android C API 1.0 bundled protobuf isolation and public-export contract."""
from __future__ import annotations

import re
from pathlib import Path

from litert_lm_symbols import required_bridge_symbols, required_c_api_symbols, uses_c_api_v1
from runtime_dependency_utils import elf_exported_symbols, is_elf


def requires_private_protobuf(upstream_tag: str) -> bool:
    # Development sources must pass their explicit stable compatibility baseline.
    if re.fullmatch(r"v\d+\.\d+\.\d+", upstream_tag) is None:
        raise ValueError("Android protobuf validation requires an upstream compatibility tag")
    return uses_c_api_v1(upstream_tag)


def validate_android_protobuf_isolation(
    library: Path, platform: str, upstream_tag: str,
) -> None:
    if platform != "android" or not requires_private_protobuf(upstream_tag):
        return
    if not is_elf(library):
        raise RuntimeError(f"{library} is not an Android ELF runtime")
    exported = elf_exported_symbols(library)
    # Reject every defined nonlocal protobuf dynamic symbol, even if st_other
    # says HIDDEN: Android lookup cannot safely be repaired by a visibility-byte edit.
    exposed = sorted(
        symbol for symbol in elf_exported_symbols(library, include_hidden=True)
        if "protobuf" in symbol
    )
    if exposed:
        raise RuntimeError(
            f"{library} exposes bundled protobuf dynamic symbols ({len(exposed)}): "
            + ", ".join(exposed[:8])
        )
    required = required_c_api_symbols(upstream_tag) + required_bridge_symbols(upstream_tag)
    missing = sorted(symbol.decode("ascii") for symbol in required if symbol.decode("ascii") not in exported)
    if missing:
        raise RuntimeError(
            f"{library} is missing required public LiteRT-LM/bridge exports: " + ", ".join(missing)
        )
