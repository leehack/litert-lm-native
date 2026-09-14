"""Finalize the distributable macOS runtime identity before model evidence."""
from __future__ import annotations

import subprocess
from pathlib import Path

LITERTLM_INSTALL_NAME = "@rpath/libLiteRtLm.dylib"


def normalize_macos_runtime_identity(library: Path) -> None:
    """Set the runtime install name without rewriting already-qualified bytes."""
    result = subprocess.run(
        ["otool", "-D", str(library)],
        check=True,
        capture_output=True,
        text=True,
    )
    lines = result.stdout.splitlines()
    if len(lines) != 2 or not lines[1].strip():
        raise RuntimeError(f"Expected one thin macOS dylib identity: {library}")
    if lines[1].strip() == LITERTLM_INSTALL_NAME:
        return
    subprocess.run(
        ["install_name_tool", "-id", LITERTLM_INSTALL_NAME, str(library)],
        check=True,
    )
