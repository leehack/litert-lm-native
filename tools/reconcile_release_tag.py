#!/usr/bin/env python3
"""Reconcile draft tag lifecycle; only the qualified writer may create a ref."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from publication_state import (
    PublicationStateError,
    plan_publication,
    validate_candidate_assets,
    validate_tag_ref,
)
from validate_publication_intent import validate_context
from release_result import build_result


class ApiTransportError(PublicationStateError):
    pass


def api(endpoint: str, *, payload: dict | None = None) -> tuple[int, object]:
    command = ["gh", "api", "--include", endpoint]
    if payload is not None:
        command += ["--method", "POST", "--input", "-"]
    result = subprocess.run(
        command,
        input=json.dumps(payload) if payload else None,
        text=True,
        capture_output=True,
    )
    # gh --include preserves HTTP status even for non-2xx responses. Neither
    # arbitrary stderr text nor an empty/failed response is evidence of absence.
    match = re.match(r"HTTP/\S+ (\d{3})[^\n]*\n", result.stdout)
    if match is None:
        raise ApiTransportError("GitHub API returned no HTTP status")
    status = int(match[1])
    try:
        body = json.loads(re.split(r"\r?\n\r?\n", result.stdout, maxsplit=1)[1])
    except (IndexError, json.JSONDecodeError) as error:
        raise PublicationStateError("GitHub API returned malformed JSON") from error
    if 200 <= status < 300 and result.returncode:
        raise PublicationStateError("GitHub API failed despite successful HTTP status")
    return status, body


def exact_release(env: dict[str, str], prerelease: bool) -> dict:
    result = subprocess.run(
        [
            "gh",
            "api",
            "--paginate",
            "--slurp",
            f"repos/{env['GITHUB_REPOSITORY']}/releases?per_page=100",
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    pages = json.loads(result.stdout)
    if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
        raise PublicationStateError("release pages must be arrays")
    releases = [release for page in pages for release in page]
    plan = plan_publication(
        releases,
        approval=env["PUBLICATION_APPROVAL"],
        release_tag=env["RELEASE_TAG"],
        upstream_tag=env["UPSTREAM_TAG"] or None,
        upstream_commit=env["UPSTREAM_COMMIT"],
        compatibility_tag=env["COMPATIBILITY_TAG"],
        native_commit=env["NATIVE_COMMIT"],
        correlation_id=env["CORRELATION_ID"],
        workflow_run_id=int(env["GITHUB_RUN_ID"]),
        prerelease=prerelease,
        allow_published_exact=True,
    )
    if plan["action"] not in {"resume", "verify-published"}:
        raise PublicationStateError("tag reconciliation requires one exact release")
    return next(item for item in releases if item.get("id") == plan["releaseId"])


def validate_resume_assets(release: dict, candidate: Path, env: dict[str, str]) -> None:
    # Validate every existing asset before handling the one receipt whose bytes
    # legitimately change after final draft validation and before promotion.
    without_receipt = {
        **release,
        "assets": [
            asset
            for asset in release.get("assets", [])
            if asset.get("name") != "release-result.json"
        ],
    }
    validate_candidate_assets(
        without_receipt, candidate_dir=candidate, allow_partial=True
    )
    receipts = [
        asset
        for asset in release.get("assets", [])
        if asset.get("name") == "release-result.json"
    ]
    if len(receipts) > 1:
        raise PublicationStateError("duplicate release receipt")
    if not receipts:
        return
    try:
        validate_candidate_assets(release, candidate_dir=candidate, allow_partial=True)
        return
    except PublicationStateError:
        pass
    receipt = receipts[0]
    if (
        type(receipt.get("id")) is not int
        or type(receipt.get("size")) is not int
        or not 0 < receipt["size"] <= 1024 * 1024
    ):
        raise PublicationStateError("invalid final receipt metadata")
    downloaded = subprocess.run(
        [
            "gh",
            "api",
            f"repos/{env['GITHUB_REPOSITORY']}/releases/assets/{receipt['id']}",
            "-H",
            "Accept: application/octet-stream",
        ],
        capture_output=True,
        check=True,
    )
    if len(downloaded.stdout) != receipt["size"]:
        raise PublicationStateError("final receipt size mismatch")
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "release-result.json"
        path.write_bytes(downloaded.stdout)
        # A final receipt is meaningful only for a complete, byte-exact candidate.
        validate_candidate_assets(release, candidate_dir=candidate, release_result=path)
        result = json.loads(downloaded.stdout)
    attempt = result.get("workflow", {}).get("runAttempt")
    if type(attempt) is not int or not 1 <= attempt <= int(env["GITHUB_RUN_ATTEMPT"]):
        raise PublicationStateError("invalid final receipt attempt")
    expected = build_result(
        manifest=json.loads((candidate / "manifest.json").read_text()),
        correlation_id=env["CORRELATION_ID"],
        repository=env["GITHUB_REPOSITORY"],
        run_id=int(env["GITHUB_RUN_ID"]),
        run_attempt=attempt,
        run_url=f"https://github.com/{env['GITHUB_REPOSITORY']}/actions/runs/{env['GITHUB_RUN_ID']}",
        approval="publish",
        outcome="validated-for-publication",
        release_tag=env["RELEASE_TAG"],
        upstream_tag=env["UPSTREAM_TAG"] or None,
        upstream_commit=env["UPSTREAM_COMMIT"],
        compatibility_tag=env["COMPATIBILITY_TAG"],
        native_commit=env["NATIVE_COMMIT"],
        candidate_artifact=f"release-candidate-{env['RELEASE_TAG']}-{env['CORRELATION_ID']}",
        release_metadata=release,
    )
    if result != expected:
        raise PublicationStateError("final receipt does not match exact transaction")


def reconcile(
    *,
    mode: str,
    prerelease: bool,
    env: dict[str, str],
    candidate: Path,
    expected_release_id: int | None = None,
) -> dict:
    if mode == "create" and expected_release_id is None:
        raise PublicationStateError("writer requires the reconciled release ID")
    release = exact_release(env, prerelease)
    if expected_release_id is not None and release["id"] != expected_release_id:
        raise PublicationStateError("release ID changed before tag reconciliation")
    endpoint = f"repos/{env['GITHUB_REPOSITORY']}/git/ref/tags/{env['RELEASE_TAG']}"
    status, ref = api(endpoint)
    if status == 200:
        validate_tag_ref(
            ref, release_tag=env["RELEASE_TAG"], native_commit=env["NATIVE_COMMIT"]
        )
    elif status == 404 and isinstance(ref, dict) and ref.get("message") == "Not Found":
        if release.get("draft") is not True:
            raise PublicationStateError("published release must have its exact tag")
        if mode == "read":
            return {"missingDraftTag": True}
        if mode != "create":
            raise PublicationStateError("draft tag is missing")
    else:
        raise PublicationStateError(f"tag lookup failed with HTTP {status}")
    if mode == "create" and release.get("draft") is not True:
        return ref
    if mode == "create":
        validate_context(env)
        # Accept only already-uploaded bytes from this exact candidate, including
        # a partial previous attempt; reject foreign assets before any mutation.
        validate_resume_assets(release, candidate, env)
        if status == 404:
            try:
                created_status, created_ref = api(
                    f"repos/{env['GITHUB_REPOSITORY']}/git/refs",
                    payload={
                        "ref": f"refs/tags/{env['RELEASE_TAG']}",
                        "sha": env["NATIVE_COMMIT"],
                    },
                )
            except ApiTransportError:
                # A transport failure can conceal an accepted create. Only the
                # independent readback below can establish the outcome.
                created_status, created_ref = 0, None
            if created_status in {401, 403, 429}:
                raise PublicationStateError(
                    f"tag create failed with HTTP {created_status}"
                )
            if created_status == 201:
                validate_tag_ref(
                    created_ref,
                    release_tag=env["RELEASE_TAG"],
                    native_commit=env["NATIVE_COMMIT"],
                )
            elif created_status not in {0, 409, 422, 500, 502, 503, 504}:
                raise PublicationStateError(
                    f"unexpected tag create status {created_status}"
                )
        status, ref = api(endpoint)
        if status != 200:
            raise PublicationStateError("created tag is not readable")
        validate_tag_ref(
            ref, release_tag=env["RELEASE_TAG"], native_commit=env["NATIVE_COMMIT"]
        )
        current = exact_release(env, prerelease)
        invariant_fields = (
            "id",
            "tag_name",
            "target_commitish",
            "name",
            "body",
            "prerelease",
            "draft",
            "assets",
        )
        if any(current.get(field) != release.get(field) for field in invariant_fields):
            raise PublicationStateError("release changed during tag reconciliation")
    return ref


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("read", "create", "strict"), required=True)
    parser.add_argument("--prerelease", choices=("true", "false"), required=True)
    parser.add_argument("--expected-release-id", type=int)
    parser.add_argument("--candidate-dir", type=Path, default=Path("candidate"))
    args = parser.parse_args()
    print(
        json.dumps(
            reconcile(
                mode=args.mode,
                prerelease=args.prerelease == "true",
                env=dict(os.environ),
                candidate=args.candidate_dir,
                expected_release_id=args.expected_release_id,
            )
        )
    )


if __name__ == "__main__":
    main()
