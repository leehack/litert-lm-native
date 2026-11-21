"""Validate Bazel 7.6.1's effective archives and preserve release build configs."""

import ast
import re
import shlex
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


def verify_resolved_archives(resolved_file: Path, pins: dict[str, tuple[str, str]]) -> None:
    """Verify the effective http_archive rule, digest, and revision for each pin."""
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
        print(f"Verified Bazel resolved archive @{name} SHA-256 {digest}", flush=True)
