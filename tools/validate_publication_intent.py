#!/usr/bin/env python3
"""Fail closed on publication context and same-run candidate identity."""

from __future__ import annotations

import json
import os
from pathlib import Path

from release_result import build_result


def validate_context(env: dict[str, str]) -> None:
    expected = {
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REPOSITORY": "leehack/litert-lm-native",
        "GITHUB_REF": "refs/heads/main",
        "PUBLICATION_APPROVAL": "publish",
        "TARGET_PLATFORM": "all",
        "TARGET_ARCH": "all",
        "RUN_ASR_SMOKE": "true",
    }
    if any(env.get(key) != value for key, value in expected.items()):
        raise ValueError("publication requires canonical main dispatch, explicit publish, and full qualification")
    if not env.get("GITHUB_SHA") or env["GITHUB_SHA"] != env.get("NATIVE_COMMIT"):
        raise ValueError("publication native commit must equal dispatch SHA")


def validate_candidate(result: dict, manifest: dict, env: dict[str, str]) -> None:
    validate_context(env)
    attempt = result.get("workflow", {}).get("runAttempt")
    # A failed-job rerun may reuse the successful package job from this run.
    if type(attempt) is not int or not 1 <= attempt <= int(env["GITHUB_RUN_ATTEMPT"]):
        raise ValueError("candidate attempt must belong to this run's past or current attempts")
    expected = build_result(
        manifest=manifest,
        correlation_id=env["CORRELATION_ID"],
        repository=env["GITHUB_REPOSITORY"],
        run_id=int(env["GITHUB_RUN_ID"]),
        run_attempt=attempt,
        run_url=f"https://github.com/{env['GITHUB_REPOSITORY']}/actions/runs/{env['GITHUB_RUN_ID']}",
        approval="publish",
        outcome="prepared",
        release_tag=env["RELEASE_TAG"],
        upstream_tag=env["UPSTREAM_TAG"] or None,
        upstream_commit=env["UPSTREAM_COMMIT"],
        compatibility_tag=env["COMPATIBILITY_TAG"],
        native_commit=env["NATIVE_COMMIT"],
        candidate_artifact=f"release-candidate-{env['RELEASE_TAG']}-{env['CORRELATION_ID']}",
    )
    if result != expected:
        raise ValueError("candidate result does not match this exact publication transaction")


def main() -> None:
    validate_candidate(
        json.loads(Path("candidate/release-result.json").read_text()),
        json.loads(Path("candidate/manifest.json").read_text()),
        dict(os.environ),
    )


if __name__ == "__main__":
    main()
