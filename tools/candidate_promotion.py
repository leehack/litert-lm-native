#!/usr/bin/env python3
"""Read-only, digest-verified promotion of a trusted merged-source candidate."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import sys
import subprocess
import tempfile
from datetime import datetime, timezone
import zipfile

from release_result import parse_candidate_source as parse_source, validate_preparation

REPOSITORY = "leehack/litert-lm-native"
MAX_BYTES = 20 * 1024**3


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def api(endpoint: str) -> dict:
    result = subprocess.run(
        ["gh", "api", f"repos/{REPOSITORY}/{endpoint}"],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise ValueError("GitHub metadata must be an object")
    return value


def validate_metadata(
    source: dict,
    run: dict,
    artifact: dict,
    workflow: dict,
    env: dict[str, str],
    now: datetime,
) -> None:
    if source["runId"] == int(env["GITHUB_RUN_ID"]):
        raise ValueError("promotion requires an earlier successful preparation run")
    expected = {
        "id": source["runId"],
        "run_attempt": source["runAttempt"],
        "event": "workflow_dispatch",
        "head_branch": "main",
        "head_sha": env["NATIVE_COMMIT"],
        "status": "completed",
        "conclusion": "success",
        "path": ".github/workflows/native_release.yml",
        "workflow_id": workflow.get("id"),
    }
    if type(workflow.get("id")) is not int or any(
        run.get(k) != v for k, v in expected.items()
    ):
        raise ValueError(
            "candidate run is not a successful exact-source main release workflow"
        )
    for key in ("repository", "head_repository"):
        if (
            not isinstance(run.get(key), dict)
            or run[key].get("full_name") != REPOSITORY
        ):
            raise ValueError("candidate run repository is untrusted")
    expected_name = f"release-candidate-{env['RELEASE_TAG']}-{env['CORRELATION_ID']}"
    if (
        artifact.get("id") != source["artifactId"]
        or artifact.get("name") != expected_name
        or artifact.get("digest") != source["digest"]
        or artifact.get("expired") is not False
    ):
        raise ValueError("candidate artifact identity, digest or expiry mismatch")
    origin = artifact.get("workflow_run", {})
    if (
        origin.get("id") != source["runId"]
        or origin.get("head_sha") != env["NATIVE_COMMIT"]
        or origin.get("head_branch") != "main"
    ):
        raise ValueError("candidate artifact belongs to a different run or source")
    expires = datetime.fromisoformat(artifact["expires_at"].replace("Z", "+00:00"))
    if expires <= now:
        raise ValueError("candidate artifact has expired")
    if (
        type(artifact.get("size_in_bytes")) is not int
        or not 0 < artifact["size_in_bytes"] <= MAX_BYTES
    ):
        raise ValueError("candidate artifact size is invalid")


def safe_extract(archive: Path, destination: Path, digest: str) -> None:
    # Authenticate the complete immutable ZIP before inspecting or extracting it.
    if sha256(archive) != digest:
        raise ValueError("candidate ZIP digest mismatch")
    if destination.exists() or destination.is_symlink():
        raise ValueError("candidate destination must not exist")
    with zipfile.ZipFile(archive) as zipped:
        entries = zipped.infolist()
        names = set()
        total = 0
        for item in entries:
            name = item.filename
            path = PurePosixPath(name)
            mode = item.external_attr >> 16
            if (
                name in names
                or "\\" in name
                or ".." in path.parts
                or path.is_absolute()
                or path.as_posix() != name.rstrip("/")
                or stat.S_ISLNK(mode)
                or item.flag_bits & 1
                or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR))
            ):
                raise ValueError("unsafe or duplicate candidate ZIP entry")
            if item.is_dir():
                if name != "release/":
                    raise ValueError("unexpected candidate directory")
            elif name not in {"manifest.json", "SHA256SUMS", "release-result.json"}:
                if (
                    len(path.parts) != 2
                    or path.parts[0] != "release"
                    or not name.endswith((".zip", ".tar.gz"))
                ):
                    raise ValueError("unexpected candidate file")
            total += item.file_size
            if total > MAX_BYTES:
                raise ValueError("candidate ZIP exceeds extraction budget")
            names.add(name)
        if not {"manifest.json", "SHA256SUMS", "release-result.json"} <= names:
            raise ValueError("candidate ZIP is missing its contract")
        destination.mkdir()
        try:
            zipped.extractall(destination)
        except BaseException:
            shutil.rmtree(destination)
            raise


def inventory(candidate: Path) -> dict[str, str]:
    paths = [
        candidate / "manifest.json",
        candidate / "SHA256SUMS",
        candidate / "release-result.json",
        *sorted((candidate / "release").iterdir()),
    ]
    if any(path.is_symlink() or not path.is_file() for path in paths):
        raise ValueError("candidate payload must contain only regular files")
    return {path.relative_to(candidate).as_posix(): sha256(path) for path in paths}


def load_promotion(candidate: Path, env: dict[str, str]) -> dict:
    promotion = json.loads((candidate / "promotion.json").read_text())
    source = parse_source(env["CANDIDATE_SOURCE"])
    if not isinstance(promotion, dict) or set(promotion) != {
        "source",
        "result",
        "payloadDigests",
    }:
        raise ValueError("invalid promotion evidence")
    if promotion["source"] != source or promotion["payloadDigests"] != inventory(
        candidate
    ):
        raise ValueError("promoted candidate payload or source changed")
    result = json.loads((candidate / "release-result.json").read_text())
    manifest = json.loads((candidate / "manifest.json").read_text())
    if promotion["result"] != result:
        raise ValueError("preparation receipt changed")
    validate_preparation(result, manifest, source, env)
    return promotion


def verify_remote(source: dict, env: dict[str, str]) -> dict:
    run = api(f"actions/runs/{source['runId']}")
    artifact = api(f"actions/artifacts/{source['artifactId']}")
    workflow = api("actions/workflows/native_release.yml")
    validate_metadata(source, run, artifact, workflow, env, datetime.now(timezone.utc))
    return artifact


def main() -> None:
    env = dict(os.environ)
    from validate_publication_intent import validate_context

    validate_context(env)
    source = parse_source(env["CANDIDATE_SOURCE"])
    candidate = Path("candidate")
    artifact = verify_remote(source, env)
    if "--verify" in sys.argv:
        load_promotion(candidate, env)
        return
    with tempfile.TemporaryDirectory() as directory:
        archive = Path(directory) / "candidate.zip"
        with archive.open("wb") as output:
            subprocess.run(
                [
                    "gh",
                    "api",
                    f"repos/{REPOSITORY}/actions/artifacts/{source['artifactId']}/zip",
                ],
                stdout=output,
                check=True,
                timeout=600,
            )
        if archive.stat().st_size != artifact["size_in_bytes"]:
            raise ValueError("candidate ZIP size mismatch")
        safe_extract(archive, candidate, source["digest"])
    manifest = json.loads((candidate / "manifest.json").read_text())
    result = json.loads((candidate / "release-result.json").read_text())
    validate_preparation(result, manifest, source, env)
    subprocess.run(
        [
            sys.executable,
            "tools/validate_release_manifest.py",
            "candidate/manifest.json",
            "--upstream-tag",
            env["UPSTREAM_TAG"],
            "--upstream-commit",
            env["UPSTREAM_COMMIT"],
            "--compatibility-tag",
            env["COMPATIBILITY_TAG"],
            "--native-commit",
            env["NATIVE_COMMIT"],
            "--release-tag",
            env["RELEASE_TAG"],
            "--require-smoke",
            "linux/x64",
            "--require-smoke",
            "windows/x64",
            "--require-smoke",
            "macos/arm64",
        ],
        check=True,
    )
    promotion = {
        "source": source,
        "result": result,
        "payloadDigests": inventory(candidate),
    }
    (candidate / "promotion.json").write_text(
        json.dumps(promotion, indent=2, sort_keys=True) + "\n"
    )
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as output:
            output.write(
                f"### Exact candidate promotion\nSource run: {source['runId']}, attempt {source['runAttempt']}; "
                f"artifact {source['artifactId']}, `{source['digest']}`.\n\n"
                "Reused nine platform builds and three identical-byte CPU smokes. "
                "No new GPU or device qualification is implied.\n"
            )


if __name__ == "__main__":
    main()
