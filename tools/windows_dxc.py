#!/usr/bin/env python3
"""Stage the pinned DirectX Shader Compiler pair into the Windows runtime.

Dawn's D3D12 backend opens dxcompiler.dll and dxil.dll by name through its own
module directory, so the published Windows runtime must carry them beside
libwebgpu_dawn.dll or GPU engine creation fails during shader compilation.
"""
from __future__ import annotations

import argparse
import hashlib
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from download_utils import download_to_path
from litert_lm_symbols import is_at_least

USER_AGENT = "litert-lm-native-windows-dxc/1"

REPO_ROOT = Path(__file__).resolve().parents[1]
WINDOWS_RUNTIME_DIR = Path("bin/windows/x64")

DXC_RELEASE_TAG = "v1.9.2602"
DXC_ARCHIVE_URL = (
    "https://github.com/microsoft/DirectXShaderCompiler/releases/download/"
    f"{DXC_RELEASE_TAG}/dxc_2026_02_20.zip"
)
DXC_ARCHIVE_SHA256 = "a1e89031421cf3c1fca6627766ab3020ca4f962ac7e2caa7fab2b33a8436151e"


@dataclass(frozen=True)
class DxcFile:
    member: str
    filename: str
    sha256: str

    @property
    def target_path(self) -> Path:
        return WINDOWS_RUNTIME_DIR / self.filename


DXC_RUNTIME_FILES = (
    DxcFile(
        member="bin/x64/dxil.dll",
        filename="dxil.dll",
        sha256="058f2f52a680c38b223a5615b7df969def21f77e577562e5099d971dede992de",
    ),
    DxcFile(
        member="bin/x64/dxcompiler.dll",
        filename="dxcompiler.dll",
        sha256="b86a738ece4c05dbe2d9bbb29668a2ccb28a0740773c9b027cdc61e8d07b4d75",
    ),
)

DXC_LICENSE_FILES = (
    DxcFile(
        member="LICENSE-LLVM.txt",
        filename="DXC-LICENSE-LLVM.txt",
        sha256="729615317e28dd03907e46f0fc3b5e88f7853cee61d1a1471d2749335516b46f",
    ),
    DxcFile(
        member="LICENSE-MIT.txt",
        filename="DXC-LICENSE-MIT.txt",
        sha256="903df5512f7d02609fed0c780a9b704f5a3eeb6e4d84ebe42a29845c81899a3c",
    ),
    DxcFile(
        member="LICENSE-MS.txt",
        filename="DXC-LICENSE-MS.txt",
        sha256="734f72f239fe7b07b4c7203f294c1a7ce27095687278bab7e56d630d7c672963",
    ),
)

DXC_FILES = DXC_RUNTIME_FILES + DXC_LICENSE_FILES


def requires_dxc(upstream_tag: str) -> bool:
    """Released v0.16 Windows bundles predate DXC packaging; keep them valid."""
    return is_at_least(upstream_tag, (0, 17, 0))


def dxc_runtime_paths() -> list[Path]:
    return [file.target_path for file in DXC_RUNTIME_FILES]


def dxc_license_paths() -> list[Path]:
    return [file.target_path for file in DXC_LICENSE_FILES]


def extract_dxc_files(archive: Path, stage_dir: Path) -> int:
    stage_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        for file in DXC_FILES:
            try:
                payload = bundle.read(file.member)
            except KeyError as error:
                raise RuntimeError(
                    f"Pinned DXC archive is missing {file.member}"
                ) from error
            actual = hashlib.sha256(payload).hexdigest()
            if actual != file.sha256:
                raise RuntimeError(
                    f"DXC checksum mismatch for {file.member}: "
                    f"expected {file.sha256}, got {actual}"
                )
            destination = stage_dir / file.filename
            destination.unlink(missing_ok=True)
            destination.write_bytes(payload)
            print(f"Staged pinned DXC file {destination}", flush=True)
    return len(DXC_FILES)


def stage_windows_dxc(stage_dir: Path) -> int:
    with tempfile.TemporaryDirectory(prefix="litert-lm-native-dxc-") as temp:
        archive = Path(temp) / "dxc.zip"
        download_to_path(
            DXC_ARCHIVE_URL,
            archive,
            headers={"User-Agent": USER_AGENT},
            label=f"DirectX Shader Compiler {DXC_RELEASE_TAG}",
            attempts=3,
            timeout_seconds=60,
            deadline_seconds=600,
            expected_sha256=DXC_ARCHIVE_SHA256,
        )
        return extract_dxc_files(archive, stage_dir)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Stage the pinned DXC runtime pair and licences."
    )
    parser.add_argument(
        "--stage-dir",
        type=Path,
        default=REPO_ROOT / WINDOWS_RUNTIME_DIR,
    )
    args = parser.parse_args()
    staged = stage_windows_dxc(args.stage_dir)
    print(f"Staged {staged} pinned DXC files in {args.stage_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
