#!/usr/bin/env python3
"""Branch-only qualification of immutable v0.19.0 Windows candidate bytes."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
import zipfile

NATIVE_COMMIT = 'f173fe9b18a30fdc23cc896be27a36bf85657921'
SOURCE = {
    'runId': 41809780904,
    'runAttempt': 1,
    'artifactId': 13315304185,
    'digest': 'sha256:d614a42da10e52db342999f6391c29b566f1b9cc4e7afce7d2320c032894877f',
}
OUTER_SIZE = 757916942
MANIFEST_SHA = 'bd6f67c047bbd853fd962d363e0507c043be0658c00502b4e486b02c27107871'
ARCHIVE = 'litert-lm-native-runtime-windows-x64-v0.19.0.tar.gz'
ARCHIVE_SHA = '77a2f84a342d1341cecb9a12470bee35ff3eb200eecbbb7ff3294ed099422a17'
ARCHIVE_SIZE = 37060575
LIBRARY_SHA = '636f44808e07f089d1b46afb6b2dc0b322e02c7f1eebb6b7ea660e661622ced8'
ARTIFACT_NAME = 'release-candidate-v0.19.0-litert-v019-private-protobuf-20261104'
LOG_LIMIT = 256 * 1024


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def extract_candidate(outer: Path, destination: Path) -> tuple[dict, Path]:
    require(outer.stat().st_size == OUTER_SIZE, 'candidate ZIP size mismatch')
    require('sha256:' + sha256(outer) == SOURCE['digest'], 'candidate ZIP digest mismatch')
    selected = {'manifest.json', 'release/' + ARCHIVE}
    with zipfile.ZipFile(outer) as zipped:
        names = set()
        total = 0
        for item in zipped.infolist():
            path = PurePosixPath(item.filename)
            mode = item.external_attr >> 16
            require(item.filename.casefold() not in names, 'duplicate candidate entry')
            names.add(item.filename.casefold())
            require(not path.is_absolute() and '..' not in path.parts
                    and '\\' not in item.filename and ':' not in item.filename
                    and path.as_posix() == item.filename.rstrip('/')
                    and not stat.S_ISLNK(mode) and not item.flag_bits & 1
                    and stat.S_IFMT(mode) in (0, stat.S_IFREG, stat.S_IFDIR),
                    'unsafe candidate entry')
            total += item.file_size
            require(total <= 20 * 1024**3, 'candidate extraction budget exceeded')
        require(selected <= set(zipped.namelist()), 'candidate Windows payload absent')
        for name in selected:
            target = destination / PurePosixPath(name).name
            with zipped.open(name) as source, target.open('xb') as output:
                while block := source.read(1024 * 1024):
                    output.write(block)
    manifest_path = destination / 'manifest.json'
    require(sha256(manifest_path) == MANIFEST_SHA, 'manifest digest mismatch')
    manifest = json.loads(manifest_path.read_text())
    require(manifest['native'] == {'commit': NATIVE_COMMIT,
                                 'repository': 'leehack/litert-lm-native'},
            'manifest native identity mismatch')
    archive = destination / ARCHIVE
    require(archive.stat().st_size == ARCHIVE_SIZE and sha256(archive) == ARCHIVE_SHA,
            'Windows archive size or digest mismatch')
    return manifest, archive


def extract_runtime(archive: Path, manifest: dict, destination: Path) -> dict[str, str]:
    artifacts = [a for a in manifest['artifacts']
                 if a.get('platform') == 'windows' and a.get('arch') == 'x64']
    expected = {a['path'].removeprefix('bin/'): a['sha256'] for a in artifacts}
    require(len(expected) == len(artifacts) == 13, 'Windows manifest library inventory mismatch')
    require(expected.get('windows/x64/LiteRtLm.dll') == LIBRARY_SHA,
            'primary Windows DLL identity mismatch')
    licenses = {'windows/x64/DXC-LICENSE-' + suffix + '.txt'
                for suffix in ('LLVM', 'MS', 'MIT')}
    with tarfile.open(archive, 'r:gz') as tar:
        members = tar.getmembers()
        names = set()
        for item in members:
            require(item.name.casefold() not in names, 'duplicate Windows archive entry')
            names.add(item.name.casefold())
            require((item.isdir() and item.name == 'windows/x64') or
                    (item.isfile() and item.name in set(expected) | licenses),
                    'unexpected Windows archive entry')
        files = {item.name for item in members if item.isfile()}
        require(files == set(expected) | licenses, 'incomplete Windows archive')
        require(sum(item.size for item in members) < 256 * 1024**2,
                'Windows extraction budget exceeded')
        for item in members:
            if item.isfile():
                target = destination / item.name
                target.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(item) as source, target.open('xb') as output:
                    while block := source.read(1024 * 1024):
                        output.write(block)
    actual = {name: sha256(destination / name) for name in expected}
    require(actual == expected, 'Windows library digest mismatch')
    return actual


def run_check(command: list[str], env: dict, directory: Path) -> dict:
    # File-backed capture keeps native diagnostics out of the Actions log and bounds proof size.
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(command, env=env, cwd=directory, stdout=stdout, stderr=stderr)
        timed_out = False
        try:
            code = process.wait(timeout=1200)
        except subprocess.TimeoutExpired:
            timed_out = True
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            process.wait(timeout=30)
            code = process.returncode
        def read_log(stream):
            size = stream.tell()
            stream.seek(0)
            return {'text': stream.read(LOG_LIMIT).decode('utf-8', errors='replace'),
                    'bytes': size, 'truncated': size > LOG_LIMIT}
        return {'command': command, 'exitCode': code, 'timedOut': timed_out,
                'stdout': read_log(stdout), 'stderr': read_log(stderr)}


def main() -> int:
    workspace = Path(os.environ['GITHUB_WORKSPACE']).resolve()
    trusted = workspace / 'trusted'
    require(subprocess.check_output(['git', '-C', str(trusted), 'rev-parse', 'HEAD'],
                                    text=True).strip() == NATIVE_COMMIT,
            'trusted tooling checkout mismatch')
    sys.path.insert(0, str(trusted / 'tools'))
    from candidate_promotion import api, validate_metadata
    from download_utils import download_to_path
    from qualify_sentencepiece_bpe_null import MODEL_URL, MODEL_SHA
    proof_dir = workspace / 'windows-text-proof'
    proof_dir.mkdir()
    proof = {'runtimeNativeCommit': NATIVE_COMMIT,
             'harnessCommit': os.environ['GITHUB_SHA'],
             'harnessRunId': os.environ['GITHUB_RUN_ID'],
             'harnessRunAttempt': os.environ['GITHUB_RUN_ATTEMPT'],
             'candidate': SOURCE, 'checks': [], 'stage': 'metadata', 'result': 'fail'}
    try:
        env = dict(os.environ, NATIVE_COMMIT=NATIVE_COMMIT, RELEASE_TAG='v0.19.0',
                   CORRELATION_ID='litert-v019-private-protobuf-20261104')
        try:
            run = api(f"actions/runs/{SOURCE['runId']}")
            artifact = api(f"actions/artifacts/{SOURCE['artifactId']}")
            workflow = api('actions/workflows/native_release.yml')
            validate_metadata(SOURCE, run, artifact, workflow, env, datetime.now(timezone.utc))
            require(artifact['name'] == ARTIFACT_NAME and artifact['size_in_bytes'] == OUTER_SIZE,
                    'candidate artifact metadata mismatch')
        except Exception:
            raise RuntimeError('candidate metadata verification failed') from None
        proof['artifactMetadata'] = {k: artifact[k] for k in
                                     ('id', 'name', 'digest', 'size_in_bytes', 'expired', 'expires_at')}
        with tempfile.TemporaryDirectory() as temporary:
            staging = Path(temporary)
            proof['stage'] = 'candidate-download'
            outer = staging / 'candidate.zip'
            with outer.open('wb') as output:
                result = subprocess.run(['gh', 'api',
                    f"repos/leehack/litert-lm-native/actions/artifacts/{SOURCE['artifactId']}/zip"],
                    stdout=output, stderr=subprocess.DEVNULL, timeout=600, check=False)
            require(result.returncode == 0, 'candidate ZIP download failed')
            proof['stage'] = 'candidate-verification'
            manifest, archive = extract_candidate(outer, staging)
            runtime = staging / 'runtime'
            proof['libraryHashes'] = extract_runtime(archive, manifest, runtime)
            proof['manifestSha256'] = MANIFEST_SHA
            proof['archive'] = {'name': ARCHIVE, 'size': ARCHIVE_SIZE, 'sha256': ARCHIVE_SHA}
            # The Actions token is needed only for authenticated candidate reads.
            os.environ.pop('GH_TOKEN', None)
            os.environ.pop('GITHUB_TOKEN', None)
            proof['stage'] = 'model-download'
            model = staging / 'Qwen3-0.6B.litertlm'
            download_to_path(MODEL_URL, model, headers={'User-Agent': 'litert-lm-native-qualification'},
                             label=model.name, expected_sha256=MODEL_SHA, attempts=1,
                             deadline_seconds=600)
            require(sha256(model) == MODEL_SHA, 'model digest mismatch')
            proof['model'] = {'fileName': model.name, 'sha256': sha256(model), 'size': model.stat().st_size}
            child_env = dict(os.environ)
            child_env['PATH'] = str(runtime / 'windows/x64') + os.pathsep + child_env['PATH']
            library = str(runtime / 'windows/x64/LiteRtLm.dll')
            for tool, arguments in [('litert_lm_chat_smoke.py', []),
                                    ('litert_lm_cpu_threads_probe.py', ['--threads', '4'])]:
                proof['stage'] = tool
                command = [sys.executable, str(trusted / 'tools' / tool),
                           '--library', library, '--model', str(model), *arguments]
                result = run_check(command, child_env, trusted)
                proof['checks'].append(result)
                require(result['exitCode'] == 0 and not result['timedOut'], f'{tool} failed')
            proof['stage'] = 'complete'
            proof['result'] = 'pass'
        return 0
    except Exception as error:
        # Error text may come from HTTP redirects; retain a safe category only.
        proof['failureType'] = type(error).__name__
        print('Windows text qualification failed; inspect bounded proof.', file=sys.stderr)
        return 1
    finally:
        (proof_dir / 'qualification.json').write_text(json.dumps(proof, indent=2) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
