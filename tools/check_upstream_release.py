#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from download_utils import fetch_json as fetch_json_with_retries
from fetch_upstream import GITHUB_API as UPSTREAM_GITHUB_API
from fetch_upstream import request_headers
from validate_runtime_artifacts import OFFICIAL_APPLE_RUNTIME_ARCHIVES


def fetch_json(url: str) -> dict[str, Any]:
    return fetch_json_with_retries(url, headers=request_headers(url))


def resolve_upstream_commit(tag: str) -> str:
    encoded_tag = quote(tag, safe="")
    commit = fetch_json(f"{UPSTREAM_GITHUB_API}/commits/{encoded_tag}")
    sha = commit.get("sha")
    if not isinstance(sha, str) or not sha:
        raise RuntimeError(f"Upstream tag {tag} did not resolve to a commit")
    return sha


def required_official_assets() -> tuple[str, ...]:
    return OFFICIAL_APPLE_RUNTIME_ARCHIVES


def evaluate_release(
    candidate: dict[str, Any],
    baseline: dict[str, Any],
    *,
    allow_same_commit: bool = False,
) -> dict[str, Any]:
    candidate_tag = _required_string(candidate, "tag", "candidate metadata")
    candidate_commit = _required_string(candidate, "commit", "candidate metadata")
    baseline_tag = _required_string(baseline, "tag", "native baseline")
    baseline_commit = _required_string(baseline, "commit", "native baseline")
    baseline_release_tag = baseline.get("releaseTag")
    if not isinstance(baseline_release_tag, str) or not baseline_release_tag:
        baseline_release_tag = None
    baseline_label = baseline_release_tag or baseline_tag

    candidate_assets = {
        asset["name"]
        for asset in candidate.get("assets", [])
        if isinstance(asset, dict) and isinstance(asset.get("name"), str)
    }
    missing_assets = sorted(set(required_official_assets()) - candidate_assets)

    if candidate_commit == baseline_commit and not allow_same_commit:
        return _decision(
            candidate_tag=candidate_tag,
            candidate_commit=candidate_commit,
            baseline_tag=baseline_tag,
            baseline_commit=baseline_commit,
            should_prepare=False,
            reason="same_upstream_commit",
            message=(
                f"Skip {candidate_tag}: it resolves to the same upstream commit as "
                f"published native release {baseline_label} (upstream {baseline_tag})."
            ),
            missing_assets=missing_assets,
            baseline_release_tag=baseline_release_tag,
        )

    if missing_assets:
        return _decision(
            candidate_tag=candidate_tag,
            candidate_commit=candidate_commit,
            baseline_tag=baseline_tag,
            baseline_commit=baseline_commit,
            should_prepare=False,
            reason="missing_required_official_assets",
            message=(
                f"Skip {candidate_tag}: required official C runtime artifacts are "
                f"not published: {', '.join(missing_assets)}."
            ),
            missing_assets=missing_assets,
            baseline_release_tag=baseline_release_tag,
        )

    return _decision(
        candidate_tag=candidate_tag,
        candidate_commit=candidate_commit,
        baseline_tag=baseline_tag,
        baseline_commit=baseline_commit,
        should_prepare=True,
        reason="ready",
        message=(
            f"Prepare {candidate_tag}: it is newer than native baseline "
            f"{baseline_tag} and publishes all required official runtime artifacts. "
            "Publication still requires an explicit exact-input dispatch."
        ),
        missing_assets=[],
        baseline_release_tag=baseline_release_tag,
    )


def load_native_baseline(repository: str) -> dict[str, Any]:
    release = fetch_json(f"https://api.github.com/repos/{repository}/releases/latest")
    manifest_url = next(
        (
            asset.get("browser_download_url")
            for asset in release.get("assets", [])
            if isinstance(asset, dict) and asset.get("name") == "manifest.json"
        ),
        None,
    )
    if not isinstance(manifest_url, str) or not manifest_url:
        release_tag = release.get("tag_name", "<unknown>")
        raise RuntimeError(
            f"Latest native release {release_tag} does not publish manifest.json"
        )

    manifest = fetch_json(manifest_url)
    upstream = manifest.get("upstream")
    if not isinstance(upstream, dict):
        raise RuntimeError("Latest native release manifest has no upstream metadata")
    tag = _required_string(upstream, "tag", "latest native release manifest")
    commit = upstream.get("commit")
    if not isinstance(commit, str) or not commit:
        commit = resolve_upstream_commit(tag)
    return {"tag": tag, "commit": commit, "releaseTag": release.get("tag_name")}


def prepare_candidate(metadata: dict[str, Any]) -> dict[str, Any]:
    candidate = dict(metadata)
    tag = _required_string(candidate, "tag", "candidate metadata")
    commit = candidate.get("commit")
    if not isinstance(commit, str) or not commit:
        candidate["commit"] = resolve_upstream_commit(tag)
    return candidate


def _required_string(data: dict[str, Any], key: str, label: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"{label} has no {key}")
    return value


def _decision(
    *,
    candidate_tag: str,
    candidate_commit: str,
    baseline_tag: str,
    baseline_commit: str,
    should_prepare: bool,
    reason: str,
    message: str,
    missing_assets: list[str],
    baseline_release_tag: str | None,
) -> dict[str, Any]:
    baseline = {"tag": baseline_tag, "commit": baseline_commit}
    if baseline_release_tag is not None:
        baseline["releaseTag"] = baseline_release_tag
    return {
        "shouldPrepare": should_prepare,
        "reason": reason,
        "message": message,
        "candidate": {"tag": candidate_tag, "commit": candidate_commit},
        "baseline": baseline,
        "missingAssets": missing_assets,
        "preparation": {
            "releaseTag": candidate_tag,
            "upstreamTag": candidate_tag,
            "upstreamCommit": candidate_commit,
            "upstreamCompatibilityTag": candidate_tag,
            "publicationApproval": "prepare-only",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Check whether an upstream LiteRT-LM release is compatible with the "
            "native package workflow."
        )
    )
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--native-repository", required=True)
    parser.add_argument(
        "--allow-same-commit",
        action="store_true",
        help="Allow an explicitly ordered rebuild of an existing upstream line.",
    )
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="Exit nonzero unless the candidate is consumable for preparation.",
    )
    args = parser.parse_args()

    candidate_metadata = json.loads(args.candidate.read_text(encoding="utf-8"))
    if not isinstance(candidate_metadata, dict):
        raise RuntimeError("Candidate metadata must be a JSON object")

    candidate = prepare_candidate(candidate_metadata)
    baseline = load_native_baseline(args.native_repository)
    decision = evaluate_release(
        candidate,
        baseline,
        allow_same_commit=args.allow_same_commit,
    )
    print(json.dumps(decision, indent=2, sort_keys=True))
    if args.require_ready and not decision["shouldPrepare"]:
        raise SystemExit(decision["message"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
