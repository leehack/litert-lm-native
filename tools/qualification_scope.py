#!/usr/bin/env python3
"""PR qualification selection; unknown/common inputs retain the exact full matrix."""
import json
import os
from pathlib import Path
import subprocess

MATRIX = [{'os': 'ubuntu-latest', 'platform': 'linux', 'arch': 'x64', 'jobs': '3', 'bazel_output_root': '.bazel-output-root', 'timeout_minutes': 90}, {'os': 'ubuntu-24.04-arm', 'platform': 'linux', 'arch': 'arm64', 'jobs': '3', 'bazel_output_root': '.bazel-output-root', 'timeout_minutes': 90}, {'os': 'windows-latest', 'platform': 'windows', 'arch': 'x64', 'jobs': '3', 'bazel_output_root': 'C:/bzl', 'timeout_minutes': 120}, {'os': 'ubuntu-latest', 'platform': 'android', 'arch': 'arm64', 'jobs': '3', 'bazel_output_root': '.bazel-output-root', 'timeout_minutes': 90}, {'os': 'ubuntu-latest', 'platform': 'android', 'arch': 'x64', 'jobs': '3', 'bazel_output_root': '.bazel-output-root', 'timeout_minutes': 90}, {'os': 'macos-latest', 'platform': 'ios', 'arch': 'arm64', 'jobs': '3', 'bazel_output_root': '.bazel-output-root', 'timeout_minutes': 120}, {'os': 'macos-latest', 'platform': 'ios', 'arch': 'arm64-sim', 'jobs': '3', 'bazel_output_root': '.bazel-output-root', 'timeout_minutes': 120}, {'os': 'macos-latest', 'platform': 'macos', 'arch': 'arm64', 'jobs': '3', 'bazel_output_root': '.bazel-output-root', 'timeout_minutes': 120}, {'os': 'macos-latest', 'platform': 'macos', 'arch': 'x64', 'jobs': '3', 'bazel_output_root': '.bazel-output-root', 'timeout_minutes': 120}]
TOOLING = frozenset(['diagnostics/repair_qwen3_tokenizer.py', 'diagnostics/runner_downloads.py', 'diagnostics/test_repair_qwen3_tokenizer.py', 'diagnostics/test_runner_downloads.py', 'tests/test_release_tag_lifecycle.py', 'tools/test_build_upstream_runtime.py', 'tools/test_check_upstream_release.py', 'tools/test_download_utils.py', 'tools/test_fetch_litert_lm_asr_smoke_assets.py', 'tools/test_git_lfs_utils.py', 'tools/test_linux_runtime_metadata.py', 'tools/test_litert_lm_asr_smoke.py', 'tools/test_litert_lm_bridge.py', 'tools/test_litert_lm_symbols.py', 'tools/test_macos_runtime_identity.py', 'tools/test_macos_spm_layout.py', 'tools/test_package_ios_runtime.py', 'tools/test_package_macos_runtime.py', 'tools/test_package_release.py', 'tools/test_package_upstream_prebuilts.py', 'tools/test_prebuilt_overrides.py', 'tools/test_publication_state.py', 'tools/test_qualification_scheduling.py', 'tools/test_release_readback.py', 'tools/test_release_result.py', 'tools/test_release_version_policy.py', 'tools/test_runtime_dependency_utils.py', 'tools/test_upstream_archive.py', 'tools/test_validate_publication_intent.py', 'tools/test_validate_release_manifest.py', 'tools/test_verify_qualification_source.py'])
PLATFORM_TOOLS = {
    'tools/package_macos_runtime.py': 'macos',
    'tools/macos_runtime_identity.py': 'macos',
    'tools/package_ios_runtime.py': 'ios',
}
PLATFORMS = {row['platform'] for row in MATRIX}


def select(paths):
    selected = set()
    full = not paths
    for path in paths:
        if path in PLATFORM_TOOLS:
            selected.add(PLATFORM_TOOLS[path])
        elif path in TOOLING or path in {'README.md', 'LICENSE'} or (path.startswith('docs/') and path.endswith('.md')):
            continue
        else:
            full = True
    if full:
        selected = PLATFORMS
    rows = [row for row in MATRIX if row['platform'] in selected]
    qwen = [row for row in rows if (row['platform'], row['arch']) in {('linux','x64'),('windows','x64'),('macos','arm64')}]
    return {'full': str(full).lower(), 'native': str(bool(rows)).lower(),
            'matrix': {'include': rows}, 'qwen': str(bool(qwen)).lower(),
            'qwen_matrix': {'include': qwen}, 'platforms': sorted(selected)}


def changed_paths(base, head='HEAD'):
    if not base or set(base) == {'0'}:
        return []
    data = subprocess.check_output(['git','diff','--no-renames','--name-only','-z',base,head,'--'])
    return data.decode('utf-8',errors='surrogateescape').rstrip('\0').split('\0') if data else []


def results_ok(needs):
    if set(needs) != {'scope','preflight','tokenizer-compatibility','build','verify','qwen-inference'}:
        return False
    if any(needs[key]['result'] != 'success' for key in ('scope','preflight')):
        return False
    scope=needs['scope']['outputs']
    if scope.get('native') not in ('true','false') or scope.get('qwen') not in ('true','false'):
        return False
    for key in ('tokenizer-compatibility','build','verify','qwen-inference'):
        selected = scope['qwen'] if key == 'qwen-inference' else scope['native']
        if needs[key]['result'] != ('success' if selected=='true' else 'skipped'):
            return False
    return True


if __name__ == '__main__':
    import sys
    if '--check-results' in sys.argv:
        raise SystemExit(0 if results_ok(json.loads(os.environ['NEEDS_JSON'])) else 1)
    result=select(changed_paths(os.environ.get('BASE_SHA','')))
    print(json.dumps(result))
    with Path(os.environ['GITHUB_OUTPUT']).open('a') as out:
        for key,value in result.items():
            out.write(f"{key}={json.dumps(value,separators=(',',':')) if not isinstance(value,str) else value}\n")
