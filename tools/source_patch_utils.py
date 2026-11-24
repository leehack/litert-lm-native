"""Apply audited patches relative to the upstream source root."""

import os
import subprocess
from pathlib import Path


def apply_source_patch(
    source_root: Path, patch_file: Path, *, ignore_space_change: bool = False,
) -> None:
    # An enclosing owner repository can silently filter out Git-format hunks.
    env = {**os.environ, "GIT_CEILING_DIRECTORIES": source_root.resolve().parent.as_posix()}
    args = ["--ignore-space-change"] if ignore_space_change else []
    args.append(str(patch_file))
    subprocess.run(["git", "apply", "--check", *args], check=True, cwd=source_root, env=env)
    subprocess.run(["git", "apply", *args], check=True, cwd=source_root, env=env)
