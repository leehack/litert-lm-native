#!/usr/bin/env python3
"""Validate only selected PR platforms; never emit full-release qualification."""
import json
import os
from pathlib import Path
import shutil
import tempfile

from package_release import load_smoke_evidence
from qualification_scope import MATRIX
from validate_runtime_artifacts import required_runtime_artifacts
from validate_runtime_dependencies import validate_elf_dependencies, validate_macho_dependencies


def validate(root, rows, upstream_tag, upstream_commit, native_commit, release_tag):
    if not rows or any(row not in MATRIX for row in rows) or len(rows) != len({(r['platform'], r['arch']) for r in rows}):
        raise ValueError('Expected unique known selected targets')
    platforms = {row['platform'] for row in rows}
    # Platform packaging operates on complete arch sets, including both Apple slices.
    if rows != [row for row in MATRIX if row['platform'] in platforms]:
        raise ValueError('Selected platform is missing an architecture')
    required = [path for path in required_runtime_artifacts(upstream_tag, include_official_assets=False)
                if path.parts[1] in platforms]
    for path in required:
        if not (root / path).is_file() or (root / path).stat().st_size == 0:
            raise ValueError(f'Missing affected runtime artifact: {path}')
    evidence = load_smoke_evidence(root / 'staged/release-evidence', upstream_commit=upstream_commit,
                                  native_commit=native_commit, release_tag=release_tag)
    actual = {(item['platform'],item['arch']) for item in evidence}
    expected = {(row['platform'],row['arch']) for row in rows} & {('linux','x64'),('windows','x64'),('macos','arm64')}
    if actual != expected:
        raise ValueError(f'Expected affected real-model evidence {expected}, got {actual}')
    with tempfile.TemporaryDirectory() as temp:
        isolated=Path(temp)
        for platform in platforms:
            shutil.copytree(root/'bin'/platform, isolated/'bin'/platform, symlinks=True)
        validate_elf_dependencies(isolated)
        validate_macho_dependencies(isolated)
    print(f'Validated affected platforms {sorted(platforms)}; not a full release candidate')


if __name__ == '__main__':
    validate(Path.cwd(), json.loads(os.environ['SELECTED_MATRIX'])['include'],
             os.environ['QUALIFICATION_UPSTREAM_TAG'], os.environ['QUALIFICATION_UPSTREAM_COMMIT'],
             os.environ['PR_HEAD_SHA'], os.environ['QUALIFICATION_RELEASE_TAG'])
