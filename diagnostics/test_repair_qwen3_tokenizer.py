import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock
import zlib

import repair_qwen3_tokenizer as repair


class RepairTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.model, self.tokenizer, self.output = [root / n for n in ('model', 'tokenizer', 'output')]
        self.original = bytearray(b'LITERTLM' + bytes(56) + b's' * 2048 + b'weights-stay-identical')
        self.original[16] = 4
        struct.pack_into('<Q', self.original, 24, 2112)
        self.model.write_bytes(self.original)
        self.json_bytes = json.dumps({'decoder': {'type': 'ByteLevel'}, 'text': '世界 😊'}).encode()
        self.tokenizer.write_bytes(self.json_bytes)
        constants = dict(MODEL_SHA256=hashlib.sha256(self.original).hexdigest(),
                         TOKENIZER_SHA256=hashlib.sha256(self.json_bytes).hexdigest(),
                         HEADER_SIZE=64, TOKENIZER_BEGIN=64, TOKENIZER_END=2112,
                         TYPE_FIELD=16, END_FIELD=24, MODEL_SIZE=len(self.original))
        patch = mock.patch.multiple(repair, **constants)
        patch.start()
        self.addCleanup(patch.stop)

    def test_preserves_weights_and_original_and_stores_original_json(self):
        evidence = repair.repair(self.model, self.tokenizer, self.output)
        result = self.output.read_bytes()
        self.assertEqual(self.model.read_bytes(), self.original)
        self.assertEqual(result[2112:], self.original[2112:])
        expected_header = self.original[:64]
        end = struct.unpack_from('<Q', result, 24)[0]
        expected_header[16] = 6
        struct.pack_into('<Q', expected_header, 24, end)
        self.assertEqual(result[:64], expected_header)
        self.assertEqual(struct.unpack_from('<Q', result, 64)[0], len(self.json_bytes))
        self.assertEqual(zlib.decompress(result[72:end]), self.json_bytes)
        self.assertEqual(result[end:2112], bytes(2112-end))
        self.assertEqual(evidence['output_sha256'], hashlib.sha256(result).hexdigest())

    def test_rejects_wrong_model_without_output(self):
        self.model.write_bytes(b'other model')
        with self.assertRaisesRegex(ValueError, 'Model SHA-256'):
            repair.repair(self.model, self.tokenizer, self.output)
        self.assertFalse(self.output.exists())

    def test_rejects_wrong_tokenizer_without_output(self):
        self.tokenizer.write_bytes(b'other tokenizer')
        with self.assertRaisesRegex(ValueError, 'Tokenizer SHA-256'):
            repair.repair(self.model, self.tokenizer, self.output)
        self.assertFalse(self.output.exists())

    def test_preserves_existing_output(self):
        self.output.write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError, 'new file'):
            repair.repair(self.model, self.tokenizer, self.output)
        self.assertEqual(self.output.read_bytes(), b'keep')

    def test_layout_mismatch_rejected(self):
        with mock.patch.object(repair, 'END_FIELD', 32):
            with self.assertRaisesRegex(ValueError, 'layout mismatch'):
                repair.repair(self.model, self.tokenizer, self.output)
        self.assertFalse(self.output.exists())

    def test_rejects_source_changed_during_copy(self):
        with mock.patch.object(repair.shutil, 'copyfile', side_effect=lambda src,dst: dst.write_bytes(b'changed')):
            with self.assertRaisesRegex(ValueError, 'changed'):
                repair.repair(self.model, self.tokenizer, self.output)
        self.assertFalse(self.output.exists())

    def test_header_is_read_from_verified_copy_not_racing_source(self):
        real_hash = repair.sha256
        real_copy = repair.shutil.copyfile
        def hash_then_mutate(path):
            result = real_hash(path)
            if path == self.model:
                mutated = bytearray(self.original)
                mutated[40] = 99
                path.write_bytes(mutated)
            return result
        def copy_restored_source(src, dst):
            src.write_bytes(self.original)
            return real_copy(src, dst)
        with mock.patch.object(repair, 'sha256', side_effect=hash_then_mutate), \
             mock.patch.object(repair.shutil, 'copyfile', side_effect=copy_restored_source):
            repair.repair(self.model, self.tokenizer, self.output)
        self.assertEqual(self.output.read_bytes()[40], self.original[40])

    def test_concurrent_output_is_not_overwritten(self):
        real_link = repair.os.link
        def racing_link(src, dst):
            dst.write_bytes(b'racing writer')
            real_link(src, dst)
        with mock.patch.object(repair.os, 'link', side_effect=racing_link):
            with self.assertRaises(FileExistsError):
                repair.repair(self.model, self.tokenizer, self.output)
        self.assertEqual(self.output.read_bytes(), b'racing writer')


if __name__ == '__main__':
    unittest.main()
