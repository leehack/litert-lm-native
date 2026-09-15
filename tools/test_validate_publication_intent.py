from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from release_result import build_result
import test_release_result
from test_release_result import NATIVE, UPSTREAM
from validate_publication_intent import validate_candidate, validate_context


class PublicationIntentTest(unittest.TestCase):
    def setUp(self):
        self.env = dict(
            GITHUB_EVENT_NAME="workflow_dispatch", GITHUB_REPOSITORY="leehack/litert-lm-native",
            GITHUB_REF="refs/heads/main", GITHUB_SHA=NATIVE, NATIVE_COMMIT=NATIVE,
            PUBLICATION_APPROVAL="publish", TARGET_PLATFORM="all", TARGET_ARCH="all",
            RUN_ASR_SMOKE="true", GITHUB_RUN_ID="42", GITHUB_RUN_ATTEMPT="2",
            CORRELATION_ID="release-42", RELEASE_TAG="v0.16.0-3", UPSTREAM_TAG="v0.16.0",
            UPSTREAM_COMMIT=UPSTREAM, COMPATIBILITY_TAG="v0.16.0",
        )
        self.manifest = test_release_result.ReleaseResultTest().manifest()
        self.result = build_result(
            manifest=self.manifest, correlation_id="release-42", repository=self.env["GITHUB_REPOSITORY"],
            run_id=42, run_attempt=1, run_url="https://github.com/leehack/litert-lm-native/actions/runs/42",
            approval="publish", outcome="prepared", release_tag="v0.16.0-3", upstream_tag="v0.16.0",
            upstream_commit=UPSTREAM, compatibility_tag="v0.16.0", native_commit=NATIVE,
            candidate_artifact="release-candidate-v0.16.0-3-release-42",
        )

    def test_same_run_failed_job_retry_and_current_attempt(self):
        validate_candidate(self.result, self.manifest, self.env)
        self.result["workflow"]["runAttempt"] = 2
        validate_candidate(self.result, self.manifest, self.env)

    def test_untrusted_or_partial_context_rejected(self):
        for key, value in self.env.items():
            if key not in {"GITHUB_EVENT_NAME", "GITHUB_REPOSITORY", "GITHUB_REF", "GITHUB_SHA",
                           "NATIVE_COMMIT", "PUBLICATION_APPROVAL", "TARGET_PLATFORM", "TARGET_ARCH", "RUN_ASR_SMOKE"}:
                continue
            for bad in ("", "untrusted"):
                with self.subTest(key=key, bad=bad), self.assertRaises(ValueError):
                    validate_context({**self.env, key: bad})

    def test_every_result_field_is_bound(self):
        for section, values in self.result.items():
            if isinstance(values, dict):
                for key in values:
                    altered = copy.deepcopy(self.result)
                    altered[section][key] = "skew"
                    with self.subTest(section=section, key=key), self.assertRaises(ValueError):
                        validate_candidate(altered, self.manifest, self.env)
            else:
                altered = copy.deepcopy(self.result)
                altered[section] = "skew"
                with self.subTest(section=section), self.assertRaises(ValueError):
                    validate_candidate(altered, self.manifest, self.env)

    def test_future_attempt_cross_run_and_prepare_only_rejected(self):
        for section, key, value in (("workflow", "runAttempt", 3), ("workflow", "runAttempt", True),
                                    ("workflow", "runId", 41), ("request", "publicationApproval", "prepare-only")):
            altered = copy.deepcopy(self.result)
            altered[section][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_candidate(altered, self.manifest, self.env)

    def test_cli_runs_validation_and_rejects_skew(self):
        script = Path(__file__).with_name("validate_publication_intent.py")
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "candidate"
            candidate.mkdir()
            (candidate / "manifest.json").write_text(json.dumps(self.manifest))
            (candidate / "release-result.json").write_text(json.dumps(self.result))
            for run_id, expected in (("42", 0), ("99", 1)):
                result = subprocess.run([sys.executable, str(script)], cwd=directory,
                    env={**os.environ, **self.env, "GITHUB_RUN_ID": run_id}, capture_output=True)
                self.assertEqual(result.returncode, expected, result.stderr)

    def test_production_callsites_fail_closed_before_writes(self):
        source = (Path(__file__).parents[1] / ".github/workflows/native_release.yml").read_text()
        publish = source.split("  publish:\n", 1)[1]
        self.assertEqual(publish[:publish.index("    concurrency:")], "    name: Publish validated immutable release\n    if: >-\n      github.event_name == 'workflow_dispatch' &&\n      github.repository == 'leehack/litert-lm-native' &&\n      github.ref == 'refs/heads/main' &&\n      github.sha == inputs.native_commit &&\n      inputs.publication_approval == 'publish' &&\n      needs.preflight.result == 'success' &&\n      needs.runtime-matrix.result == 'success' &&\n      needs.build-upstream-runtime.result == 'success' &&\n      needs.package.result == 'success'\n    needs: [preflight, runtime-matrix, build-upstream-runtime, package]\n")
        self.assertEqual(publish[publish.index("      - name: Validate same-run"):publish.index("      - name: Recheck exact")], '      - name: Validate same-run candidate before any publication mutation\n        shell: bash\n        run: |\n          set -euo pipefail\n          python3 tools/validate_publication_intent.py\n          python3 tools/validate_release_manifest.py \\\n            candidate/manifest.json \\\n            --upstream-tag "$UPSTREAM_TAG" \\\n            --upstream-commit "$UPSTREAM_COMMIT" \\\n            --compatibility-tag "$COMPATIBILITY_TAG" \\\n            --native-commit "$NATIVE_COMMIT" \\\n            --release-tag "$RELEASE_TAG" \\\n            --require-smoke linux/x64 \\\n            --require-smoke windows/x64 \\\n            --require-smoke macos/arm64\n\n')
        for required in ("github.event_name == 'workflow_dispatch'", "github.repository == 'leehack/litert-lm-native'",
                         "github.ref == 'refs/heads/main'", "github.sha == inputs.native_commit",
                         "inputs.publication_approval == 'publish'", "ref: ${{ github.sha }}", "persist-credentials: false"):
            self.assertIn(required, publish)
        for job in ("preflight", "runtime-matrix", "build-upstream-runtime", "package"):
            self.assertIn(f"needs.{job}.result == 'success'", publish)
        self.assertNotIn("environment:", publish)
        self.assertEqual(source.count("contents: write"), 1)
        self.assertLess(publish.index("python3 tools/validate_publication_intent.py"), publish.index("python3 tools/reconcile_release_tag.py --mode prepare"))
        self.assertLess(publish.index("candidate/manifest.json"), publish.index("python3 tools/reconcile_release_tag.py --mode prepare"))
        self.assertEqual(source.count("--require-smoke macos/arm64"), 4)
        self.assertIn("--candidate-dir candidate", publish)
        self.assertIn("python3 tools/publication_state.py", publish)


if __name__ == "__main__":
    unittest.main()
