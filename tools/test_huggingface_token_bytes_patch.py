from __future__ import annotations

import hashlib
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import huggingface_token_bytes_patch as carry
from asr_overlap_patch import source_patch_manifest
from qualify_huggingface_token_bytes import qualify, vocabulary_fixture

REPO = Path(__file__).resolve().parents[1]


class HuggingFaceTokenBytesPatchTest(unittest.TestCase):
    def test_unknown_releases_need_a_new_byte_contract_decision(self) -> None:
        for tag in ("v0.17.0", "v0.18.1"):
            self.assertFalse(carry.require_token_bytes_patch_decision(tag))
            self.assertEqual(carry.token_bytes_patch_manifest(tag), [])
        self.assertTrue(carry.require_token_bytes_patch_decision("v0.19.0"))
        for tag in ("v0.19.2", "v0.20.0", "main"):
            with self.subTest(tag=tag), self.assertRaisesRegex(RuntimeError, "no explicit decision"):
                carry.require_token_bytes_patch_decision(tag)

    def test_patch_targets_and_manifest_pin_the_same_exact_sources(self) -> None:
        text = (REPO / carry.PATCH_PATH).read_text()
        self.assertEqual(set(re.findall(r"^\+\+\+ b/(\S+)$", text, re.MULTILINE)), set(carry.SOURCES))
        self.assertNotIn("sentencepiece_tokenizer", text)
        records = carry.token_bytes_patch_manifest("v0.19.0")
        self.assertEqual({entry["source"] for entry in records}, set(carry.SOURCES))
        self.assertTrue(all(entry["sha256"] == hashlib.sha256(
            (REPO / carry.PATCH_PATH).read_bytes()).hexdigest() for entry in records))
        self.assertEqual([entry for entry in source_patch_manifest("v0.19.0")
                          if entry["id"] == "huggingface-token-bytes"], records)

    def test_packaged_grammar_controls_reject_incomplete_identity_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "require source, tokenizer"):
                qualify(Path(temp), runtime_library=Path("unused-library"))

    def test_mixed_or_unknown_source_is_refused_before_git_apply(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sources = {"one": (hashlib.sha256(b"pre").hexdigest(), hashlib.sha256(b"post").hexdigest()),
                       "two": (hashlib.sha256(b"pre").hexdigest(), hashlib.sha256(b"post").hexdigest())}
            for name in sources:
                (root / name).write_bytes(b"post")
            with patch.object(carry, "SOURCES", sources), patch.object(carry.subprocess, "run") as run:
                carry.apply(root, "v0.19.0")
                run.assert_not_called()
                for contents in (b"pre", b"unrecognized"):
                    (root / "one").write_bytes(contents)
                    with self.assertRaisesRegex(RuntimeError, "source changed"):
                        carry.apply(root, "v0.19.0")
                    run.assert_not_called()

    def test_successful_git_apply_must_match_every_postimage(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "one").write_bytes(b"pre")
            sources = {"one": (hashlib.sha256(b"pre").hexdigest(), hashlib.sha256(b"post").hexdigest())}
            with patch.object(carry, "SOURCES", sources), patch.object(carry.subprocess, "run"):
                with self.assertRaisesRegex(RuntimeError, "postimage mismatch"):
                    carry.apply(root, "v0.19.0")

    def test_reference_uses_special_ids_and_keeps_partial_utf8_and_all_slots(self) -> None:
        fixture = vocabulary_fixture({"model": {"vocab": {"Ã": 0, "©": 1, "Ā": 2}},
                                      "decoder": {"type": "ByteLevel"},
                                      "added_tokens": [{"id": 3, "content": "Ġ", "special": True},
                                                       {"id": 4, "content": "Ġ", "special": False}]})
        self.assertEqual([entry["id"] for entry in fixture["tokens"]], list(range(5)))
        self.assertEqual([entry["hex"] for entry in fixture["tokens"]], ["c3", "a9", "00", "c4a0", "20"])
        self.assertEqual([entry["special"] for entry in fixture["tokens"]], [False, False, False, True, False])
        with self.assertRaisesRegex(ValueError, "contiguous"):
            vocabulary_fixture({"model": {"vocab": {"x": 2}}})


if __name__ == "__main__":
    unittest.main()
