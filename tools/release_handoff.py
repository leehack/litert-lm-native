#!/usr/bin/env python3
"""Render a digest-bound release handoff and a read-only consumer sync preview."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from datetime import datetime

from candidate_promotion import sha256


def handoff(
    result: dict, manifest: dict, manifest_digest: str, jobs: list[dict]
) -> tuple[str, dict]:
    release = result.get("release")
    if (
        not isinstance(release, dict)
        or release.get("assetDigests", {}).get("manifest.json") != manifest_digest
    ):
        raise ValueError(
            "handoff requires a published receipt binding the exact manifest bytes"
        )
    request = result["request"]
    if (
        manifest["release"]["tag"] != request["releaseTag"]
        or manifest["native"]["commit"] != request["nativeCommit"]
        or manifest["upstream"]["commit"] != request["upstreamCommit"]
    ):
        raise ValueError("handoff manifest identity mismatch")
    preparation = result.get("candidate", {}).get("preparation")
    completed = [
        job for job in jobs if job.get("started_at") and job.get("completed_at")
    ]
    seconds = sum(
        (
            datetime.fromisoformat(job["completed_at"].replace("Z", "+00:00"))
            - datetime.fromisoformat(job["started_at"].replace("Z", "+00:00"))
        ).total_seconds()
        for job in completed
    )
    tag = request["releaseTag"]
    lines = [
        f"## LiteRT-LM {tag} consumer handoff",
        "",
        f"Published assets: {release['url']}",
        f"Publication run: {result['workflow']['url']} (attempt {result['workflow']['runAttempt']})",
        f"Native commit: `{request['nativeCommit']}`",
        f"Upstream commit: `{request['upstreamCommit']}`",
        f"Manifest: `{manifest_digest}`",
        "",
    ]
    if preparation:
        source = preparation["source"]
        lines += [
            f"Preparation: {preparation['result']['workflow']['url']} (attempt {source['runAttempt']})",
            f"Immutable candidate: artifact {source['artifactId']}, `{source['digest']}`",
            "Reused nine builds and three CPU model smokes from the exact candidate.",
            "",
        ]
    else:
        lines += ["Qualification and publication used the full rebuild path.", ""]
    lines += [
        "### Recorded model evidence",
        "",
        "| Platform | Backend | Model | Result |",
        "| --- | --- | --- | --- |",
    ]
    for smoke in manifest["realModelSmokes"]:
        lines.append(
            f"| {smoke['platform']}/{smoke['arch']} | {smoke.get('backend', 'unspecified')} | "
            f"{smoke.get('model', {}).get('fileName', 'unspecified')} | {smoke['result']} |"
        )
    lines += [
        "",
        "CPU model evidence does not qualify GPU execution. Independent review and affected",
        "device results must be supplied separately; missing evidence remains unqualified.",
        "",
        "### Timing snapshot",
        "",
        f"{len(completed)}/{len(jobs)} listed jobs completed; completed runner-job time: {seconds:.0f}s.",
        "The publication job is still running when this snapshot is collected. This is not final wall time.",
        "",
        "### Consumer preview",
        "",
        "In llamadart, inspect the exact published assets without changing pins:",
        "",
        "```sh",
        f"python3 tool/native/sync_native_release_pins.py --litert-lm-tag {tag} --dry-run",
        "```",
        "",
        "Adoption requires a reviewed consumer PR and affected device qualification.",
    ]
    preview = {
        "releaseTag": tag,
        "releaseUrl": release["url"],
        "nativeCommit": request["nativeCommit"],
        "upstreamCommit": request["upstreamCommit"],
        "manifestDigest": manifest_digest,
        "publishedAssetDigests": release["assetDigests"],
        "publicationRun": result["workflow"],
        "preparation": preparation,
        "modelEvidence": manifest["realModelSmokes"],
        "qualificationLimits": {
            "independentReview": "not-attached",
            "affectedDeviceEvidence": "not-attached",
            "cpuDoesNotQualifyGpu": True,
            "ios16_4Execution": "not-attached",
        },
        "deviceQualified": False,
        "requiresReviewedConsumerPR": True,
        "timingSnapshot": {
            "completedJobs": len(completed),
            "listedJobs": len(jobs),
            "completedRunnerSeconds": seconds,
            "final": False,
        },
    }
    return "\n".join(lines) + "\n", preview


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--jobs", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--preview", type=Path, required=True)
    args = parser.parse_args()
    summary, preview = handoff(
        json.loads(args.result.read_text()),
        json.loads(args.manifest.read_text()),
        sha256(args.manifest),
        json.loads(args.jobs.read_text()),
    )
    with args.summary.open("a") as output:
        output.write(summary)
    args.preview.write_text(json.dumps(preview, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
