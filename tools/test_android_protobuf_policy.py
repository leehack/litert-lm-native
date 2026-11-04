from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import build_upstream_runtime as builder

import android_protobuf_policy as policy
from litert_lm_symbols import (
    ANDROID_OPENCL_SAMPLER_SYMBOLS,
    required_bridge_symbols,
    required_c_api_symbols,
)
from runtime_dependency_utils import elf_exported_symbols, elf_has_global_flag
from test_runtime_dependency_utils import write_elf_with_exports
from validate_runtime_dependencies import validate_elf_dependencies

ROOT = Path(__file__).resolve().parents[1]
PROTOBUF_OBJECT = '_ZN6google8protobuf8internal26fixed_address_empty_stringE'


def runtime_link_options(platform: str, c_api_v1: bool) -> list[str]:
    """Evaluate the wrapper's selects with the selected platform/define pair."""
    settings = {}
    binaries = {}

    def select(choices):
        matches = []
        for label, value in choices.items():
            if label == '//conditions:default':
                continue
            if label == '@platforms//os:' + platform:
                matches.append(value)
            if label.startswith(':'):
                setting = settings[label[1:]]
                if (all(constraint == '@platforms//os:' + platform for constraint in setting.get('constraint_values', []))
                    and all(c_api_v1 and key == 'litert_lm_c_api_v1' and value == 'true'
                            for key, value in setting.get('define_values', {}).items())):
                    matches.append(value)
        if len(matches) > 1:
            raise AssertionError('ambiguous wrapper select')
        return matches[0] if matches else choices['//conditions:default']

    def config_setting(**kwargs):
        settings[kwargs['name']] = kwargs

    def cc_binary(**kwargs):
        binaries[kwargs['name']] = kwargs

    ignore = lambda **kwargs: None
    namespace = dict(package=ignore, cc_library=ignore, cc_test=ignore,
                     exports_files=lambda *args: None, config_setting=config_setting,
                     select=select, cc_binary=cc_binary)
    build = ROOT / 'native/bridge/BUILD.bazel'
    exec(compile(build.read_text(), str(build), 'exec'), namespace)
    binary = binaries['libLiteRtLm.so']
    inputs = binary['additional_linker_inputs']
    options = binary['linkopts']
    for option in options:
        location = re.search(r'\$\(location ([^)]+)\)', option)
        if location:
            if location[1] not in inputs:
                raise AssertionError('version script missing from linker inputs')
    return [re.sub(r'\$\(location ([^)]+)\)', lambda match: str(ROOT / 'native/bridge' / match[1]), option)
            for option in options]


class AndroidProtobufPolicyTest(unittest.TestCase):
    def test_compatibility_context_cannot_silently_skip_policy(self):
        for tag in ('', 'g' + 'a' * 12, 'v0.19.0-1'):
            with self.subTest(tag=tag), self.assertRaisesRegex(ValueError, 'compatibility tag'):
                policy.requires_private_protobuf(tag)
        self.assertFalse(policy.requires_private_protobuf('v0.18.0'))
        self.assertTrue(policy.requires_private_protobuf('v0.19.0'))

    def test_link_policy_requires_android_and_c_api_v1(self):
        self.assertEqual(runtime_link_options('android', True),
                         ['-Wl,--version-script=' + str(ROOT / 'native/bridge/android_private_protobuf.lds')])
        for platform, c_api in (('android', False), ('linux', True), ('linux', False), ('macos', True), ('windows', True)):
            with self.subTest(platform=platform, c_api=c_api):
                self.assertEqual(runtime_link_options(platform, c_api), [])

    def test_defined_global_weak_unique_and_hidden_protobuf_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = Path(tmp) / 'libLiteRtLm.so'
            for binding, visibility in ((1, 0), (2, 0), (10, 0), (1, 2)):
                with self.subTest(binding=binding, visibility=visibility):
                    write_elf_with_exports(library, [PROTOBUF_OBJECT])
                    data = bytearray(library.read_bytes())
                    # The last fixture entry is the one defined symbol (Elf64_Sym).
                    data[-20] = (binding << 4) | 1
                    data[-19] = visibility
                    library.write_bytes(data)
                    with self.assertRaisesRegex(RuntimeError, 'exposes bundled protobuf'):
                        policy.validate_android_protobuf_isolation(library, 'android', 'v0.19.0')
                    policy.validate_android_protobuf_isolation(library, 'android', 'v0.18.0')
                    policy.validate_android_protobuf_isolation(library, 'linux', 'v0.19.0')

    def test_undefined_protobuf_imports_and_local_definitions_are_not_exports(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = Path(tmp) / 'libLiteRtLm.so'
            required = [symbol.decode() for symbol in required_c_api_symbols('v0.19.0') + required_bridge_symbols('v0.19.0')]
            for binding, section in ((1, 0), (0, 1)):
                with self.subTest(binding=binding, section=section):
                    write_elf_with_exports(library, required + [PROTOBUF_OBJECT])
                    data = bytearray(library.read_bytes())
                    data[-20] = (binding << 4) | 1
                    data[-18:-16] = section.to_bytes(2, 'little')
                    library.write_bytes(data)
                    policy.validate_android_protobuf_isolation(library, 'android', 'v0.19.0')

    def test_hidden_required_public_symbol_is_not_an_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = Path(tmp) / 'libLiteRtLm.so'
            required = [symbol.decode() for symbol in required_c_api_symbols('v0.19.0') + required_bridge_symbols('v0.19.0')]
            write_elf_with_exports(library, required)
            data = bytearray(library.read_bytes())
            data[-19] = 2
            library.write_bytes(data)
            with self.assertRaisesRegex(RuntimeError, required[-1]):
                policy.validate_android_protobuf_isolation(library, 'android', 'v0.19.0')

    def test_public_names_in_a_string_table_do_not_satisfy_exports(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = Path(tmp) / 'libLiteRtLm.so'
            write_elf_with_exports(library, [])
            library.write_bytes(library.read_bytes() + b'\0'.join(required_c_api_symbols('v0.19.0') + required_bridge_symbols('v0.19.0')))
            with self.assertRaisesRegex(RuntimeError, 'missing required public'):
                policy.validate_android_protobuf_isolation(library, 'android', 'v0.19.0')


class AndroidProtobufLinkerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        roots = [Path(os.environ[key]) for key in ('ANDROID_NDK_HOME', 'ANDROID_NDK_ROOT') if os.environ.get(key)]
        if not roots:
            roots = sorted((Path.home() / 'Library/Android/sdk/ndk').glob('*'), reverse=True)
        candidates = [path for root in roots for path in (root / 'toolchains/llvm/prebuilt').glob('*/bin/clang++')]
        if not candidates:
            if os.environ.get('ANDROID_PROTOBUF_REQUIRE_NDK') == '1':
                raise RuntimeError('Android protobuf linker tests require the configured NDK')
            raise unittest.SkipTest('Android NDK required for model-free link fixtures')
        cls.compiler = candidates[0]
        cls.readelf = cls.compiler.with_name('llvm-readelf')

    def compile(self, directory, arch, *, private=True, global_flag=True, missing=None, alignment=16384, dependency=None):
        directory.mkdir(parents=True, exist_ok=True)
        required = {symbol.decode() for symbol in required_c_api_symbols('v0.19.0') + required_bridge_symbols('v0.19.0')}
        public = required | set(ANDROID_OPENCL_SAMPLER_SYMBOLS) | {'LiteRtAcceleratorImpl'}
        self.assertFalse(any('protobuf' in symbol for symbol in public))
        source = directory / 'fixture.cc'
        source.write_text('''namespace google { namespace protobuf { namespace internal {
extern const char fixed_address_empty_string[24] = {};
int mutable_counter;
int helper() { return mutable_counter; }
}}}
extern "C" { const void* own_pointer = google::protobuf::internal::fixed_address_empty_string; }
extern "C" const void* own_object() { return google::protobuf::internal::fixed_address_empty_string; }
extern "C" int own_helper() { return google::protobuf::internal::helper(); }
namespace unrelated { int cpp_plugin_helper() { return 17; } }
''' + '\n'.join('extern "C" void ' + symbol + '() {}' for symbol in sorted(public) if symbol != missing))
        output = directory / 'libLiteRtLm.so'
        command = [str(self.compiler), '--target=' + {'arm64': 'aarch64', 'x64': 'x86_64'}[arch] + '-linux-android28',
                   '-shared', '-fPIC', '-nostdlib', '-Wl,--pack-dyn-relocs=none', '-Wl,-z,max-page-size=' + str(alignment), str(source), '-o', str(output)]
        if global_flag:
            command += ['-Wl,-z,global']
        if private:
            command += runtime_link_options('android', True)
        if dependency:
            command += ['-Wl,--no-as-needed', str(dependency)]
        subprocess.run(command, check=True, capture_output=True, text=True)
        return output

    def test_linker_localizes_own_objects_without_hiding_public_or_plugin_abi(self):
        for arch in ('arm64', 'x64'):
            with self.subTest(arch=arch), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                old = self.compile(root / 'old', arch, private=False)
                private = self.compile(root / 'bin/android' / arch, arch)
                old_exports = elf_exported_symbols(old)
                new_exports = elf_exported_symbols(private)
                self.assertIn(PROTOBUF_OBJECT, old_exports)
                self.assertEqual(new_exports, {symbol for symbol in old_exports if 'protobuf' not in symbol})
                self.assertIn('_ZN9unrelated17cpp_plugin_helperEv', new_exports)
                self.assertTrue(elf_has_global_flag(private))
                symbols = subprocess.check_output([str(self.readelf), '--symbols', str(private)], text=True)
                self.assertRegex(symbols, r'LOCAL\s+DEFAULT\s+\d+\s+' + PROTOBUF_OBJECT)
                relocations = subprocess.check_output([str(self.readelf), '--relocations', str(private)], text=True)
                self.assertNotIn('protobuf', relocations)
                self.assertIn('RELATIVE', relocations)
                with self.assertRaisesRegex(RuntimeError, 'exposes bundled protobuf'):
                    policy.validate_android_protobuf_isolation(old, 'android', 'v0.19.0')
                policy.validate_android_protobuf_isolation(private, 'android', 'v0.19.0')
                self.assertEqual(validate_elf_dependencies(root, 'v0.19.0'), 1)
                private.write_bytes(old.read_bytes())
                with self.assertRaisesRegex(SystemExit, 'exposes bundled protobuf'):
                    validate_elf_dependencies(root, 'v0.19.0')
                self.assertEqual(validate_elf_dependencies(root, 'v0.18.0'), 1)

    def test_build_entry_points_enforce_policy_before_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = self.compile(root / 'old', 'arm64', private=False)
            private = self.compile(root / 'private', 'arm64')
            for source_root in (True, False):
                for tag, output, rejected in (('v0.19.0', old, True),
                                              ('v0.19.0', private, False),
                                              ('v0.18.0', old, False)):
                    with self.subTest(source_root=source_root, tag=tag, rejected=rejected):
                        args = ['build_upstream_runtime.py', '--upstream-tag', tag,
                                '--platform', 'android', '--arch', 'arm64']
                        if source_root:
                            args += ['--source-root', str(root)]
                        with patch('sys.argv', args), \
                             patch.object(builder, 'download_upstream', return_value=root), \
                             patch.object(builder, 'build_runtime', return_value=output), \
                             patch.object(builder, 'validate_android_gpu_environment_teardown'), \
                             patch.object(builder, 'stage_runtime') as stage, \
                             patch.object(builder, 'stage_runtime_dependencies'), \
                             patch.object(builder, 'stage_runtime_overrides'), \
                             patch.object(builder, 'stage_windows_vc_runtime'):
                            if rejected:
                                with self.assertRaisesRegex(RuntimeError, 'exposes bundled protobuf'):
                                    builder.main()
                                stage.assert_not_called()
                            else:
                                self.assertEqual(builder.main(), 0)
                                stage.assert_called_once_with(output, 'android', 'arm64')

    def test_export_loss_global_alignment_and_closure_guards_remain_effective(self):
        for kwargs, diagnostic in (({'missing': 'stream_proxy_load_global'}, 'missing required public'),
                                   ({'global_flag': False}, 'DF_1_GLOBAL'),
                                   ({'alignment': 4096}, 'alignment below 16 KB')):
            with self.subTest(kwargs=kwargs), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.compile(root / 'bin/android/arm64', 'arm64', **kwargs)
                with self.assertRaisesRegex(SystemExit, diagnostic):
                    validate_elf_dependencies(root, 'v0.19.0')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dependency = self.compile(root / 'outside', 'arm64')
            self.compile(root / 'bin/android/arm64', 'arm64', dependency=dependency)
            dependency.unlink()
            with self.assertRaisesRegex(SystemExit, 'missing from the same runtime directory'):
                validate_elf_dependencies(root, 'v0.19.0')


if __name__ == '__main__':
    unittest.main()
