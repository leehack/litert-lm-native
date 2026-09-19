import copy
import itertools
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from qualification_scope import MATRIX, changed_paths, results_ok, select
from validate_affected_candidate import validate
from validate_runtime_artifacts import required_runtime_artifacts


class ScopeTest(unittest.TestCase):
    def test_full_matrix_preserved_for_shared_unknown_release_and_native(self):
        self.assertEqual(len(MATRIX),9)
        for paths in ([], ['native/bridge/litert_lm_bridge.c'], ['tools/build_upstream_runtime.py'],
                      ['tools/prebuilt_overrides.py'], ['tools/package_release.py'],
                      ['tools/package_apple_xcframeworks.py'], ['.github/workflows/native_release.yml'],
                      ['.github/workflows/pr_release_qualification.yml'], ['new.lock'],
                      ['tools/new_test.py'], ['prebuilt/windows/new.dll'], ['patches/fix.patch']):
            with self.subTest(paths=paths):
                scope=select(paths)
                self.assertEqual(scope['full'],'true')
                self.assertEqual(scope['matrix']['include'],MATRIX)
                self.assertEqual(len(scope['qwen_matrix']['include']),3)

    def test_known_tests_docs_only_and_platform_unions(self):
        scope=select(['tools/test_build_upstream_runtime.py','docs/guide.md'])
        self.assertEqual(scope['native'],'false')
        self.assertEqual(scope['qwen'],'false')
        for path,platform in [('tools/package_macos_runtime.py','macos'),('tools/macos_runtime_identity.py','macos'),('tools/package_ios_runtime.py','ios')]:
            with self.subTest(path=path):
                scope=select([path,'README.md'])
                self.assertEqual(scope['full'],'false')
                self.assertEqual(scope['matrix']['include'],[row for row in MATRIX if row['platform']==platform])
                self.assertEqual(scope['qwen'],'true' if platform=='macos' else 'false')
        self.assertEqual(select(['tools/package_ios_runtime.py','tools/package_macos_runtime.py'])['platforms'],['ios','macos'])
        self.assertEqual(select(['tools/package_ios_runtime.py','tools/build_upstream_runtime.py'])['full'],'true')

    def test_partial_apple_candidates_keep_real_xcframework_gate(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/pr_release_qualification.yml').read_text()
        gate = workflow.split('      - name: Qualify Apple SwiftPM archives\n', 1)[1].split('      - name:', 1)[0]
        self.assertNotIn('if:', gate)
        self.assertIn('python3 tools/package_apple_xcframeworks.py', gate)
        for platform, label in [('ios', 'iOS'), ('macos', 'macOS')]:
            removal = workflow.split(f'      - name: Exclude unselected {label} prebuilts\n', 1)[1].split('      - name:', 1)[0]
            self.assertIn("needs.scope.outputs.full != 'true'", removal)
            self.assertIn(f"!contains(fromJSON(needs.scope.outputs.platforms), '{platform}')", removal)
            self.assertIn(f'run: rm -rf bin/{platform}', removal)
            self.assertLess(workflow.index(f'Exclude unselected {label} prebuilts'), workflow.index('Qualify Apple SwiftPM archives'))

    def test_all_aggregate_states_fail_closed(self):
        names=['scope','preflight','tokenizer-compatibility','build','verify','qwen-inference']
        for native,qwen in [('false','false'),('true','false'),('true','true')]:
            for states in itertools.product(['success','failure','cancelled','skipped'],repeat=6):
                needs={name:{'result':state} for name,state in zip(names,states)}
                needs['scope']['outputs']={'native':native,'qwen':qwen}
                expected=['success','success']+(['success']*3 if native=='true' else ['skipped']*3)+['success' if qwen=='true' else 'skipped']
                self.assertEqual(results_ok(needs),list(states)==expected)
        self.assertFalse(results_ok({}))

    def test_real_git_rename_delete_and_unavailable_ref(self):
        with tempfile.TemporaryDirectory() as temp:
            def git(*args):
                return subprocess.check_output(['git','-C',temp,*args],stderr=subprocess.DEVNULL).decode().strip()
            git('init');git('config','user.email','fixture@example.test');git('config','user.name','Fixture')
            root=Path(temp);(root/'native').mkdir();(root/'docs').mkdir()
            (root/'native/source.c').write_text('source');(root/'README.md').write_text('docs')
            git('add','.');git('commit','-m','base');base=git('rev-parse','HEAD');old=Path.cwd()
            try:
                os.chdir(temp);git('mv','native/source.c','docs/source.md');git('commit','-m','rename')
                paths=changed_paths(base);self.assertIn('native/source.c',paths);self.assertEqual(select(paths)['full'],'true')
                ref=git('rev-parse','HEAD');(root/'new.lock').write_text('dep');git('add','.');git('commit','-m','dep');dep=git('rev-parse','HEAD')
                self.assertEqual(select(changed_paths(ref))['full'],'true')
                git('rm','new.lock');git('commit','-m','delete');self.assertEqual(select(changed_paths(dep))['full'],'true')
                with self.assertRaises(subprocess.CalledProcessError):changed_paths('bad-ref')
            finally:os.chdir(old)

    def test_partial_artifact_and_smoke_contract_rejects_omissions(self):
        rows=[row for row in MATRIX if row['platform']=='ios']
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for path in required_runtime_artifacts('v0.17.0',include_official_assets=False):
                if path.parts[1]=='ios':
                    file=root/path;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(b'fixture')
            with patch('validate_affected_candidate.load_smoke_evidence',return_value=[]), patch('validate_affected_candidate.validate_elf_dependencies') as elf, patch('validate_affected_candidate.validate_macho_dependencies') as macho:
                validate(root,rows,'v0.17.0','upstream','native','v0.17.0')
                elf.assert_called_once();macho.assert_called_once()
                for bad in ([],rows[:1],rows+rows, [{'platform':'unknown'}]):
                    with self.assertRaises(ValueError):validate(root,bad,'v0.17.0','upstream','native','v0.17.0')
                missing=root/'bin/ios/arm64/LiteRtLm.framework/LiteRtLm';missing.unlink()
                with self.assertRaises(ValueError):validate(root,rows,'v0.17.0','upstream','native','v0.17.0')
                missing.write_bytes(b'fixture')
                with patch('validate_affected_candidate.load_smoke_evidence',return_value=[{'platform':'macos','arch':'arm64'}]):
                    with self.assertRaises(ValueError):validate(root,rows,'v0.17.0','upstream','native','v0.17.0')


if __name__=='__main__':unittest.main()
