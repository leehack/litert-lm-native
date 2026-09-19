from __future__ import annotations

import itertools
import os
import re
import subprocess
import textwrap
import unittest
from pathlib import Path


WORKFLOW_PATH = Path(__file__).resolve().parents[1] / '.github/workflows/pr_release_qualification.yml'
WORKFLOW = WORKFLOW_PATH.read_text()


def job(name: str) -> str:
    return re.search(rf'^  {name}:\n(.*?)(?=^  [\w-]+:|\Z)',
                     WORKFLOW, re.M | re.S).group(1)


class QualificationSchedulingTest(unittest.TestCase):
    def test_builds_require_successful_tooling_and_tokenizer_jobs(self) -> None:
        # GitHub's default job condition is success(): failed, cancelled or
        # skipped dependencies cannot start these jobs. Guard against bypasses.
        for name, needs in (
            ('tokenizer-compatibility', '[preflight, scope]'),
            ('build', '[preflight, scope, tokenizer-compatibility]'),
        ):
            with self.subTest(job=name):
                metadata = job(name).split('    steps:', 1)[0]
                self.assertIn(f'    needs: {needs}\n', metadata)
                self.assertIn("if: needs.scope.outputs.native == 'true'", metadata)
                self.assertNotIn('always()', metadata)
                self.assertNotIn('continue-on-error:', metadata)
        preflight = job('preflight')
        self.assertIn('uses: ./.github/workflows/validate.yml', preflight)
        shared = WORKFLOW_PATH.parent.joinpath('validate.yml').read_text()
        self.assertIn('  workflow_call:', shared)
        self.assertNotIn('  pull_request:', shared)
        self.assertEqual(shared.count("unittest discover -s tools -p 'test_*.py'"), 1)
        self.assertEqual(shared.count("unittest discover -s diagnostics -p 'test_*.py'"), 1)
        self.assertEqual(shared.count('python3 tests/test_release_tag_lifecycle.py'), 1)
        self.assertIn('test_linux_runtime_metadata.py', shared)
        self.assertNotIn('continue-on-error:', preflight)

    def test_candidate_check_reports_every_unsuccessful_prerequisite(self) -> None:
        verify = job('verify')
        metadata, steps = verify.split('    steps:\n', 1)
        self.assertIn('Verify nine-platform candidate', metadata)
        self.assertIn('needs: [preflight, scope, tokenizer-compatibility, build]', metadata)
        self.assertIn("    if: always() && needs.scope.outputs.native == 'true'\n", metadata)
        self.assertNotIn('continue-on-error:', verify)
        guard = steps.split('\n      - uses:', 1)[0]
        self.assertTrue(guard.startswith('      - name: Require successful qualification prerequisites\n'))
        self.assertIn('        shell: bash\n', guard)
        for env, dependency in (('PREFLIGHT', 'preflight'),
                                ('TOKENIZER', 'tokenizer-compatibility'),
                                ('BUILD', 'build')):
            self.assertIn(f'{env}_RESULT: ${{{{ needs.{dependency}.result }}}}', guard)
        script = textwrap.dedent(guard.split('        run: |\n', 1)[1])
        results = ('success', 'failure', 'cancelled', 'skipped')
        for states in itertools.product(results, repeat=3):
            with self.subTest(results=states):
                process = subprocess.run(
                    ['bash', '--noprofile', '--norc', '-eo', 'pipefail', '-c', script],
                    env={**os.environ, **dict(zip(
                        ('PREFLIGHT_RESULT', 'TOKENIZER_RESULT', 'BUILD_RESULT'), states))},
                    capture_output=True, text=True,
                )
                self.assertEqual(process.returncode == 0, states == ('success',) * 3)
        self.assertIn('    needs: [scope, verify]\n', job('qwen-inference'))


if __name__ == '__main__':
    unittest.main()
