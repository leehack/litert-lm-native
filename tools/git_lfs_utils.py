from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from download_utils import download_to_path

UPSTREAM_MEDIA_BASE_URL = (
    "https://media.githubusercontent.com/media/google-ai-edge/LiteRT-LM"
)
GIT_LFS_VERSION = "https://git-lfs.github.com/spec/v1"
MAX_POINTER_BYTES = 1024
_OID_PATTERN = re.compile(r"sha256:([0-9a-f]{64})")


@dataclass(frozen=True)
class GitLfsPointer:
    sha256: str
    size: int


def read_git_lfs_pointer(path: Path) -> GitLfsPointer | None:
    """Returns Git LFS metadata when path contains a pointer, otherwise None."""
    if path.stat().st_size > MAX_POINTER_BYTES:
        return None

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None

    lines = text.splitlines()
    if not lines or lines[0] != f"version {GIT_LFS_VERSION}":
        return None

    fields: dict[str, str] = {}
    for line in lines[1:]:
        key, separator, value = line.partition(" ")
        if separator:
            fields[key] = value

    oid_match = _OID_PATTERN.fullmatch(fields.get("oid", ""))
    if oid_match is None:
        raise RuntimeError(f"Invalid Git LFS oid in {path}")
    try:
        size = int(fields["size"])
    except (KeyError, ValueError) as error:
        raise RuntimeError(f"Invalid Git LFS size in {path}") from error
    if size < 0:
        raise RuntimeError(f"Invalid Git LFS size in {path}: {size}")
    return GitLfsPointer(sha256=oid_match.group(1), size=size)


def materialize_git_lfs_file(
    path: Path,
    *,
    upstream_tag: str,
    source_root: Path,
) -> bool:
    """Downloads and verifies a LiteRT-LM Git LFS object when path is a pointer."""
    pointer = read_git_lfs_pointer(path)
    if pointer is None:
        return False

    relative_path = path.relative_to(source_root).as_posix()
    encoded_path = quote(relative_path, safe="/")
    url = f"{UPSTREAM_MEDIA_BASE_URL}/{upstream_tag}/{encoded_path}"
    staged = path.with_name(f"{path.name}.lfs-download")
    staged.unlink(missing_ok=True)
    try:
        download_to_path(
            url,
            staged,
            headers={"User-Agent": "litert-lm-native-lfs-materializer"},
            label=f"LiteRT-LM {upstream_tag} {relative_path}",
        )
        actual_size = staged.stat().st_size
        if actual_size != pointer.size:
            raise RuntimeError(
                f"Git LFS size mismatch for {relative_path}: expected "
                f"{pointer.size}, got {actual_size}"
            )
        actual_sha256 = _sha256_file(staged)
        if actual_sha256 != pointer.sha256:
            raise RuntimeError(
                f"Git LFS checksum mismatch for {relative_path}: expected "
                f"{pointer.sha256}, got {actual_sha256}"
            )
        staged.replace(path)
    finally:
        staged.unlink(missing_ok=True)
    print(f"Materialized Git LFS object {relative_path}", flush=True)
    return True


def materialize_git_lfs_libraries(
    source_dir: Path,
    *,
    upstream_tag: str,
    source_root: Path,
    suffixes: tuple[str, ...],
) -> int:
    """Materializes pointer-backed libraries immediately below source_dir."""
    if not source_dir.is_dir():
        return 0
    materialized = 0
    for path in sorted(source_dir.iterdir()):
        if path.is_file() and path.name.endswith(suffixes):
            materialized += int(
                materialize_git_lfs_file(
                    path,
                    upstream_tag=upstream_tag,
                    source_root=source_root,
                )
            )
    return materialized


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
