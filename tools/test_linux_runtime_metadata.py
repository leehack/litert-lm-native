import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import build_upstream_runtime as build


class LinuxRuntimeMetadataTest(unittest.TestCase):
    def test_non_linux_does_not_require_patchelf(self):
        with patch.object(build.shutil, 'which', return_value=None):
            build.normalize_linux_runtime_metadata('android', 'arm64')
            with self.assertRaisesRegex(RuntimeError, 'patchelf'):
                build.normalize_linux_runtime_metadata('linux', 'x64')

    def test_dlopen_only_prebuilt_is_staged_for_normalization_and_overlay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = root / 'bin/linux/x64'
            bundle.mkdir(parents=True)
            host = bundle / build.RUNTIME_TARGETS[('linux', 'x64')]['library']
            host.write_bytes(b'\x7fELFhost')
            source = root / 'source'
            prebuilt = source / 'prebuilt' / build.PREBUILT_TARGETS[('linux', 'x64')]
            prebuilt.mkdir(parents=True)
            (prebuilt / 'libdlopen_only.so').write_bytes(b'\x7fELFraw')
            host.chmod(0o444)
            def normalize(command, cwd):
                self.assertTrue(Path(command[-1]).stat().st_mode & 0o200)
                Path(command[-1]).write_bytes(b'\x7fELFnormalized')
            with patch.object(build, 'BIN_DIR', root/'bin'), \
                 patch.object(build, 'elf_needed_libraries', return_value=[]), \
                 patch.object(build.shutil, 'which', return_value='/usr/bin/patchelf'), \
                 patch.object(build, 'run', side_effect=normalize):
                build.stage_runtime_dependencies(host, source, 'linux', 'x64')
                build.normalize_linux_runtime_metadata('linux', 'x64')
            self.assertEqual(host.stat().st_mode & 0o777, 0o444)
            # The package workflow stages raw prebuilts then overlays build output.
            merged = root / 'merged'
            shutil.copytree(prebuilt, merged)
            shutil.copytree(bundle, merged, dirs_exist_ok=True)
            self.assertEqual((merged/'libdlopen_only.so').read_bytes(), b'\x7fELFnormalized')

    @unittest.skipUnless(sys.platform == 'linux', 'requires the real Linux loader')
    def test_flat_bundle_loads_without_search_path(self):
        self.assertIsNotNone(shutil.which('patchelf'))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = root / 'linux' / 'x64'
            bundle.mkdir(parents=True)
            (root / 'dep.c').write_text('int answer(void) { return 42; }')
            (root / 'host.c').write_text('extern int answer(void); int result(void) { return answer(); }')
            subprocess.run(['cc', '-shared', '-fPIC', str(root/'dep.c'), '-o', str(bundle/'libdep.so')], check=True)
            subprocess.run(['cc', '-shared', '-fPIC', str(root/'host.c'), '-L'+str(bundle), '-ldep', '-Wl,-rpath,/missing/bazel/tree', '-o', str(bundle/'libhost.so')], check=True)
            env = {k:v for k,v in os.environ.items() if k not in ('LD_LIBRARY_PATH', 'LD_PRELOAD')}
            code = 'import ctypes,sys; lib=ctypes.CDLL(sys.argv[1]); assert lib.result()==42'
            command = [sys.executable, '-c', code, str(bundle/'libhost.so')]
            self.assertNotEqual(subprocess.run(command, env=env, capture_output=True).returncode, 0)
            with patch.object(build, 'BIN_DIR', root):
                build.normalize_linux_runtime_metadata('linux', 'x64')
            subprocess.run(command, env=env, check=True)
            # Both metadata corrections survive a repeated packaging pass.
            with patch.object(build, 'BIN_DIR', root):
                build.normalize_linux_runtime_metadata('linux', 'x64')
            subprocess.run(command, env=env, check=True)
            for name in ('libdep.so','libhost.so'):
                self.assertEqual(subprocess.check_output(['patchelf','--print-soname',str(bundle/name)],text=True).strip(),name)
                self.assertEqual(subprocess.check_output(['patchelf','--print-rpath',str(bundle/name)],text=True).strip(),'$ORIGIN')
