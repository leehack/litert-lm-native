from __future__ import annotations

import itertools
import os
import re
import subprocess
import textwrap
import unittest
from pathlib import Path


WORKFLOW = (Path(__file__).resolve().parents[1] /
            '.github/workflows/pr_release_qualification.yml').read_text()


def job(name: str) -> str:
    return re.search(rf'^  {name}:\n(.*?)(?=^  [\w-]+:|\Z)',
                     WORKFLOW, re.M | re.S).group(1)


class QualificationSchedulingTest(unittest.TestCase):
    def test_builds_require_successful_tooling_and_tokenizer_jobs(self) -> None:
        # GitHub's default job condition is success(): failed, cancelled or
        # skipped dependencies cannot start these jobs. Guard against bypasses.
        for name, needs in (
            ('tokenizer-compatibility', 'preflight'),
            ('build', '[preflight, tokenizer-compatibility]'),
        ):
            with self.subTest(job=name):
                metadata = job(name).split('    steps:', 1)[0]
                self.assertIn(f'    needs: {needs}\n', metadata)
                self.assertNotRegex(metadata, re.compile(r'^    if:', re.M), msg='Keep default success() gating')
                self.assertNotIn('continue-on-error:', metadata)
        preflight = job('preflight')
        self.assertNotIn('continue-on-error:', preflight)
        self.assertIn('ref: ${{ github.event.pull_request.head.sha }}', preflight)
        self.assertIn("python3 -m unittest discover -s tools -p 'test_*.py'", preflight)
        self.assertIn("python3 -m unittest discover -s diagnostics -p 'test_*.py'", preflight)
        self.assertIn('python3 tests/test_release_tag_lifecycle.py', preflight)

    def test_candidate_check_reports_every_unsuccessful_prerequisite(self) -> None:
        verify = job('verify')
        metadata, steps = verify.split('    steps:\n', 1)
        self.assertIn('name: Verify nine-platform candidate', metadata)
        self.assertIn('needs: [preflight, tokenizer-compatibility, build]', metadata)
        self.assertIn('    if: always()\n', metadata)
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
        self.assertIn('    needs: verify\n', job('qwen-inference'))


if __name__ == '__main__':
    unittest.main()
