from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from candidate_promotion import (
    inventory,
    load_promotion,
    parse_source,
    safe_extract,
    sha256,
    validate_metadata,
    validate_preparation,
    main,
)
from release_result import build_result
import test_release_result
from test_release_result import NATIVE, UPSTREAM
from validate_publication_intent import validate_candidate


class CandidatePromotionTest(unittest.TestCase):
    def setUp(self):
        self.env = dict(
            GITHUB_REPOSITORY="leehack/litert-lm-native",
            GITHUB_RUN_ID="99",
            GITHUB_RUN_ATTEMPT="1",
            GITHUB_EVENT_NAME="workflow_dispatch",
            GITHUB_REF="refs/heads/main",
            GITHUB_SHA=NATIVE,
            NATIVE_COMMIT=NATIVE,
            PUBLICATION_APPROVAL="publish",
            TARGET_PLATFORM="all",
            TARGET_ARCH="all",
            RUN_ASR_SMOKE="true",
            RELEASE_TAG="v0.16.0-3",
            CORRELATION_ID="fixture",
            UPSTREAM_TAG="v0.16.0",
            UPSTREAM_COMMIT=UPSTREAM,
            COMPATIBILITY_TAG="v0.16.0",
        )
        self.source = dict(
            runId=42, runAttempt=1, artifactId=7, digest="sha256:" + "a" * 64
        )
        self.env["CANDIDATE_SOURCE"] = json.dumps(self.source)
        self.now = datetime.now(timezone.utc)
        self.run = dict(
            id=42,
            run_attempt=1,
            event="workflow_dispatch",
            head_branch="main",
            head_sha=NATIVE,
            status="completed",
            conclusion="success",
            workflow_id=123,
            path=".github/workflows/native_release.yml",
            repository=dict(full_name="leehack/litert-lm-native"),
            head_repository=dict(full_name="leehack/litert-lm-native"),
        )
        self.artifact = dict(
            id=7,
            name="release-candidate-v0.16.0-3-fixture",
            digest=self.source["digest"],
            expired=False,
            size_in_bytes=123,
            expires_at=(self.now + timedelta(days=1)).isoformat(),
            workflow_run=dict(id=42, head_sha=NATIVE, head_branch="main"),
        )
        self.workflow = dict(id=123)
        self.manifest = test_release_result.ReleaseResultTest().manifest()
        self.result = self.receipt()

    def receipt(self, **changes):
        values = dict(
            manifest=self.manifest,
            correlation_id="fixture",
            repository=self.env["GITHUB_REPOSITORY"],
            run_id=42,
            run_attempt=1,
            run_url="https://github.com/leehack/litert-lm-native/actions/runs/42",
            approval="prepare-only",
            outcome="prepared",
            release_tag="v0.16.0-3",
            upstream_tag="v0.16.0",
            upstream_commit=UPSTREAM,
            compatibility_tag="v0.16.0",
            native_commit=NATIVE,
            candidate_artifact="release-candidate-v0.16.0-3-fixture",
        )
        return build_result(**{**values, **changes})

    def test_exact_trusted_run_and_artifact(self):
        validate_metadata(
            self.source, self.run, self.artifact, self.workflow, self.env, self.now
        )
        validate_preparation(self.result, self.manifest, self.source, self.env)

    def test_untrusted_failed_partial_ambiguous_expired_and_mismatched_sources(self):
        cases = [
            ("run", "event", "pull_request"),
            ("run", "head_branch", "topic"),
            ("run", "head_sha", "c" * 40),
            ("run", "conclusion", "failure"),
            ("run", "status", "in_progress"),
            ("run", "workflow_id", 321),
            ("run", "path", ".github/workflows/pr_release_qualification.yml"),
            ("run", "run_attempt", 2),
            ("run", "id", 43),
            ("run", "head_repository", dict(full_name="attacker/fork")),
            ("run", "repository", dict(full_name="attacker/fork")),
            ("artifact", "id", 8),
            ("artifact", "name", "other"),
            ("artifact", "digest", "sha256:" + "b" * 64),
            ("artifact", "expired", True),
            ("artifact", "expires_at", (self.now - timedelta(seconds=1)).isoformat()),
            (
                "artifact",
                "workflow_run",
                dict(id=43, head_sha=NATIVE, head_branch="main"),
            ),
            ("artifact", "size_in_bytes", 0),
            ("artifact", "size_in_bytes", True),
        ]
        for section, key, value in cases:
            run, artifact = copy.deepcopy(self.run), copy.deepcopy(self.artifact)
            (run if section == "run" else artifact)[key] = value
            with self.subTest(section=section, key=key), self.assertRaises(
                (ValueError, KeyError)
            ):
                validate_metadata(
                    self.source, run, artifact, self.workflow, self.env, self.now
                )
        with self.assertRaises(ValueError):
            validate_metadata(
                self.source,
                self.run,
                self.artifact,
                self.workflow,
                {**self.env, "GITHUB_RUN_ID": "42"},
                self.now,
            )

    def test_request_parser_rejects_boolean_ids_extra_fields_and_missing_digest(self):
        for source in (
            {**self.source, "runId": True},
            {**self.source, "extra": 1},
            {**self.source, "digest": "a" * 64},
            {**self.source, "runAttempt": 0},
            [],
            None,
        ):
            with self.subTest(source=source), self.assertRaises(ValueError):
                parse_source(json.dumps(source))

    def test_receipt_cannot_be_rebound_to_tag_attempt_source_or_channel(self):
        for section, key, bad in (
            ("request", "releaseTag", "v0.16.0-4"),
            ("workflow", "runAttempt", 2),
            ("request", "publicationApproval", "publish"),
            ("request", "nativeCommit", "c" * 40),
            ("correlationId", None, "other"),
        ):
            result = copy.deepcopy(self.result)
            if key:
                result[section][key] = bad
            else:
                result[section] = bad
            with self.subTest(section=section, key=key), self.assertRaises(ValueError):
                validate_preparation(result, self.manifest, self.source, self.env)

    def archive(self, root, entries):
        archive = root / "candidate.zip"
        with zipfile.ZipFile(archive, "w") as zipped:
            for name, contents in entries:
                zipped.writestr(name, contents)
        return archive

    def files(self):
        return [
            ("manifest.json", json.dumps(self.manifest)),
            ("SHA256SUMS", "original checksums"),
            ("release-result.json", json.dumps(self.result)),
            ("release/runtime.tar.gz", "exact bytes"),
        ]

    def test_digest_checked_before_extraction_and_safe_zip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = self.archive(root, self.files())
            destination = root / "candidate"
            with self.assertRaisesRegex(ValueError, "digest"):
                safe_extract(archive, destination, "sha256:" + "0" * 64)
            self.assertFalse(destination.exists())
            safe_extract(archive, destination, sha256(archive))
            self.assertEqual(
                (destination / "release/runtime.tar.gz").read_text(), "exact bytes"
            )
            with self.assertRaisesRegex(ValueError, "exist"):
                safe_extract(archive, destination, sha256(archive))

    def test_traversal_symlinks_duplicates_unknown_files_and_zip_bombs_rejected(self):
        link = zipfile.ZipInfo("release/link.tar.gz")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        for name in (
            "../escape",
            "/tmp/escape",
            "release/../../escape",
            "release\\evil.zip",
            "release//evil.zip",
            "tools/tool.py",
            "promotion.json",
            "manifest.json",
            link,
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                archive = self.archive(root, self.files() + [(name, "bad")])
                with self.assertRaises(ValueError):
                    safe_extract(archive, root / "candidate", sha256(archive))
                self.assertFalse((root / "candidate").exists())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = self.archive(root, self.files())
            with patch("candidate_promotion.MAX_BYTES", 1), self.assertRaises(
                ValueError
            ):
                safe_extract(archive, root / "candidate", sha256(archive))

    def test_publication_validates_original_payload_and_preserves_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = self.archive(root, self.files())
            candidate = root / "candidate"
            safe_extract(archive, candidate, sha256(archive))
            promotion = dict(
                source=self.source,
                result=self.result,
                payloadDigests=inventory(candidate),
            )
            (candidate / "promotion.json").write_text(json.dumps(promotion))
            cwd = Path.cwd()
            os.chdir(root)
            try:
                validate_candidate(self.result, self.manifest, self.env)
                published = self.receipt(
                    run_id=99,
                    run_url="https://github.com/leehack/litert-lm-native/actions/runs/99",
                    approval="publish",
                    outcome="validated-for-publication",
                    preparation=promotion,
                )
                self.assertEqual(published["workflow"]["runId"], 99)
                self.assertEqual(
                    published["candidate"]["preparation"]["result"], self.result
                )
                (candidate / "release/runtime.tar.gz").write_text("changed")
                with self.assertRaisesRegex(ValueError, "changed"):
                    validate_candidate(self.result, self.manifest, self.env)
            finally:
                os.chdir(cwd)

    def test_production_cli_authenticates_before_extracting_and_runs_full_manifest_gate(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = self.archive(root, self.files())
            source = {**self.source, "digest": sha256(archive)}
            artifact = {
                **self.artifact,
                "digest": source["digest"],
                "size_in_bytes": archive.stat().st_size,
            }
            calls = []

            def fake_run(args, **kwargs):
                calls.append(args)
                if args[:2] == ["gh", "api"]:
                    kwargs["stdout"].write(archive.read_bytes())
                return subprocess.CompletedProcess(args, 0)

            cwd = Path.cwd()
            os.chdir(root)
            try:
                with patch.dict(
                    os.environ,
                    {**self.env, "CANDIDATE_SOURCE": json.dumps(source)},
                    clear=True,
                ), patch(
                    "candidate_promotion.verify_remote", return_value=artifact
                ), patch(
                    "candidate_promotion.subprocess.run", side_effect=fake_run
                ):
                    main()
                    load_promotion(
                        root / "candidate",
                        {**self.env, "CANDIDATE_SOURCE": json.dumps(source)},
                    )
                gate = calls[-1]
                self.assertIn("tools/validate_release_manifest.py", gate)
                for target in ("linux/x64", "windows/x64", "macos/arm64"):
                    self.assertIn(target, gate)
                self.assertEqual(
                    (root / "candidate/release-result.json").read_text(),
                    json.dumps(self.result),
                )
            finally:
                os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
