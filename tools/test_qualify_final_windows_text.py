from __future__ import annotations

import copy
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import qualify_final_windows_text as harness


class FinalWindowsTextTest(unittest.TestCase):
    def runtime_fixture(self, directory):
        entries = {'windows/x64/LiteRtLm.dll': b'final primary',
                   **{f'windows/x64/dependency{i}.dll': bytes([i]) for i in range(12)}}
        artifacts = [{'platform': 'windows', 'arch': 'x64', 'path': 'bin/' + name,
                      'sha256': harness.hashlib.sha256(content).hexdigest()}
                     for name, content in entries.items()]
        for suffix in ('LLVM', 'MS', 'MIT'):
            entries[f'windows/x64/DXC-LICENSE-{suffix}.txt'] = b'license'
        archive = directory / harness.ARCHIVE
        self.write_tar(archive, entries)
        return archive, {'artifacts': artifacts}, entries

    def write_tar(self, archive, entries, extra=None):
        with tarfile.open(archive, 'w:gz') as tar:
            directory = tarfile.TarInfo('windows/x64')
            directory.type = tarfile.DIRTYPE
            tar.addfile(directory)
            for name, data in entries.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            if extra:
                tar.addfile(extra)

    def test_exact_inventory_hashes_all_libraries(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            archive, manifest, _ = self.runtime_fixture(directory)
            with patch.object(harness, 'LIBRARY_SHA', manifest['artifacts'][0]['sha256']):
                hashes = harness.extract_runtime(archive, manifest, directory / 'runtime')
            self.assertEqual(len(hashes), 13)
            self.assertEqual(hashes, {a['path'][4:]: a['sha256'] for a in manifest['artifacts']})

    def test_rejects_changed_dependency(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            archive, manifest, entries = self.runtime_fixture(directory)
            entries['windows/x64/dependency4.dll'] = b'tampered'
            self.write_tar(archive, entries)
            with patch.object(harness, 'LIBRARY_SHA', manifest['artifacts'][0]['sha256']):
                with self.assertRaisesRegex(ValueError, 'library digest'):
                    harness.extract_runtime(archive, manifest, directory / 'runtime')

    def test_rejects_links_traversal_case_alias_and_missing_file_before_extract(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            archive, manifest, entries = self.runtime_fixture(directory)
            link = tarfile.TarInfo('windows/x64/untrusted.dll')
            link.type = tarfile.SYMTYPE
            link.linkname = 'LiteRtLm.dll'
            traversal = tarfile.TarInfo('../escaped')
            alias = tarfile.TarInfo('windows/x64/LITERTLM.DLL')
            for index, extra in enumerate((link, traversal, alias, None)):
                with self.subTest(index=index):
                    payload = dict(entries)
                    if extra is None:
                        payload.pop('windows/x64/dependency4.dll')
                    self.write_tar(archive, payload, extra)
                    destination = directory / f'runtime{index}'
                    with patch.object(harness, 'LIBRARY_SHA', manifest['artifacts'][0]['sha256']):
                        with self.assertRaises(ValueError):
                            harness.extract_runtime(archive, manifest, destination)
                    self.assertFalse(destination.exists())

    def candidate_fixture(self, directory, extra=None):
        archive, manifest, _ = self.runtime_fixture(directory)
        manifest['native'] = {'commit': harness.NATIVE_COMMIT,
                              'repository': 'leehack/litert-lm-native'}
        raw = json.dumps(manifest).encode()
        outer = directory / 'candidate.zip'
        with zipfile.ZipFile(outer, 'w') as zipped:
            zipped.writestr('manifest.json', raw)
            zipped.write(archive, 'release/' + harness.ARCHIVE)
            zipped.writestr('release/other-platform.tar.gz', b'not extracted')
            if extra:
                zipped.writestr(*extra)
        values = {'OUTER_SIZE': outer.stat().st_size,
                  'SOURCE': dict(harness.SOURCE, digest='sha256:' + harness.sha256(outer)),
                  'MANIFEST_SHA': harness.hashlib.sha256(raw).hexdigest(),
                  'ARCHIVE_SIZE': archive.stat().st_size,
                  'ARCHIVE_SHA': harness.sha256(archive)}
        return outer, manifest, values

    def test_only_extracts_authenticated_windows_archive_and_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            outer, manifest, values = self.candidate_fixture(directory)
            destination = directory / 'selected'
            destination.mkdir()
            with patch.multiple(harness, **values):
                actual, archive = harness.extract_candidate(outer, destination)
            self.assertEqual(actual, manifest)
            self.assertEqual({p.name for p in destination.iterdir()}, {'manifest.json', harness.ARCHIVE})
            self.assertEqual(harness.sha256(archive), values['ARCHIVE_SHA'])

    def test_authenticates_outer_manifest_and_archive_before_runtime_loading(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            outer, _, values = self.candidate_fixture(directory)
            for index, key in enumerate(('SOURCE', 'MANIFEST_SHA', 'ARCHIVE_SHA', 'ARCHIVE_SIZE')):
                with self.subTest(key=key):
                    changed = copy.deepcopy(values)
                    changed[key] = (dict(changed[key], digest='sha256:' + '0' * 64)
                                    if key == 'SOURCE' else
                                    1 if key == 'ARCHIVE_SIZE' else '0' * 64)
                    destination = directory / f'selected{index}'
                    destination.mkdir()
                    with patch.multiple(harness, **changed):
                        with self.assertRaises(ValueError):
                            harness.extract_candidate(outer, destination)
                    if key == 'SOURCE':
                        self.assertEqual(list(destination.iterdir()), [])

    def test_rejects_unsafe_or_duplicate_outer_entry_before_extract(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for index, extra in enumerate((('../escaped', b'x'),
                                           ('MANIFEST.JSON', b'alias'),
                                           ('C:/escape', b'x'),
                                           ('release\\escape', b'x'))):
                with self.subTest(extra=extra):
                    outer, _, values = self.candidate_fixture(directory, extra)
                    destination = directory / f'selected{index}'
                    destination.mkdir()
                    with patch.multiple(harness, **values):
                        with self.assertRaises(ValueError):
                            harness.extract_candidate(outer, destination)
                    self.assertEqual(list(destination.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
