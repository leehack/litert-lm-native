from __future__ import annotations

import re
from urllib.parse import quote


FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
STABLE_TAG_RE = re.compile(
    r"^v(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)$"
)


def github_source_archive_url(repository: str, upstream_ref: str) -> str:
    """Return GitHub's documented source-archive URL for an exact tag or SHA."""
    if FULL_SHA_RE.fullmatch(upstream_ref):
        archive_ref = upstream_ref
    elif STABLE_TAG_RE.fullmatch(upstream_ref):
        archive_ref = f"refs/tags/{quote(upstream_ref, safe='')}"
    else:
        raise ValueError("upstream ref must be an exact stable tag or lowercase full SHA")
    return f"https://github.com/{repository}/archive/{archive_ref}.tar.gz"
