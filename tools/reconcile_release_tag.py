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
import time

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


def api(
    endpoint: str, *, payload: dict | None = None, timeout: float = 10
) -> tuple[int, object]:
    command = ["gh", "api", "--include", endpoint]
    if payload is not None:
        command += ["--method", "POST", "--input", "-"]
    method = "POST" if payload is not None else "GET"
    operation = f"{method} {endpoint}"
    try:
        result = subprocess.run(
            command,
            input=json.dumps(payload) if payload is not None else None,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise ApiTransportError(f"{operation}: request timed out") from None
    # gh --include preserves HTTP status even for non-2xx responses. Neither
    # arbitrary stderr text nor an empty/failed response is evidence of absence.
    match = re.match(r"HTTP/\S+ (\d{3})[^\n]*\n", result.stdout)
    if match is None:
        raise ApiTransportError(f"{operation}: no HTTP status")
    status = int(match[1])
    try:
        body = json.loads(re.split(r"\r?\n\r?\n", result.stdout, maxsplit=1)[1])
    except (IndexError, json.JSONDecodeError) as error:
        raise PublicationStateError(
            f"{operation}: HTTP {status}, malformed JSON"
        ) from None
    if 200 <= status < 300 and result.returncode:
        raise PublicationStateError(f"{operation}: HTTP {status}, client failure")
    return status, body


def publication_request(env: dict[str, str], prerelease: bool) -> dict:
    return dict(
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


def release_list(env: dict[str, str]) -> list[dict]:
    endpoint = f"repos/{env['GITHUB_REPOSITORY']}/releases?per_page=100"
    try:
        result = subprocess.run(
            ["gh", "api", "--paginate", "--slurp", endpoint],
            text=True,
            capture_output=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        raise PublicationStateError(f"GET {endpoint}: request timed out") from None
    if result.returncode:
        raise PublicationStateError(f"GET {endpoint}: release-list request failed")
    try:
        pages = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise PublicationStateError(f"GET {endpoint}: malformed JSON") from None
    if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
        raise PublicationStateError("release pages must be arrays")
    return [release for page in pages for release in page]


def require_release_id(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise PublicationStateError(
            "release readback requires a positive numeric release ID"
        )
    return value


def read_release(env: dict[str, str], prerelease: bool, release_id: int) -> dict:
    release_id = require_release_id(release_id)
    endpoint = f"repos/{env['GITHUB_REPOSITORY']}/releases/{release_id}"
    deadline = time.monotonic() + 30
    for attempt in range(3):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        status, release = api(endpoint, timeout=min(10, remaining))
        if time.monotonic() >= deadline:
            raise PublicationStateError(f"GET {endpoint}: readback deadline exhausted")
        if status == 200:
            if not isinstance(release, dict) or release.get("id") != release_id:
                raise PublicationStateError(
                    f"GET {endpoint}: HTTP 200, release ID mismatch"
                )
            require_release_id(release["id"])
            try:
                plan = plan_publication(
                    [release], **publication_request(env, prerelease)
                )
            except PublicationStateError as error:
                raise PublicationStateError(
                    f"GET {endpoint}: HTTP 200, {error}"
                ) from None
            if plan["action"] not in {"resume", "verify-published"}:
                raise PublicationStateError(
                    f"GET {endpoint}: unexpected plan {plan['action']}"
                )
            return release
        # Only a genuine missing-ID readback may be eventually consistent.
        # Authentication, malformed responses and server errors fail closed.
        if (
            status != 404
            or not isinstance(release, dict)
            or release.get("message") != "Not Found"
        ):
            raise PublicationStateError(
                f"GET {endpoint}: HTTP {status}, readback rejected"
            )
        if attempt < 2:
            wait = 2**attempt
            if time.monotonic() + wait >= deadline:
                break
            time.sleep(wait)
    raise PublicationStateError(
        f"GET {endpoint}: HTTP 404, exact-ID readback budget exhausted"
    )


def exact_release(
    env: dict[str, str], prerelease: bool, release_id: int | None = None
) -> dict:
    if release_id is not None:
        require_release_id(release_id)
    releases = release_list(env)
    # Retain list collision checks, even when its newly created record is not
    # visible yet. Only the authoritative ID response may fill that omission.
    listed_plan = plan_publication(releases, **publication_request(env, prerelease))
    if release_id is not None:
        if listed_plan["action"] != "create" and listed_plan["releaseId"] != release_id:
            raise PublicationStateError("release ID changed before tag reconciliation")
        return read_release(env, prerelease, release_id)
    if listed_plan["action"] not in {"resume", "verify-published"}:
        raise PublicationStateError("tag reconciliation requires one exact release")
    require_release_id(listed_plan["releaseId"])
    return next(item for item in releases if item.get("id") == listed_plan["releaseId"])


def prepare_release(env: dict[str, str], prerelease: bool) -> dict:
    validate_context(env)
    plan = plan_publication(release_list(env), **publication_request(env, prerelease))
    if plan["action"] == "create":
        endpoint = f"repos/{env['GITHUB_REPOSITORY']}/releases"
        status, created = api(
            endpoint,
            payload=dict(
                tag_name=env["RELEASE_TAG"],
                target_commitish=env["NATIVE_COMMIT"],
                name=plan["title"],
                body=plan["notes"],
                draft=True,
                prerelease=prerelease,
            ),
        )
        # Never retry a create whose outcome is uncertain. A later separately
        # authorized attempt must reconcile any retained exact draft first.
        if status != 201 or not isinstance(created, dict):
            raise PublicationStateError(
                f"POST {endpoint}: HTTP {status}, create response rejected"
            )
        release_id = require_release_id(created.get("id"))
        created_plan = plan_publication(
            [created], **publication_request(env, prerelease)
        )
        if created_plan["action"] != "resume":
            raise PublicationStateError(
                f"POST {endpoint}: expected exact draft, plan={created_plan['action']}"
            )
    else:
        release_id = require_release_id(plan["releaseId"])
    return exact_release(env, prerelease, release_id)


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
    release = exact_release(env, prerelease, expected_release_id)
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
        current = exact_release(env, prerelease, expected_release_id)
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
    parser.add_argument(
        "--mode",
        choices=("read", "create", "strict", "prepare", "release"),
        required=True,
    )
    parser.add_argument("--prerelease", choices=("true", "false"), required=True)
    parser.add_argument("--expected-release-id", type=int)
    parser.add_argument("--candidate-dir", type=Path, default=Path("candidate"))
    args = parser.parse_args()
    env = dict(os.environ)
    prerelease = args.prerelease == "true"
    if args.mode == "prepare":
        result = prepare_release(env, prerelease)
    elif args.mode == "release":
        result = exact_release(
            env, prerelease, require_release_id(args.expected_release_id)
        )
    else:
        result = reconcile(
            mode=args.mode,
            prerelease=prerelease,
            env=env,
            candidate=args.candidate_dir,
            expected_release_id=args.expected_release_id,
        )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
