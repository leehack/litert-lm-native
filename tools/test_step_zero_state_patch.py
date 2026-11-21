import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import step_zero_state_patch as carry
from asr_overlap_patch import source_patch_manifest


class StepZeroStatePatchTest(unittest.TestCase):
    def test_manifest_attributes_only_the_v0191_executor(self) -> None:
        self.assertEqual(carry.manifest("v0.19.0"), [])
        with self.assertRaisesRegex(RuntimeError, "no explicit decision"):
            carry.manifest("v0.19.2")
        self.assertEqual(source_patch_manifest("v0.19.1")[-1], {
            "id": "step-zero-state",
            "path": carry.PATCH_PATH,
            "sha256": hashlib.sha256(carry.PATCH.read_bytes()).hexdigest(),
            "source": carry.SOURCE,
            "preimageSha256Lf": carry.PREIMAGE,
            "postimageSha256Lf": "b2c73fbcb400654072bf926dbaa3b81e252acf750f8fc1a60dd0b51df84d890d",
            "scope": "source-built runtimes only; excludes official upstream prebuilts",
        })
        headers = [line for line in carry.PATCH.read_text().splitlines()
                   if line.startswith(("--- ", "+++ "))]
        self.assertEqual(headers, [f"--- a/{carry.SOURCE}", f"+++ b/{carry.SOURCE}"])

    def test_version_bound_application_is_idempotent_and_rejects_wrong_source(self) -> None:
        before = b"old executor\n"
        after = b"new executor\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / carry.SOURCE
            source.parent.mkdir(parents=True)
            patch_path = root / "fixture.patch"
            patch_path.write_text(f"--- a/{carry.SOURCE}\n+++ b/{carry.SOURCE}\n"
                                  "@@ -1 +1 @@\n-old executor\n+new executor\n")
            with (patch.object(carry, "PATCH", patch_path),
                  patch.object(carry, "PREIMAGE", hashlib.sha256(before).hexdigest()),
                  patch.object(carry, "POSTIMAGE", hashlib.sha256(after).hexdigest())):
                source.write_bytes(before)
                carry.apply(root, "v0.19.1")
                self.assertEqual(source.read_bytes(), after)
                with patch.object(carry.subprocess, "run") as run:
                    carry.apply(root, "v0.19.1")
                    source.write_bytes(b"unknown executor\n")
                    with self.assertRaisesRegex(RuntimeError, "source changed"):
                        carry.apply(root, "v0.19.1")
                    run.assert_not_called()

    def test_application_requires_the_exact_postimage(self) -> None:
        with (patch.object(carry, "_digest", side_effect=[carry.PREIMAGE, "wrong"]),
              patch.object(carry.subprocess, "run")):
            with self.assertRaisesRegex(RuntimeError, "postimage mismatch"):
                carry.apply(Path("."), "v0.19.1")
