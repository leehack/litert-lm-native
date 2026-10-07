from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import generate_schema2_contract_fixture as fixture

from publication_state import release_notes
from release_result import build_result

ROOT = Path(__file__).resolve().parents[1]
NATIVE = "a" * 40
UPSTREAM = "b" * 40

# Real workflow shell, real publication_state, and real reconciliation CLI run
# against this persistent fake service. Draft creation deliberately has no tag.
FAKE_GH = (ROOT / "tests/fixtures/fake_release_gh.py").read_text()


def workflow_step(name: str) -> str:
    lines = (ROOT / ".github/workflows/native_release.yml").read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "- name: " + name)
    run = next(i for i in range(start, len(lines)) if lines[i].strip() == "run: |")
    end = run + 1
    while end < len(lines) and (
        not lines[end].strip() or lines[end].startswith("          ")
    ):
        end += 1
    return textwrap.dedent("\n".join(lines[run + 1 : end])).replace(
        "${{ needs.preflight.outputs.github_prerelease }}", "false"
    )


class DraftTagLifecycleTest(unittest.TestCase):
    def setUp(self):
        shell = os.environ.get("LIFECYCLE_BASH", "bash")
        version = subprocess.check_output(
            [shell, "-c", "echo ${BASH_VERSINFO[0]}"], text=True
        )
        if int(version.strip()) < 4:
            self.fail(
                "Lifecycle tests require Bash 4+; set LIFECYCLE_BASH to a modern Bash"
            )
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "tools").symlink_to(ROOT / "tools", target_is_directory=True)
        (self.root / "fakebin").mkdir()
        gh = self.root / "fakebin/gh"
        gh.write_text(FAKE_GH)
        gh.chmod(0o755)
        for name in (
            "manifest.json",
            "SHA256SUMS",
            "release-result.json",
            "release/runtime.tar.gz",
        ):
            path = self.root / "candidate" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(name)
        self.env = {
            **os.environ,
            "PATH": str(self.root / "fakebin") + os.pathsep + os.environ["PATH"],
            "FAKE_STATE": str(self.root / "state.json"),
            "GITHUB_REPOSITORY": "leehack/litert-lm-native",
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_SHA": NATIVE,
            "NATIVE_COMMIT": NATIVE,
            "UPSTREAM_COMMIT": UPSTREAM,
            "UPSTREAM_TAG": "v0.17.0",
            "COMPATIBILITY_TAG": "v0.17.0",
            "RELEASE_TAG": "v0.17.0",
            "CORRELATION_ID": "fixture-42",
            "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_RUN_ID": "42",
            "GITHUB_RUN_ATTEMPT": "3",
            "PUBLICATION_APPROVAL": "publish",
            "TARGET_PLATFORM": "all",
            "TARGET_ARCH": "all",
            "RUN_ASR_SMOKE": "true",
        }
        self.release = dict(
            id=100,
            tag_name="v0.17.0",
            target_commitish=NATIVE,
            name="LiteRT-LM v0.17.0",
            body=release_notes(
                release_tag="v0.17.0",
                upstream_tag="v0.17.0",
                upstream_commit=UPSTREAM,
                compatibility_tag="v0.17.0",
                native_commit=NATIVE,
                correlation_id="fixture-42",
                workflow_run_id=42,
            ),
            prerelease=False,
            draft=True,
            assets=[],
            html_url="https://github.com/leehack/litert-lm-native/releases/tag/untagged-fixture",
        )
        self.ref = {
            "ref": "refs/tags/v0.17.0",
            "object": {"type": "commit", "sha": NATIVE},
        }
        self.state = dict(release=None, ref=None, template=self.release, calls=[])
        self.writer = workflow_step(
            "Create or safely resume exact draft and replace candidate assets"
        )

    def run_shell(self, script, **overrides):
        self.state.update(overrides)
        Path(self.env["FAKE_STATE"]).write_text(json.dumps(self.state))
        result = subprocess.run(
            [
                os.environ.get("LIFECYCLE_BASH", "bash"),
                "-euo",
                "pipefail",
                "-c",
                script,
            ],
            cwd=self.root,
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.state = json.loads(Path(self.env["FAKE_STATE"]).read_text())
        return result

    def writes(self):
        return [
            c for c in self.state["calls"] if c[:1] == ["release"] or "--method" in c
        ]

    def prepare_promoted_candidate(self):
        from candidate_promotion import inventory
        from datetime import datetime, timedelta, timezone

        manifest = self.prepare_full_candidate()
        candidate = self.root / "candidate"
        original = json.loads((candidate / "release-result.json").read_text())
        original["workflow"].update(
            runId=41,
            runAttempt=1,
            url="https://github.com/leehack/litert-lm-native/actions/runs/41",
        )
        original["request"]["publicationApproval"] = "prepare-only"
        (candidate / "release-result.json").write_text(json.dumps(original))
        source = dict(runId=41, runAttempt=1, artifactId=7, digest="sha256:" + "a" * 64)
        promotion = dict(
            source=source, result=original, payloadDigests=inventory(candidate)
        )
        (candidate / "promotion.json").write_text(json.dumps(promotion))
        self.env["CANDIDATE_SOURCE"] = json.dumps(source)
        self.state["candidate_run"] = dict(
            id=41,
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
        self.state["candidate_artifact"] = dict(
            id=7,
            name="release-candidate-v0.17.0-fixture-42",
            digest=source["digest"],
            expired=False,
            size_in_bytes=123,
            expires_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            workflow_run=dict(id=41, head_sha=NATIVE, head_branch="main"),
        )
        return original

    def test_promoted_candidate_full_publication_retry_and_readonly_recovery(self):
        original = self.prepare_promoted_candidate()
        qualification = workflow_step(
            "Validate same-run candidate before any publication mutation"
        )
        promotion = workflow_step("Validate draft and promote it")
        self.env["GITHUB_STEP_SUMMARY"] = str(self.root / "summary.md")
        handoff = workflow_step(
            "Summarize exact published handoff and completed job timings"
        )
        script = qualification + "\n" + self.writer + "\n" + promotion + "\n" + handoff
        result = self.run_shell(script, fail_promotion=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.state["release"]["draft"])
        result = self.run_shell(script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.state["release"]["draft"])
        final = json.loads(
            next(
                content
                for aid, content in self.state["asset_data"].items()
                if aid
                == str(
                    next(
                        asset["id"]
                        for asset in self.state["release"]["assets"]
                        if asset["name"] == "release-result.json"
                    )
                )
            )
        )
        self.assertEqual(final["workflow"]["runId"], 42)
        self.assertEqual(final["candidate"]["preparation"]["result"], original)
        self.state["calls"] = []
        result = self.run_shell(script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.writes(), [])
        preview = json.loads(
            (
                self.root / "published-release-check/consumer-sync-preview.json"
            ).read_text()
        )
        self.assertEqual(preview["preparation"]["result"], original)
        self.assertFalse(preview["deviceQualified"])

    def test_promoted_candidate_missing_model_evidence_cannot_publish(self):
        from candidate_promotion import inventory

        self.prepare_promoted_candidate()
        candidate = self.root / "candidate"
        manifest = json.loads((candidate / "manifest.json").read_text())
        manifest["realModelSmokes"] = [
            smoke
            for smoke in manifest["realModelSmokes"]
            if smoke["platform"] != "windows"
        ]
        (candidate / "manifest.json").write_text(json.dumps(manifest))
        result = build_result(
            manifest=manifest,
            correlation_id="fixture-42",
            repository=self.env["GITHUB_REPOSITORY"],
            run_id=41,
            run_attempt=1,
            run_url="https://github.com/leehack/litert-lm-native/actions/runs/41",
            approval="prepare-only",
            outcome="prepared",
            release_tag="v0.17.0",
            upstream_tag="v0.17.0",
            upstream_commit=UPSTREAM,
            compatibility_tag="v0.17.0",
            native_commit=NATIVE,
            candidate_artifact="release-candidate-v0.17.0-fixture-42",
        )
        (candidate / "release-result.json").write_text(json.dumps(result))
        promotion = dict(
            source=json.loads(self.env["CANDIDATE_SOURCE"]),
            result=result,
            payloadDigests=inventory(candidate),
        )
        (candidate / "promotion.json").write_text(json.dumps(promotion))
        script = (
            workflow_step("Validate same-run candidate before any publication mutation")
            + "\n"
            + self.writer
        )
        response = self.run_shell(script)
        self.assertNotEqual(response.returncode, 0)
        self.assertIn("smoke", response.stderr.lower())
        self.assertEqual(self.writes(), [])

    def test_promoted_candidate_mismatch_fails_before_any_write(self):
        for change in ("payload", "source", "expired"):
            with self.subTest(change=change):
                self.prepare_promoted_candidate()
                if change == "payload":
                    (self.root / "candidate/release/runtime.tar.gz").write_text("skew")
                elif change == "source":
                    self.state["candidate_run"]["head_sha"] = "c" * 40
                else:
                    self.state["candidate_artifact"]["expired"] = True
                script = (
                    workflow_step(
                        "Validate same-run candidate before any publication mutation"
                    )
                    + "\n"
                    + self.writer
                )
                result = self.run_shell(script)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.writes(), [])

    def test_fresh_workflow_draft_creates_ref_before_upload(self):
        result = self.run_shell(self.writer)
        self.assertEqual(result.returncode, 0, result.stderr)
        writes = self.writes()
        self.assertEqual(
            [x[:2] for x in writes],
            [["api", "--include"], ["api", "--include"], ["release", "upload"]],
        )
        self.assertIn("--method", writes[1])
        self.assertEqual(writes[1][writes[1].index("--method") + 1], "POST")
        self.assertFalse(any("PATCH" in call for call in self.state["calls"]))
        self.assertEqual(
            self.state["create_payload"], {"ref": "refs/tags/v0.17.0", "sha": NATIVE}
        )
        self.assertEqual(len(self.state["release"]["assets"]), 4)
        self.assertGreaterEqual(self.state["tag_reads"], 2)

    def test_created_id_survives_delayed_list_and_readback_through_publication(self):
        self.prepare_full_candidate()
        qualification = workflow_step(
            "Validate same-run candidate before any publication mutation"
        )
        promotion = workflow_step("Validate draft and promote it")
        result = self.run_shell(
            qualification + "\n" + self.writer + "\n" + promotion,
            omit_created_from_lists=True,
            release_read_404_count=2,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.state["release"]["draft"])
        self.assertEqual(self.state["release_posts"], 1)
        self.assertTrue(
            all("/releases/null" not in " ".join(call) for call in self.state["calls"])
        )

    def test_readback_rejects_exhausted_missing_auth_server_and_wrong_identity(self):
        cases = [
            {"release_read_status": status} for status in (404, 401, 403, 429, 500)
        ]
        cases += [
            {"release_read_failure": "malformed"},
            {"release_read_failure": "transport"},
            {"release_read_response": {"id": 101}},
            {"release_read_response": {"body": "foreign"}},
            {"release_read_response": {"target_commitish": "c" * 40}},
        ]
        for case in cases:
            with self.subTest(case=case):
                self.state = dict(
                    release=None, ref=None, template=self.release, calls=[]
                )
                result = self.run_shell(self.writer, **case)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.state["release_posts"], 1)
                self.assertEqual(len(self.writes()), 1)
                self.assertIsNone(self.state["ref"])
                self.assertLessEqual(self.state["release_reads"], 3)
                self.assertIn(
                    "GET repos/leehack/litert-lm-native/releases/100", result.stderr
                )

    def test_create_response_identity_is_verified_before_readback(self):
        for field, value in (
            ("body", "foreign"),
            ("name", "foreign"),
            ("target_commitish", "c" * 40),
            ("prerelease", True),
            ("draft", False),
        ):
            with self.subTest(field=field):
                self.state = dict(
                    release=None, ref=None, template=self.release, calls=[]
                )
                result = self.run_shell(
                    self.writer, create_release_response={field: value}
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.state.get("release_reads", 0), 0)
                self.assertEqual(len(self.writes()), 1)

    def test_create_requires_http_created_without_retry(self):
        for status in (200, 202, 401, 403, 429, 500, 502, 503, 504):
            with self.subTest(status=status):
                self.state = dict(
                    release=None, ref=None, template=self.release, calls=[]
                )
                result = self.run_shell(self.writer, release_create_status=status)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.state.get("release_reads", 0), 0)
                self.assertEqual(len(self.writes()), 1)

    def test_prepare_rejects_untrusted_context_before_create(self):
        original = self.env.copy()
        for field, value in (
            ("GITHUB_EVENT_NAME", "push"),
            ("GITHUB_REF", "refs/heads/other"),
            ("GITHUB_REPOSITORY", "foreign/repo"),
            ("GITHUB_SHA", "c" * 40),
            ("PUBLICATION_APPROVAL", "prepare-only"),
        ):
            with self.subTest(field=field):
                self.env = {**original, field: value}
                self.state = dict(
                    release=None, ref=None, template=self.release, calls=[]
                )
                result = self.run_shell(self.writer)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.writes(), [])
        self.env = original

    def test_uncertain_create_never_retries_or_mutates_assets(self):
        for failure in ("malformed", "transport"):
            self.state = dict(
                release=None,
                ref=None,
                template=self.release,
                calls=[],
                release_response_failure=failure,
            )
            result = self.run_shell(self.writer)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.state["release_posts"], 1)
            self.assertEqual(len(self.writes()), 1)
            self.assertEqual(self.state.get("release_reads", 0), 0)

    def test_invalid_create_ids_never_reach_readback_or_second_post(self):
        for value in (None, "100", True, False, 0, -1):
            with self.subTest(id=value):
                self.state = dict(
                    release=None, ref=None, template=self.release, calls=[]
                )
                result = self.run_shell(
                    self.writer,
                    create_release_response={"id": value},
                    omit_created_from_lists=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.state["release_posts"], 1)
                self.assertEqual(self.state.get("release_reads", 0), 0)
                self.assertEqual(len(self.writes()), 1)

    def test_visible_collision_is_not_hidden_by_authoritative_id(self):
        result = self.run_shell(self.writer, listed_collision=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(self.state["ref"])
        self.assertFalse(
            any(call[:2] == ["release", "upload"] for call in self.writes())
        )

    def test_stale_listing_competitor_cannot_replace_captured_id(self):
        result = self.run_shell(self.writer, listed_competing_only=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.state["release_posts"], 1)
        self.assertEqual(self.state.get("release_reads", 0), 0)
        self.assertEqual(len(self.writes()), 1)
        self.assertIn("release ID changed", result.stderr)

    def test_exact_resume_missing_and_existing_ref(self):
        for ref in (None, self.ref):
            self.state = dict(
                release=copy.deepcopy(self.release),
                ref=copy.deepcopy(ref),
                template=self.release,
                calls=[],
            )
            result = self.run_shell(self.writer)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                sum("/git/refs" in " ".join(x) for x in self.writes()), int(ref is None)
            )
            self.assertEqual(self.state.get("release_posts", 0), 0)

    def run_readonly_history(self, name):
        script = workflow_step(name)
        start = script.index("history_args=()")
        end = script.index("gh api --paginate " + chr(92) + "\n", start)
        segment = script[start:end]
        action = "resume" if self.state["release"]["draft"] else "verify-published"
        (self.root / "publication-plan.json").write_text(json.dumps({"action": action}))
        (self.root / "existing-releases.json").write_text(
            json.dumps([self.state["release"]])
        )
        (self.root / "release-policy.env").write_text("github_prerelease=false\n")
        return self.run_shell("publication_args=(--allow-published-exact)\n" + segment)

    def test_both_readonly_workflow_history_paths_admit_exact_missing_draft(self):
        for name in (
            "Verify native and upstream commits",
            "Recheck exact identity and immutable history",
        ):
            with self.subTest(path=name):
                self.state = dict(
                    release=copy.deepcopy(self.release),
                    ref=None,
                    template=self.release,
                    calls=[],
                )
                result = self.run_readonly_history(name)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.writes(), [])
                self.assertEqual(
                    json.loads((self.root / "candidate-tag-ref.json").read_text()),
                    {"missingDraftTag": True},
                )

    def test_both_readonly_paths_reject_lookup_failures_without_missing_evidence(self):
        cases = [
            {"get_status": status} for status in (401, 403, 429, 500, 502, 503, 504)
        ]
        cases += [
            {"get_malformed": True},
            {"get_transport": True},
            {"release": {**self.release, "draft": False}},
            {"ref": {"ref": "refs/tags/foreign", "object": self.ref["object"]}},
            {"ref": {"ref": self.ref["ref"], "object": {"type": "tag", "sha": NATIVE}}},
            {
                "ref": {
                    "ref": self.ref["ref"],
                    "object": {"type": "commit", "sha": "c" * 40},
                }
            },
        ]
        for name in (
            "Verify native and upstream commits",
            "Recheck exact identity and immutable history",
        ):
            for case in cases:
                with self.subTest(path=name, case=case):
                    self.state = dict(
                        release=copy.deepcopy(self.release),
                        ref=None,
                        template=self.release,
                        calls=[],
                    )
                    self.state.update(copy.deepcopy(case))
                    result = self.run_readonly_history(name)
                    self.assertNotEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(self.writes(), [])
                    # The lookup itself must reject, not emit admitted missing
                    # evidence that happens to be rejected by a later guard.
                    self.assertEqual(
                        (self.root / "candidate-tag-ref.json").read_text(), ""
                    )

    def test_published_existing_is_readonly_missing_is_rejected(self):
        published = {**self.release, "draft": False}
        for ref in (self.ref, None):
            self.state = dict(
                release=published, ref=ref, template=self.release, calls=[]
            )
            result = self.run_shell(self.writer)
            self.assertEqual(result.returncode == 0, ref is not None, result.stderr)
            self.assertEqual(self.writes(), [])

    def test_foreign_transaction_and_assets_rejected_before_writes(self):
        variants = [
            {**self.release, key: value}
            for key, value in [
                ("body", "foreign"),
                ("target_commitish", "c" * 40),
                ("name", "foreign"),
            ]
        ]
        variants += [
            {
                **self.release,
                "assets": [
                    dict(
                        id=1,
                        name="foreign",
                        state="uploaded",
                        size=1,
                        digest="sha256:" + "0" * 64,
                    )
                ],
            },
            {
                **self.release,
                "assets": [
                    dict(
                        id=1,
                        name="manifest.json",
                        state="uploaded",
                        size=13,
                        digest="sha256:" + "0" * 64,
                    )
                ],
            },
        ]
        for release in variants:
            self.state = dict(
                release=release, ref=None, template=self.release, calls=[]
            )
            result = self.run_shell(self.writer)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.writes(), [])

    def test_release_id_change_before_helper_rejects_without_mutation(self):
        result = self.run_shell(
            self.writer,
            release=copy.deepcopy(self.release),
            change_id_before_helper=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.writes(), [])
        self.assertEqual((self.root / "candidate-tag-ref.json").read_text(), "")

    def test_matching_partial_assets_can_resume(self):
        data = (self.root / "candidate/manifest.json").read_bytes()
        asset = dict(
            id=1,
            name="manifest.json",
            state="uploaded",
            size=len(data),
            digest="sha256:" + hashlib.sha256(data).hexdigest(),
        )
        result = self.run_shell(
            self.writer, release={**self.release, "assets": [asset]}
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.state["release"]["assets"]), 4)

    def test_late_validated_receipt_resume_and_foreign_receipts(self):
        manifest = {
            "schemaVersion": 2,
            "release": {"tag": "v0.17.0", "githubPrerelease": False},
            "upstream": {
                "tag": "v0.17.0",
                "commit": UPSTREAM,
                "compatibilityTag": "v0.17.0",
            },
            "native": {"commit": NATIVE},
            "platforms": [],
            "artifacts": [],
            "realModelSmokes": [],
        }
        (self.root / "candidate/manifest.json").write_text(json.dumps(manifest))
        initial = self.run_shell(self.writer)
        self.assertEqual(initial.returncode, 0, initial.stderr)
        state = copy.deepcopy(self.state)
        receipt = build_result(
            manifest=manifest,
            correlation_id="fixture-42",
            repository=self.env["GITHUB_REPOSITORY"],
            run_id=42,
            run_attempt=2,
            run_url="https://github.com/leehack/litert-lm-native/actions/runs/42",
            approval="publish",
            outcome="validated-for-publication",
            release_tag="v0.17.0",
            upstream_tag="v0.17.0",
            upstream_commit=UPSTREAM,
            compatibility_tag="v0.17.0",
            native_commit=NATIVE,
            candidate_artifact="release-candidate-v0.17.0-fixture-42",
            release_metadata=state["release"],
        )
        for key, value in (
            (None, None),
            ("runId", 99),
            ("nativeCommit", "c" * 40),
            ("runAttempt", 4),
        ):
            self.state = copy.deepcopy(state)
            self.state["calls"] = []
            altered = copy.deepcopy(receipt)
            if key:
                altered["workflow"][key] = value
            content = json.dumps(altered)
            self.state["receipt_text"] = content
            asset = next(
                a
                for a in self.state["release"]["assets"]
                if a["name"] == "release-result.json"
            )
            asset["size"] = len(content.encode())
            asset["digest"] = "sha256:" + hashlib.sha256(content.encode()).hexdigest()
            result = self.run_shell(self.writer)
            self.assertEqual(result.returncode == 0, key is None, result.stderr)
            if key:
                self.assertEqual(self.writes(), [])

    def prepare_full_candidate(self):
        def check_ios_directory(path):
            self.assertEqual(path, fixture.package_release.BIN_DIR / "ios")

        def check_ios_archives(path):
            self.assertEqual(path, fixture.package_release.DIST_DIR / "spm" / "v0.17.0")

        with patch.multiple(
            fixture,
            UPSTREAM_TAG="v0.17.0",
            RELEASE_TAG="v0.17.0",
            UPSTREAM_COMMIT=UPSTREAM,
            NATIVE_COMMIT=NATIVE,
        ), patch.object(
            fixture.package_release,
            "validate_ios_directory",
            side_effect=check_ios_directory,
        ) as validate_ios, patch.object(
            fixture.package_release,
            "validate_ios_archives",
            side_effect=check_ios_archives,
        ) as validate_archives:
            # These payloads are synthetic metadata fixtures, not Mach-O or ZIP
            # artifacts. Isolate real inspection here while checking that the
            # production manifest builder still invokes both selected guards.
            manifest = fixture.generate_manifest()
            validate_ios.assert_called_once()
            validate_archives.assert_called_once()
            smoke = copy.deepcopy(manifest["realModelSmokes"][0])
            library = next(
                a
                for a in manifest["artifacts"]
                if a.get("platform") == "macos"
                and a.get("arch") == "arm64"
                and a["fileName"].endswith(".dylib")
                and "LiteRtLm" in a["fileName"]
            )
            smoke.update(
                platform="macos",
                arch="arm64",
                library={"fileName": library["fileName"], "sha256": library["sha256"]},
            )
            smoke["source"][
                "runtimeReleaseAsset"
            ] = "litert-lm-native-runtime-macos-arm64-v0.17.0.tar.gz"
            manifest["realModelSmokes"].append(smoke)
            names = [
                a["name"]
                for a in fixture.generate_release_metadata(manifest, "0" * 64)["assets"]
            ]
        for path in (self.root / "candidate/release").iterdir():
            path.unlink()
        for name in names:
            if name not in ("manifest.json", "SHA256SUMS", "release-result.json"):
                (self.root / "candidate/release" / name).write_text(
                    "fixture archive " + name
                )
        (self.root / "candidate/manifest.json").write_text(json.dumps(manifest))
        result = build_result(
            manifest=manifest,
            correlation_id="fixture-42",
            repository=self.env["GITHUB_REPOSITORY"],
            run_id=42,
            run_attempt=1,
            run_url="https://github.com/leehack/litert-lm-native/actions/runs/42",
            approval="publish",
            outcome="prepared",
            release_tag="v0.17.0",
            upstream_tag="v0.17.0",
            upstream_commit=UPSTREAM,
            compatibility_tag="v0.17.0",
            native_commit=NATIVE,
            candidate_artifact="release-candidate-v0.17.0-fixture-42",
        )
        (self.root / "candidate/release-result.json").write_text(json.dumps(result))
        self.assertEqual(len(manifest["platforms"]), 9)
        self.assertEqual(len(manifest["realModelSmokes"]), 3)
        return manifest

    def test_full_qualified_lifecycle_failed_promotion_retry_and_published_readonly(
        self,
    ):
        self.prepare_full_candidate()
        qualification = workflow_step(
            "Validate same-run candidate before any publication mutation"
        )
        promotion = workflow_step("Validate draft and promote it")
        result = self.run_shell(
            qualification + "\n" + self.writer + "\n" + promotion, fail_promotion=True
        )
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertIsNotNone(self.state["release"], result.stderr)
        self.assertTrue(self.state["release"]["draft"])
        self.assertEqual(self.writes()[-1][:2], ["release", "edit"], result.stderr)
        # The real promotion step has uploaded a real final receipt; the real
        # retry writer must recognize that exact receipt before replacing it.
        self.state["calls"] = []
        result = self.run_shell(qualification + "\n" + self.writer + "\n" + promotion)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.state["release"]["draft"])
        self.state["calls"] = []
        result = self.run_shell(qualification + "\n" + self.writer + "\n" + promotion)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.writes(), [])

    def test_full_qualification_failure_has_zero_mutations(self):
        manifest = self.prepare_full_candidate()
        manifest["realModelSmokes"].pop()
        (self.root / "candidate/manifest.json").write_text(json.dumps(manifest))
        result = self.run_shell(
            workflow_step("Validate same-run candidate before any publication mutation")
            + "\n"
            + self.writer
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.writes(), [])

    def test_tag_changes_before_promotion_are_rejected(self):
        self.prepare_full_candidate()
        result = self.run_shell(self.writer)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.state["calls"] = []
        self.state["ref"]["object"]["sha"] = "c" * 40
        result = self.run_shell(workflow_step("Validate draft and promote it"))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.writes(), [])

    def test_production_lifecycle_order_and_read_only_boundaries(self):
        workflow = (ROOT / ".github/workflows/native_release.yml").read_text()
        names = [
            "Validate same-run candidate before any publication mutation",
            "Recheck exact identity and immutable history",
            "Create or safely resume exact draft and replace candidate assets",
            "Validate draft and promote it",
        ]
        positions = [workflow.index("- name: " + name) for name in names]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(workflow.count("reconcile_release_tag.py --mode create"), 1)
        self.assertEqual(workflow.count("reconcile_release_tag.py --mode read"), 2)
        self.assertEqual(workflow.count("--allow-missing-draft-tag"), 2)
        writer = workflow_step(names[2])
        self.assertLess(
            writer.index("reconcile_release_tag.py --mode create"),
            writer.index("--method DELETE"),
        )
        self.assertIn('--expected-release-id "$release_id"', writer)
        for name in names:
            block = workflow[workflow.index("- name: " + name) :]
            block = block.split("\n      - ", 1)[0]
            self.assertNotIn("continue-on-error:", block)
            self.assertNotIn("if: false", block)
        self.assertNotIn("--allow-missing-draft-tag", workflow_step(names[3]))

    def test_lookup_errors_are_not_missing(self):
        for override in [{"get_status": x} for x in (401, 403, 429, 500)] + [
            {"get_malformed": True},
            {"get_transport": True},
        ]:
            self.state = dict(
                release=self.release,
                ref=None,
                template=self.release,
                calls=[],
                **override,
            )
            result = self.run_shell(self.writer)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.writes(), [])

    def test_conflict_and_uncertain_create_require_exact_readback(self):
        for override in [{"create_status": x} for x in (409, 422, 500)] + [
            {"create_transport": True}
        ]:
            for applied in (False, True):
                self.state = dict(
                    release=self.release,
                    ref=None,
                    template=self.release,
                    calls=[],
                    create_applies=applied,
                    **override,
                )
                result = self.run_shell(self.writer)
                self.assertEqual(result.returncode == 0, applied, result.stderr)
                if not applied:
                    self.assertFalse(
                        any(x[:2] == ["release", "upload"] for x in self.writes())
                    )
                self.assertEqual(
                    sum("/git/refs" in " ".join(x) for x in self.writes()), 1
                )

    def test_wrong_refs_and_transaction_changes_stop_upload(self):
        cases = [
            {"ref": {"ref": "refs/tags/wrong", "object": self.ref["object"]}},
            {"ref": {"ref": self.ref["ref"], "object": {"type": "tag", "sha": NATIVE}}},
            {"ref_changes": True},
            {"create_bad_response": True},
        ]
        cases += [
            {"mutate_after_readback": key}
            for key in ("body", "target_commitish", "id", "draft", "assets")
        ]
        for case in cases:
            self.state = dict(
                release=copy.deepcopy(self.release),
                ref=None,
                template=self.release,
                calls=[],
            )
            self.state.update(case)
            result = self.run_shell(self.writer)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(
                any(
                    x[:2] == ["release", "upload"] or "DELETE" in x
                    for x in self.writes()
                )
            )


class SyntheticCandidateFixtureTest(unittest.TestCase):
    def test_fixture_generation_needs_no_apple_tools_and_restores_real_guards(self):
        # Exercise only the Python fixture setup on Linux-like hosts. The
        # separate publication lifecycle suite still requires real Bash 4+.
        with tempfile.TemporaryDirectory() as temp:
            case = DraftTagLifecycleTest(
                "test_full_qualification_failure_has_zero_mutations"
            )
            case.root = Path(temp)
            case.env = {"GITHUB_REPOSITORY": "leehack/litert-lm-native"}
            (case.root / "candidate/release").mkdir(parents=True)
            real_ios_guard = fixture.package_release.validate_ios_directory
            real_archive_guard = fixture.package_release.validate_ios_archives
            with patch("ios_runtime_policy.shutil.which", return_value=None), patch(
                "ios_runtime_policy.subprocess.run",
                side_effect=AssertionError("Synthetic fixture invoked Apple tools"),
            ):
                manifest = case.prepare_full_candidate()
            self.assertEqual(len(manifest["platforms"]), 9)
            self.assertEqual(len(manifest["realModelSmokes"]), 3)
            self.assertEqual(manifest["upstream"]["compatibilityTag"], "v0.17.0")
            self.assertIs(
                fixture.package_release.validate_ios_directory, real_ios_guard
            )
            self.assertIs(
                fixture.package_release.validate_ios_archives, real_archive_guard
            )


if __name__ == "__main__":
    unittest.main()
