"""Validate Bazel 7.6.1's effective archives and preserve release build configs."""

import ast
import errno
import hashlib
import os
import re
import shlex
import stat
from pathlib import Path

UPSTREAM_REGISTRY = "--registry=https://raw.githubusercontent.com/bazelbuild/bazel-central-registry/main/"
OPTIONAL_RC_IMPORTS = frozenset({
    "%workspace%/.tf_configure.bazelrc",
    "%workspace%/xla_configure.bazelrc",
    "%workspace%/.bazelrc.user",
    "%workspace%/warnings.bazelrc",
})
REPOSITORY_REDIRECTS = frozenset({
    "--override_repository",
    "--registry",
    "--experimental_resolved_file_instead_of_workspace",
})
HTTP_ARCHIVE = "@@bazel_tools//tools/build_defs/repo:http.bzl%http_archive"


def release_workspace_rc(text: str) -> str:
    lines = []
    for line in text.replace("\\\n", "").splitlines():
        words = shlex.split(line, comments=True)
        if not words:
            lines.append(line)
            continue
        section, *options = words
        if section in {"import", "try-import"}:
            if section == "try-import" and len(options) == 1 and options[0] in OPTIONAL_RC_IMPORTS:
                continue
            raise RuntimeError("Unexpected Bazel rc import; requalify the release configuration")
        if words == ["common", UPSTREAM_REGISTRY]:
            # The pinned builds use WORKSPACE, so the upstream Bzlmod mirror is inert.
            continue
        for option in options:
            name = option.partition("=")[0]
            if name in REPOSITORY_REDIRECTS:
                raise RuntimeError(f"Unexpected Bazel rc option {name}; requalify the release configuration")
        lines.append(line)
        if section == "build" and options and options[0].partition("=")[0] == "--repo_env":
            # sync evaluates WORKSPACE without inheriting build's repository environment.
            lines.append("sync " + " ".join(shlex.quote(option) for option in options))
    return "\n".join(lines) + "\n"


def bazel_path_chars(text: str) -> str:
    # Bazel's native Unix filesystem stores each path byte in a Java char.
    return text if os.name == "nt" else os.fsencode(text).decode("latin-1")


def bazel_file_digest(path: Path, mode: int) -> bytes:
    # The Windows filesystem reports regular files as executable.
    kind = "x" if os.name == "nt" or mode & stat.S_IXUSR else "-"
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        if error.filename is None:
            raise OSError(error.errno, error.strerror, os.fspath(path)) from error
        raise
    return kind.encode("utf-16-le") + digest.digest()


def bazel_tree_hash(directory: Path) -> str:
    # Match Bazel 7.6.1 Path.getDirectoryDigest, including Guava's little-endian chars.
    digest = hashlib.sha256()
    entries = sorted(
        directory.iterdir(),
        key=lambda path: bazel_path_chars(path.name).encode("utf-16-be", "surrogatepass"),
    )
    for path in entries:
        digest.update(bazel_path_chars(path.name).encode("utf-16-le", "surrogatepass"))
        info = path.lstat()
        mode = info.st_mode
        if stat.S_ISLNK(mode) or (os.name == "nt" and
                info.st_reparse_tag == stat.IO_REPARSE_TAG_MOUNT_POINT):
            target = os.readlink(path)
            if os.name == "nt":
                if target.startswith("\\\\?\\UNC\\"):
                    target = "\\\\" + target[8:]
                else:
                    target = target.removeprefix("\\\\?\\")
            target = os.path.normpath(target)
            if os.path.isabs(target):
                target_path = Path(target)
                try:
                    target_mode = target_path.stat().st_mode
                except OSError as error:
                    # Bazel hashes the link text when its target cannot be resolved.
                    # Windows reports a link loop as ERROR_CANT_RESOLVE_FILENAME (1921) with EINVAL.
                    if (error.errno not in (errno.ENOENT, errno.ENOTDIR, errno.ELOOP)
                            and getattr(error, "winerror", None) != 1921):
                        raise
                else:
                    if stat.S_ISREG(target_mode):
                        digest.update(bazel_file_digest(target_path, target_mode))
                        continue
            target = target.replace("\\", "/") if os.name == "nt" else re.sub(r"^//", "/", target)
            link = "" if target == "." else bazel_path_chars(target)
            digest.update(("l" + link).encode("utf-16-le", "surrogatepass"))
        elif stat.S_ISDIR(mode):
            digest.update(("d" + bazel_tree_hash(path)).encode("utf-16-le"))
        elif stat.S_ISREG(mode):
            digest.update(bazel_file_digest(path, mode))
        else:
            raise OSError(f"Unsupported Bazel repository tree entry: {path.name}")
    return digest.hexdigest()


def verify_resolved_archives(
    resolved_file: Path, pins: dict[str, tuple[str, str]], external_dir: Path,
) -> None:
    """Verify each archive's resolved rule, pinned identity, and fetched tree hash."""
    if not resolved_file.is_file():
        raise RuntimeError("Bazel did not report the resolved repositories")
    report = resolved_file.read_text(encoding="utf-8")
    if not report.startswith("resolved = [\n") or not report.rstrip().endswith("\n]"):
        raise RuntimeError("Unexpected Bazel resolved repository report")
    # Other rules can emit Starlark values that are not Python literals. Parse
    # only the archive entries, using Bazel 7.6.1's record indentation.
    records = re.findall(r"^     \{\n.*?^     \}(?=,?$)", report, re.MULTILINE | re.DOTALL)
    for name, (digest, prefix) in pins.items():
        entries = [record for record in records if re.search(
            rf'^               "name": "{re.escape(name)}",?$', record, re.MULTILINE,
        )]
        if len(entries) != 1:
            raise RuntimeError(f"Bazel did not resolve @{name} from its pinned archive")
        try:
            record = ast.literal_eval(entries[0].strip())
            original_rule = record["original_rule_class"]
            repository, = record["repositories"]
            attrs = repository["attributes"]
            identity = (
                repository["rule_class"], attrs["name"], attrs["sha256"], attrs["strip_prefix"],
            )
            tree_hash = repository["output_tree_hash"]
        except (KeyError, SyntaxError, TypeError, ValueError) as error:
            raise RuntimeError(f"Invalid Bazel resolved archive for @{name}") from error
        if (original_rule != HTTP_ARCHIVE or identity != (HTTP_ARCHIVE, name, digest, prefix)
                or not isinstance(tree_hash, str) or re.fullmatch(r"[0-9a-f]{64}", tree_hash) is None):
            raise RuntimeError(f"Bazel resolved @{name} from an unexpected archive")
        try:
            actual_tree_hash = bazel_tree_hash(external_dir / name)
        except OSError as error:
            raise RuntimeError(f"Could not hash Bazel output tree for @{name}: {error}") from error
        if tree_hash != actual_tree_hash:
            raise RuntimeError(
                f"Bazel output tree hash mismatch for @{name}: reported {tree_hash}, "
                f"computed {actual_tree_hash}"
            )
        print(f"Verified Bazel resolved archive @{name} SHA-256 {digest}", flush=True)
