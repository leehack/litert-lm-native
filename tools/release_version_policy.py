#!/usr/bin/env python3
"""Validate LiteRT-LM native release identities and immutable history."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable


STABLE_RE = re.compile(
    r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"
)
STABLE_REBUILD_RE = re.compile(
    r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"-([1-9][0-9]*)$"
)
DEVELOPMENT_RE = re.compile(r"^g([0-9a-f]{12})$")
DEVELOPMENT_REBUILD_RE = re.compile(r"^g([0-9a-f]{12})-([1-9][0-9]*)$")
LEGACY_STABLE_REBUILD_RE = re.compile(
    r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"-native\.([1-9][0-9]*)$"
)
FULL_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


class PolicyError(ValueError):
    """Raised when release identity does not satisfy the repository policy."""


@dataclass(frozen=True)
class ReleaseIdentity:
    tag: str
    channel: str
    kind: str
    core: tuple[int, ...] | str
    rebuild: int = 0
    legacy: bool = False

    @property
    def github_prerelease(self) -> bool:
        return self.channel == "development" or self.kind == "rebuild"


@dataclass(frozen=True)
class UpstreamIdentity:
    channel: str
    tag: str | None
    commit: str
    compatibility_tag: str

    @property
    def release_base(self) -> str:
        return self.tag or development_tag_for(self.commit)


def _stable_core(match: re.Match[str]) -> tuple[int, int, int]:
    return tuple(map(int, match.groups()[:3]))  # type: ignore[return-value]


def development_tag_for(commit: str) -> str:
    if not FULL_COMMIT_RE.fullmatch(commit):
        raise PolicyError(
            "development upstream commit must be an exact lowercase 40-hex SHA"
        )
    return f"g{commit[:12]}"


def parse_upstream(
    *, upstream_tag: str | None, upstream_commit: str, compatibility_tag: str
) -> UpstreamIdentity:
    if not FULL_COMMIT_RE.fullmatch(upstream_commit):
        raise PolicyError("upstream_commit must be an exact lowercase 40-hex SHA")
    compatibility = STABLE_RE.fullmatch(compatibility_tag)
    if compatibility is None:
        raise PolicyError("compatibility_tag must be stable vMAJOR.MINOR.PATCH")

    normalized_tag = upstream_tag.strip() if upstream_tag else None
    if normalized_tag:
        if STABLE_RE.fullmatch(normalized_tag) is None:
            raise PolicyError(
                "stable upstream_tag must be exact vMAJOR.MINOR.PATCH; use an "
                "empty tag plus an exact commit for development"
            )
        if compatibility_tag != normalized_tag:
            raise PolicyError(
                "stable compatibility_tag must exactly match upstream_tag"
            )
        return UpstreamIdentity(
            channel="stable",
            tag=normalized_tag,
            commit=upstream_commit,
            compatibility_tag=compatibility_tag,
        )

    return UpstreamIdentity(
        channel="development",
        tag=None,
        commit=upstream_commit,
        compatibility_tag=compatibility_tag,
    )


def parse_release_tag(tag: str) -> ReleaseIdentity:
    stable = STABLE_RE.fullmatch(tag)
    if stable:
        return ReleaseIdentity(tag, "stable", "upstream", _stable_core(stable))

    stable_rebuild = STABLE_REBUILD_RE.fullmatch(tag)
    if stable_rebuild:
        return ReleaseIdentity(
            tag,
            "stable",
            "rebuild",
            _stable_core(stable_rebuild),
            int(stable_rebuild.group(4)),
        )

    development = DEVELOPMENT_RE.fullmatch(tag)
    if development:
        return ReleaseIdentity(
            tag, "development", "commit", development.group(1)
        )

    development_rebuild = DEVELOPMENT_REBUILD_RE.fullmatch(tag)
    if development_rebuild:
        return ReleaseIdentity(
            tag,
            "development",
            "rebuild",
            development_rebuild.group(1),
            int(development_rebuild.group(2)),
        )

    legacy = LEGACY_STABLE_REBUILD_RE.fullmatch(tag)
    if legacy:
        return ReleaseIdentity(
            tag,
            "stable",
            "rebuild",
            _stable_core(legacy),
            int(legacy.group(4)),
            legacy=True,
        )

    raise PolicyError(
        f"invalid native release tag {tag!r}: expected vMAJOR.MINOR.PATCH, "
        "vMAJOR.MINOR.PATCH-N, g<12-hex>, or g<12-hex>-N"
    )


def validate_pair(
    upstream: UpstreamIdentity, release_tag: str
) -> ReleaseIdentity:
    release = parse_release_tag(release_tag)
    if release.legacy:
        raise PolicyError(
            f"legacy release tag {release_tag!r} is read-only compatibility; "
            f"emit {upstream.release_base!r} or append compact -N"
        )
    if release.channel != upstream.channel:
        raise PolicyError(
            f"release tag {release_tag!r} is {release.channel}, but the upstream "
            f"identity is {upstream.channel}"
        )
    if release.kind == "upstream":
        if release.tag != upstream.release_base:
            raise PolicyError(
                "upstream-aligned release tag must exactly match "
                f"{upstream.release_base!r}; got {release.tag!r}"
            )
        return release

    expected_core: tuple[int, ...] | str
    if upstream.channel == "stable":
        match = STABLE_RE.fullmatch(upstream.release_base)
        assert match is not None
        expected_core = _stable_core(match)
    else:
        expected_core = upstream.commit[:12]
    if release.core != expected_core:
        raise PolicyError(
            f"rebuild for {upstream.release_base} must preserve that exact prefix "
            "and append -N"
        )
    return release


def validate_history(candidate: ReleaseIdentity, existing_tags: Iterable[str]) -> None:
    parsed: list[ReleaseIdentity] = []
    for raw_tag in existing_tags:
        tag = raw_tag.strip()
        if not tag:
            continue
        if tag == candidate.tag:
            raise PolicyError(
                f"release tag collision: {candidate.tag!r} already exists; tags "
                "and releases are immutable"
            )
        try:
            parsed.append(parse_release_tag(tag))
        except PolicyError:
            # Historical tags outside the supported grammar remain immutable but
            # do not participate in the new ordering contract.
            continue

    if candidate.channel == "stable":
        stable = [item for item in parsed if item.channel == "stable"]
        if not stable:
            return
        latest_core = max(item.core for item in stable)
        assert isinstance(candidate.core, tuple)
        assert isinstance(latest_core, tuple)
        if candidate.core < latest_core:
            raise PolicyError(
                f"stable rollback: {candidate.tag!r} precedes the newest native "
                f"stable line v{'.'.join(map(str, latest_core))}"
            )
        same_line = [item for item in stable if item.core == candidate.core]
        if candidate.rebuild > 0:
            if not any(item.rebuild == 0 for item in same_line):
                raise PolicyError(
                    f"orphan stable rebuild: {candidate.tag!r} has no aligned "
                    "base release"
                )
            predecessor = candidate.rebuild - 1
            if not any(item.rebuild == predecessor for item in same_line):
                raise PolicyError(
                    f"orphan stable rebuild: {candidate.tag!r} requires same-line "
                    f"predecessor rebuild {predecessor}"
                )
        if same_line:
            latest_rebuild = max(item.rebuild for item in same_line)
            if candidate.rebuild <= latest_rebuild:
                raise PolicyError(
                    f"stable rebuild order: {candidate.tag!r} must use a rebuild "
                    f"number greater than {latest_rebuild}; legacy -native.N "
                    "releases count in this sequence"
                )
        return

    same_development = [
        item
        for item in parsed
        if item.channel == "development" and item.core == candidate.core
    ]
    if candidate.rebuild > 0:
        if not any(item.rebuild == 0 for item in same_development):
            raise PolicyError(
                f"orphan development rebuild: {candidate.tag!r} has no aligned "
                "base release"
            )
        predecessor = candidate.rebuild - 1
        if not any(item.rebuild == predecessor for item in same_development):
            raise PolicyError(
                f"orphan development rebuild: {candidate.tag!r} requires same-line "
                f"predecessor rebuild {predecessor}"
            )
    if same_development:
        latest_rebuild = max(item.rebuild for item in same_development)
        if candidate.rebuild <= latest_rebuild:
            raise PolicyError(
                f"development rebuild order: {candidate.tag!r} must use a rebuild "
                f"number greater than {latest_rebuild}"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream-tag", default="")
    parser.add_argument("--upstream-commit", required=True)
    parser.add_argument("--compatibility-tag", required=True)
    parser.add_argument("--release-tag", required=True)
    parser.add_argument("--existing-tags-file", type=Path)
    args = parser.parse_args()

    existing = (
        []
        if args.existing_tags_file is None
        else args.existing_tags_file.read_text(encoding="utf-8").splitlines()
    )
    try:
        upstream = parse_upstream(
            upstream_tag=args.upstream_tag,
            upstream_commit=args.upstream_commit,
            compatibility_tag=args.compatibility_tag,
        )
        release = validate_pair(upstream, args.release_tag)
        validate_history(release, existing)
    except PolicyError as error:
        parser.error(str(error))

    print(f"channel={release.channel}")
    print(f"release_kind={release.kind}")
    print(f"upstream_ref={upstream.tag or upstream.commit}")
    print(f"development_identity={development_tag_for(upstream.commit)}")
    print(f"github_prerelease={'true' if release.github_prerelease else 'false'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
