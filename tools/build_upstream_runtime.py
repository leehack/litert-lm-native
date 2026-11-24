#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

from android_automatic_gpu_patch import (
    apply as patch_android_automatic_gpu,
    executor_compile_query,
    verify_executor_compile_actions,
)
from android_protobuf_policy import validate_android_protobuf_isolation
from android_gpu_safety_patch import apply as apply_android_gpu_safety
from asr_overlap_patch import (
    MERGER_SOURCE,
    PATCH_PATH as ASR_PATCH_PATH,
    POSTIMAGE_SHA256 as ASR_POSTIMAGE,
    PREIMAGE_SHA256 as ASR_PREIMAGE,
    source_sha256,
)
from bazel_repository_provenance import release_workspace_rc, verify_resolved_archives
from ios_runtime_policy import FST_DEFINE, provider_free_ios, validate_ios_directory, verify_upstream_fst_gate
from download_utils import download_to_path
from git_lfs_utils import materialize_git_lfs_libraries
from gpu_environment_teardown import find_ndk_llvm_objdump, validate_library
from huggingface_token_bytes_patch import apply as patch_huggingface_token_bytes
from litert_lm_symbols import (
    android_static_gpu_sampler_symbols,
    in_process_litert_abi_version,
    required_bridge_symbols,
    required_c_api_symbols,
)
from litert_stage_spatial_tensors_patch import (
    LITERT_REF as STAGING_LITERT_REF,
    LITERT_ARCHIVE_SHA256 as STAGING_LITERT_SHA256,
    PATCH_PATH as STAGING_PATCH_PATH,
    SOURCES as STAGING_SOURCES,
)
from litert_xnnpack_fresh_cache_patch import (
    PATCH_PATH as FRESH_CACHE_PATCH_PATH,
    SOURCES as FRESH_CACHE_SOURCES,
)
from macos_runtime_identity import normalize_macos_runtime_identity
from macos_runtime_policy import UNSUPPORTED_MACOS_ARCH_REASON
from package_upstream_prebuilts import apply_prebuilt_overrides
from runtime_dependency_utils import (
    elf_exported_symbols,
    elf_has_global_flag,
    elf_needed_libraries,
    is_elf,
    is_system_needed,
)
from source_patch_utils import active_source_carries, apply_source_patch
from stream_finish_reason_patch import (
    BAZEL_DEFINE as FINISH_REASON_DEFINE,
    PATCH_PATH as FINISH_REASON_PATCH_PATH,
    SOURCES as FINISH_REASON_SOURCES,
)
from windows_dxc import stage_windows_dxc
from windows_engine_fd_patch import apply as patch_windows_engine_fd
import windows_runtime
from xnnpack_pf32_sme2_patch import (
    TENSORFLOW_REF,
    XNNPACK_SHA256,
    XNNPACK_COMMIT,
    declare_patched_xnnpack,
    SOURCES as XNNPACK_PF32_SOURCES,
    verify_patched_xnnpack_archive,
)
from xnnpack_pqs8_qc4w_sme2_patch import SOURCES as XNNPACK_QC4W_SOURCES
from upstream_archive import github_source_archive_url

REPO_ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"
BRIDGE_PACKAGE_ROOT = REPO_ROOT / "native"
UPSTREAM_REPO = "google-ai-edge/LiteRT-LM"
MACOS_MINIMUM_OS = "14.0"
USER_AGENT = "litert-lm-native-build"
ZLIB_URL = "https://zlib.net/fossils/zlib-1.3.1.tar.gz"
ZLIB_GITHUB_MIRROR_URL = (
    "https://github.com/madler/zlib/releases/download/v1.3.1/"
    "zlib-1.3.1.tar.gz"
)

RUNTIME_TARGETS = {
    ("android", "arm64"): {
        "bazel_target": "//bridge:libLiteRtLm.so",
        "bazel_config": "android_arm64",
        "bazel_options": [
            "--linkopt=-Wl,-z,max-page-size=16384",
            "--linkopt=-Wl,-z,common-page-size=16384",
            "--linkopt=-Wl,-z,global",
        ],
        "output": "bazel-bin/bridge/libLiteRtLm.so",
        "library": "libLiteRtLm.so",
    },
    ("android", "x64"): {
        "bazel_target": "//bridge:libLiteRtLm.so",
        "bazel_config": "android_x86_64",
        "bazel_options": [
            "--linkopt=-Wl,-z,max-page-size=16384",
            "--linkopt=-Wl,-z,common-page-size=16384",
            "--linkopt=-Wl,-z,global",
        ],
        "output": "bazel-bin/bridge/libLiteRtLm.so",
        "library": "libLiteRtLm.so",
    },
    ("ios", "arm64"): {
        "bazel_target": "//bridge:libLiteRtLm.dylib",
        "bazel_config": "ios_arm64",
        "output": "bazel-bin/bridge/libLiteRtLm.dylib",
        "library": "libLiteRtLm.dylib",
    },
    ("ios", "arm64-sim"): {
        "bazel_target": "//bridge:libLiteRtLm.dylib",
        "bazel_config": "ios_sim_arm64",
        "output": "bazel-bin/bridge/libLiteRtLm.dylib",
        "library": "libLiteRtLm.dylib",
    },
    ("linux", "arm64"): {
        "bazel_target": "//bridge:libLiteRtLm.so",
        "bazel_configs": ["linux", "linux_arm64"],
        "output": "bazel-bin/bridge/libLiteRtLm.so",
        "library": "libLiteRtLm.so",
    },
    ("linux", "x64"): {
        "bazel_target": "//bridge:libLiteRtLm.so",
        "bazel_config": "linux",
        "output": "bazel-bin/bridge/libLiteRtLm.so",
        "library": "libLiteRtLm.so",
    },
    ("macos", "arm64"): {
        "bazel_target": "//bridge:libLiteRtLm.dylib",
        "bazel_configs": ["macos", "macos_arm64"],
        "output": "bazel-bin/bridge/libLiteRtLm.dylib",
        "library": "libLiteRtLm.dylib",
    },
    ("windows", "x64"): {
        "bazel_target": "//bridge:LiteRtLm.dll",
        "bazel_config": "windows",
        "output": "bazel-bin/bridge/LiteRtLm.dll",
        "library": "LiteRtLm.dll",
    },
}

PREBUILT_TARGETS = {
    ("android", "arm64"): "android_arm64",
    ("android", "x64"): "android_x86_64",
    ("ios", "arm64"): "ios_arm64",
    ("ios", "arm64-sim"): "ios_sim_arm64",
    ("linux", "arm64"): "linux_arm64",
    ("linux", "x64"): "linux_x86_64",
    ("macos", "arm64"): "macos_arm64",
    ("windows", "x64"): "windows_x86_64",
}
LIB_SUFFIXES = (".so", ".dylib", ".dll", ".lib", ".a")


def patch_asr_untimed_overlap(source_root: Path, upstream_tag: str) -> None:
    """Carry #673 only on an audited source; require review on drift."""
    if not active_source_carries(upstream_tag):
        return
    source = source_root / MERGER_SOURCE
    digest = source_sha256(source.read_bytes())
    if digest == ASR_POSTIMAGE:
        return
    if digest != ASR_PREIMAGE:
        raise RuntimeError("ASR merger source changed; requalify untimed overlap patch")
    patch_file = BRIDGE_PACKAGE_ROOT / "bridge" / Path(ASR_PATCH_PATH).name
    apply_source_patch(source_root, patch_file, ignore_space_change=True)
    if source_sha256(source.read_bytes()) != ASR_POSTIMAGE:
        raise RuntimeError("ASR merger postimage mismatch; requalify untimed overlap patch")
    print("Applied audited untimed ASR overlap patch", flush=True)


def patch_stream_finish_reason(source_root: Path, upstream_tag: str) -> None:
    """Apply the audited terminal cause reported by the streaming bridge."""
    if not active_source_carries(upstream_tag):
        return
    sources = FINISH_REASON_SOURCES
    digests = {
        name: source_sha256((source_root / name).read_bytes())
        for name in sources
    }
    if all(digests[name] == post for name, (_, post) in sources.items()):
        return
    if any(digests[name] != pre for name, (pre, _) in sources.items()):
        raise RuntimeError(
            "Decode or conversation source changed; requalify the stream "
            "finish-reason patch")
    patch_file = REPO_ROOT / FINISH_REASON_PATCH_PATH
    apply_source_patch(source_root, patch_file, ignore_space_change=True)
    for name, (_, post) in sources.items():
        if source_sha256((source_root / name).read_bytes()) != post:
            raise RuntimeError(
                "Stream finish-reason patch postimage mismatch; requalify")
    print("Applied audited stream finish-reason patch", flush=True)


def xnnpack_postimages() -> dict[str, str]:
    """Final XNNPACK sources after both patches; the QC4W opt-out applies last."""
    return {
        name: postimage
        for sources in (
            XNNPACK_PF32_SOURCES,
            XNNPACK_QC4W_SOURCES,
        )
        for name, (_, postimage) in sources.items()
    }


def verify_xnnpack_postimages(source_root: Path) -> None:
    """Fails unless Bazel compiled the patched XNNPACK sources."""
    repository = (source_root / "bazel-out").resolve().parents[2] / "external" / "XNNPACK"
    for name, postimage in xnnpack_postimages().items():
        source = repository / name
        if not source.is_file() or source_sha256(source.read_bytes()) != postimage:
            raise RuntimeError("XNNPACK patch postimage mismatch; requalify")
    print("Verified XNNPACK PF32 rollback and PQS8/QC4W opt-out postimages", flush=True)


def verify_litert_carry_postimages(source_root: Path) -> None:
    """Fails unless Bazel used the audited LiteRT sources."""
    repository = (source_root / "bazel-out").resolve().parents[2] / "external" / "litert"
    for name, (_, postimage) in (STAGING_SOURCES | FRESH_CACHE_SOURCES).items():
        source = repository / name
        if not source.is_file() or source_sha256(source.read_bytes()) != postimage:
            raise RuntimeError(f"LiteRT carry postimage mismatch for {name}; requalify")
    print("Verified LiteRT carry postimages", flush=True)


def source_archive_path(work_dir: Path, upstream_ref: str) -> Path:
    ref_digest = hashlib.sha256(upstream_ref.encode("utf-8")).hexdigest()
    return work_dir / f"LiteRT-LM-{ref_digest}.tar.gz"


def run(
    command: list[str], cwd: Path, env: dict[str, str] | None = None, *, capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    printable = " ".join(command)
    print(f"+ {printable}", flush=True)
    windows = os.name == "nt"
    return subprocess.run(
        subprocess.list2cmdline(command) if windows else command,
        cwd=cwd, env=env, check=True, shell=windows, text=True,
        stdout=subprocess.PIPE if capture_output else None,
    )


def reject_ambiguous_workspace(source_root: Path) -> None:
    # Bazel prefers WORKSPACE.bazel, while the owner patches and verifies WORKSPACE.
    if (os.path.lexists(source_root / "WORKSPACE")
            and os.path.lexists(source_root / "WORKSPACE.bazel")):
        raise RuntimeError("Ambiguous Bazel workspace with both WORKSPACE and WORKSPACE.bazel")


def download_upstream(
    upstream_ref: str, compatibility_tag: str, work_dir: Path
) -> Path:
    require_source_build(compatibility_tag)
    archive_path = source_archive_path(work_dir, upstream_ref)
    url = github_source_archive_url(UPSTREAM_REPO, upstream_ref)
    print(f"Downloading {url}", flush=True)
    download_to_path(
        url,
        archive_path,
        headers={"User-Agent": USER_AGENT},
        label=f"LiteRT-LM {upstream_ref} source archive",
    )
    with tarfile.open(archive_path, "r:gz") as archive:
        archive.extractall(work_dir, filter="data")
    candidates = [path for path in work_dir.iterdir() if path.is_dir()]
    if len(candidates) != 1:
        raise RuntimeError(f"Expected one extracted source directory, got {candidates}")
    source_root = candidates[0]
    reject_ambiguous_workspace(source_root)
    patch_upstream_workspace(
        source_root,
        patch_xnnpack_pf32_sme2=True,
        patch_litert_carries=True,
    )
    return source_root


def verify_litert_archive_pin(workspace: str, ref: str, sha256: str, carry: str) -> None:
    archive = list(re.finditer(
        r'^http_archive\(\n    name = "litert",\n(.*?)^\)$',
        workspace, re.MULTILINE | re.DOTALL,
    ))
    if len(archive) != 1:
        raise RuntimeError(f"Expected one LiteRT archive in WORKSPACE for {carry}; requalify")
    for name, expected in (("LITERT_REF", ref), ("LITERT_SHA256", sha256)):
        assignments = list(re.finditer(rf'^{name}[ \t]*=[ \t]*(.*)$', workspace, re.MULTILINE))
        if (len(assignments) != 1 or assignments[0].group(1) != f'"{expected}"'
                or assignments[0].start() >= archive[0].start()):
            raise RuntimeError(f"Unexpected {name} for {carry}; requalify")

    # Bazel checks the downloaded bytes against this digest before applying patches.
    attributes = {
        "sha256": "LITERT_SHA256,",
        "strip_prefix": '"LiteRT-" + LITERT_REF,',
        "url": '"https://github.com/google-ai-edge/LiteRT/archive/" + LITERT_REF + ".tar.gz",',
    }
    for name, expected in attributes.items():
        values = re.findall(rf'^    {name}[ \t]*=[ \t]*(.*)$', archive[0].group(1), re.MULTILINE)
        if values != [expected]:
            raise RuntimeError(f"Unexpected LiteRT archive {name} for {carry}; requalify")


def verify_carried_dependency_pins(source_root: Path, compatibility_tag: str) -> None:
    reject_ambiguous_workspace(source_root)
    workspace = (source_root / "WORKSPACE").read_text(encoding="utf-8")
    verify_litert_archive_pin(
        workspace, STAGING_LITERT_REF, STAGING_LITERT_SHA256, "LiteRT carries",
    )
    verify_patched_xnnpack_archive(workspace, compatibility_tag)


def patch_upstream_workspace(
    source_root: Path,
    *,
    patch_xnnpack_pf32_sme2: bool = False,
    patch_litert_carries: bool = False,
) -> None:
    workspace = source_root / "WORKSPACE"
    text = workspace.read_text(encoding="utf-8")
    needle = f'    url = "{ZLIB_URL}",'
    replacement = (
        "    urls = [\n"
        f'        "{ZLIB_GITHUB_MIRROR_URL}",\n'
        f'        "{ZLIB_URL}",\n'
        "    ],"
    )
    if needle not in text:
        if ZLIB_GITHUB_MIRROR_URL not in text and (
            f'        "{ZLIB_URL}",' not in text
            or '"https://mirror.bazel.build/zlib.net/fossils/zlib-1.3.1.tar.gz"' not in text
        ):
            raise RuntimeError(f"Expected zlib URL not found in {workspace}")
    else:
        text = text.replace(needle, replacement)
    litert_patches = []
    if patch_litert_carries:
        verify_litert_archive_pin(
            text, STAGING_LITERT_REF, STAGING_LITERT_SHA256, "LiteRT carries",
        )
        litert_patches = [Path(path).name for path in (STAGING_PATCH_PATH, FRESH_CACHE_PATCH_PATH)]
    litert_archive = 'http_archive(\n    name = "litert",\n'
    litert_archive_with_patch = (
        litert_archive
        + '    patch_args = ["-p1"],\n'
        + "    patches = ["
        + ", ".join(f'"@//bridge:{name}"' for name in litert_patches)
        + "],\n"
    )
    if litert_patches and litert_archive_with_patch not in text:
        if litert_archive not in text:
            raise RuntimeError(f"Expected LiteRT archive not found in {workspace}")
        if litert_archive + "    patch_args" in text:
            raise RuntimeError(f"Unexpected LiteRT patches in {workspace}")
        text = text.replace(litert_archive, litert_archive_with_patch, 1)
    if patch_xnnpack_pf32_sme2:
        text = declare_patched_xnnpack(text)
    workspace.write_text(text, encoding="utf-8")
    print(
        "Patched upstream WORKSPACE dependencies",
        flush=True,
    )


def patch_windows_rules_android(source_root: Path) -> None:
    workspace = source_root / "WORKSPACE"
    text = workspace.read_text(encoding="utf-8")
    refs = re.findall(r'^TENSORFLOW_REF[ \t]*=[ \t]*"([0-9a-f]{40})"$', text, re.MULTILINE)
    if refs != [TENSORFLOW_REF]:
        raise RuntimeError("TensorFlow pin changed; requalify the Windows rules_android patch")

    # TensorFlow skips repos declared before tf_workspace2(). Use its archive
    # and all four source edits without its Bash/sed repository commands.
    url = "https://github.com/bazelbuild/rules_android/releases/download/v0.6.0/rules_android-v0.6.0.tar.gz"
    archive = f'''http_archive(
    name = "build_bazel_rules_android",
    patch_args = ["-p1"],
    patches = ["@//bridge:rules_android_tensorflow_v020.patch"],
    sha256 = "af84b69ab3d16dd1a41056286e6511f147a94ccea995603e13e934c915c1631c",
    strip_prefix = "rules_android-0.6.0",
    urls = [
        "https://storage.googleapis.com/mirror.tensorflow.org/{url[8:]}",
        "{url}",
    ],
)

'''
    hook = '\nload("@org_tensorflow//tensorflow:workspace2.bzl", "tf_workspace2")\n'
    declarations = re.findall(r'^\s*name\s*=\s*"build_bazel_rules_android"\s*,', text, re.MULTILINE)
    if text.count("\n" + archive + hook) == 1 and len(declarations) == 1:
        return
    if declarations or text.count(hook) != 1:
        raise RuntimeError("Unexpected Windows rules_android declaration point in WORKSPACE; requalify")
    workspace.write_text(text.replace(hook, "\n" + archive + hook, 1), encoding="utf-8")


def bazel_command() -> list[str]:
    if shutil.which("bazelisk"):
        return ["bazelisk"]
    if shutil.which("npx"):
        return ["npx", "--yes", "@bazel/bazelisk@latest"]
    if shutil.which("bazel"):
        return ["bazel"]
    raise RuntimeError("Could not find bazelisk, bazel, or npx")


def bazel_path(path: Path) -> str:
    resolved = path.resolve()
    if os.name == "nt":
        return resolved.as_posix()
    return str(resolved)


def prepare_bridge_package(source_root: Path) -> list[str]:
    if os.name != "nt":
        package_path = os.pathsep.join(
            [bazel_path(BRIDGE_PACKAGE_ROOT), bazel_path(source_root)]
        )
        return [f"--package_path={package_path}"]

    # Bazel 7.6.1 on the Windows 2025 hosted image rewrites absolute
    # --package_path entries like D:/a/... into /a/... during package loading.
    # Copying the small downstream bridge package into the extracted upstream
    # tree avoids that parser path while keeping the upstream archive untouched.
    bridge_source = BRIDGE_PACKAGE_ROOT / "bridge"
    bridge_destination = source_root / "bridge"
    if bridge_destination.exists():
        shutil.rmtree(bridge_destination)
    shutil.copytree(bridge_source, bridge_destination)
    print(f"Staged bridge package at {bridge_destination}", flush=True)
    return []


def fetch_audited_archives(
    startup: list[str], source_root: Path, bridge_options: list[str],
    resolved: Path, pins: dict[str, tuple[str, str]],
) -> None:
    # A targeted sync emits the resolved rule even with a warm repository cache.
    run([
        *startup, "sync", "--noenable_bzlmod", *bridge_options,
        *(f"--only={name}" for name in pins),
        f"--experimental_repository_resolved_file={bazel_path(resolved)}",
    ], source_root)
    result = run([*startup, "info", "--noenable_bzlmod", "output_base"], source_root, capture_output=True)
    output_base = Path(result.stdout.rstrip("\r\n"))
    if not output_base.is_absolute():
        raise RuntimeError("Bazel did not report an absolute output base")
    verify_resolved_archives(resolved, pins, output_base / "external")


def build_runtime(
    source_root: Path,
    platform: str,
    arch: str,
    upstream_tag: str,
    jobs: str | None,
    upstream_ref: str | None = None,
) -> Path:
    require_source_build(upstream_tag)
    verify_carried_dependency_pins(source_root, upstream_tag)
    if platform == "windows":
        patch_windows_rules_android(source_root)
    if platform == "android":
        patch_android_automatic_gpu(source_root, upstream_tag)
    patch_asr_untimed_overlap(source_root, upstream_tag)
    patch_stream_finish_reason(source_root, upstream_tag)
    patch_huggingface_token_bytes(source_root, upstream_tag)
    if platform == "windows":
        patch_windows_engine_fd(source_root, upstream_tag)
    else:
        apply_android_gpu_safety(source_root, upstream_tag)
    prebuilt_target = PREBUILT_TARGETS.get((platform, arch))
    if prebuilt_target is not None:
        source_dir = source_root / "prebuilt" / prebuilt_target
        materialized = materialize_git_lfs_libraries(
            source_dir,
            upstream_tag=upstream_ref or upstream_tag,
            source_root=source_root,
            suffixes=LIB_SUFFIXES,
        )
        if materialized:
            print(
                f"Materialized {materialized} pointer-backed libraries for "
                f"{platform}/{arch}",
                flush=True,
            )
    target = RUNTIME_TARGETS[(platform, arch)]
    configs = [
        f"--config={config}"
        for config in target.get("bazel_configs", [target.get("bazel_config")])
        if config
    ]
    startup = [*bazel_command(), "--nohome_rc", "--nosystem_rc"]
    output_user_root = os.environ.get("BAZEL_OUTPUT_USER_ROOT")
    if output_user_root:
        if not os.path.isabs(output_user_root):
            output_user_root = bazel_path(REPO_ROOT / output_user_root)
        elif os.name == "nt":
            output_user_root = Path(output_user_root).resolve().as_posix()
        startup.append(f"--output_user_root={output_user_root}")
    bridge_options = prepare_bridge_package(source_root)
    options = [
        *bridge_options,
        *configs,
        *target.get("bazel_options", []),
        "--define=litert_link_capi_so=true",
        "--define=resolve_symbols_in_exec=false",
        "--define=litert_lm_stream_chunk_api=true",
        "--define=litert_lm_capabilities_in_c_engine=true",
        "--define=litert_lm_asr_api=true",
        "--define=litert_lm_asr_omni_engine=true",
        "--define=litert_lm_c_api_v1=true",
        "--define=litert_lm_in_process_litert=true",
    ]
    options.append(FINISH_REASON_DEFINE)
    if platform == "macos":
        options.append(f"--macos_minimum_os={MACOS_MINIMUM_OS}")
    if platform == "ios":
        if provider_free_ios(upstream_tag):
            verify_upstream_fst_gate(source_root)
            options.append(FST_DEFINE)
        options.append("--ios_minimum_os=13.0")
    if jobs:
        options.append(f"--jobs={jobs}")
    pins = {
        "litert": (STAGING_LITERT_SHA256, f"LiteRT-{STAGING_LITERT_REF}"),
        "XNNPACK": (XNNPACK_SHA256, f"XNNPACK-{XNNPACK_COMMIT}"),
    }
    workspace_rc = source_root / ".bazelrc"
    rc_text = workspace_rc.read_text(encoding="utf-8") if workspace_rc.is_file() else ""
    with tempfile.TemporaryDirectory(prefix="litert-bazel-") as temp:
        config = Path(temp) / "release.bazelrc"
        config.write_text(release_workspace_rc(rc_text), encoding="utf-8")
        startup.extend(("--noworkspace_rc", f"--bazelrc={bazel_path(config)}"))
        # Keep both commands in the WORKSPACE mode used by the pin verifier.
        options.append("--noenable_bzlmod")
        fetch_audited_archives(startup, source_root, bridge_options, Path(temp) / "resolved.bzl", pins)
        bazel_target = target["bazel_target"]
        if platform == "android":
            result = run([
                *startup, "aquery", *options, "--output=jsonproto", "--include_param_files",
                "--noinclude_artifacts", executor_compile_query(bazel_target),
            ], source_root, capture_output=True)
            verify_executor_compile_actions(result.stdout)
        run([*startup, "build", *options, bazel_target], source_root)
    verify_xnnpack_postimages(source_root)
    verify_litert_carry_postimages(source_root)

    if "output" in target:
        output = source_root / target["output"]
        if not output.is_file():
            raise RuntimeError(f"Expected build output missing: {output}")
        return output

    matches = sorted(source_root.glob(target["output_glob"]))
    if not matches:
        raise RuntimeError(f"Expected build output missing: {target['output_glob']}")
    return matches[0]


def stage_runtime(output: Path, platform: str, arch: str) -> Path:
    target = RUNTIME_TARGETS[(platform, arch)]
    stage_dir = BIN_DIR / platform / arch
    stage_dir.mkdir(parents=True, exist_ok=True)
    staged = stage_dir / target["library"]
    copy_artifact(output, staged)
    if platform == "macos":
        normalize_macos_runtime_identity(staged)
    print(f"Staged {staged}", flush=True)
    return staged


def copy_artifact(source: Path, destination: Path) -> None:
    destination.unlink(missing_ok=True)
    shutil.copy2(source, destination)


def stage_runtime_dependencies(
    output: Path,
    source_root: Path,
    platform: str,
    arch: str,
) -> None:
    if platform == "windows":
        stage_windows_runtime_dependencies(source_root, arch)
        return
    if platform in {"ios", "macos"}:
        stage_macho_runtime_dependencies(output, source_root, platform, arch)
        return

    stage_dir = BIN_DIR / platform / arch
    staged = stage_dir / RUNTIME_TARGETS[(platform, arch)]["library"]
    if platform == "linux":
        # Include dlopen-only accelerators as well as the host DT_NEEDED closure.
        # These copies overlay the raw prebuilt inventory in the package job.
        prebuilt_dir = source_root / "prebuilt" / PREBUILT_TARGETS[(platform, arch)]
        for dependency in sorted(prebuilt_dir.glob("*.so*")):
            if dependency.is_file() and dependency.name != staged.name:
                if not is_elf(dependency):
                    raise RuntimeError(f"Matching upstream Linux prebuilt is not ELF: {dependency.name}")
                copy_artifact(dependency, stage_dir / dependency.name)
    queued = [staged]
    seen = set()
    dependency_cache: dict[str, Path | None] = {}

    while queued:
        current = queued.pop()
        if current in seen:
            continue
        seen.add(current)
        if not is_elf(current):
            continue
        for library_name in elf_needed_libraries(current):
            if is_system_needed(platform, library_name):
                continue
            destination = stage_dir / library_name
            if platform == "linux" and library_name == "libLiteRt.so":
                # Prebuilt GPU accelerators require their matching upstream core;
                # a same-named source-built runtime can have incompatible ABI flags.
                prebuilt_target = PREBUILT_TARGETS[(platform, arch)]
                dependency = source_root / "prebuilt" / prebuilt_target / library_name
                if not dependency.is_file() or not is_elf(dependency):
                    raise RuntimeError("Matching upstream Linux libLiteRt.so is missing or not ELF")
                copy_artifact(dependency, destination)
            elif not destination.exists():
                dependency = find_runtime_dependency(
                    source_root,
                    output,
                    library_name,
                    dependency_cache,
                )
                if dependency is None:
                    raise RuntimeError(
                        f"{current} depends on {library_name}, but that library "
                        "was not found in the Bazel output tree."
                    )
                copy_artifact(dependency, destination)
                print(f"Staged runtime dependency {destination}", flush=True)
            queued.append(destination)


def normalize_linux_runtime_metadata(platform: str, arch: str) -> None:
    """Make the final flat ELF bundle resolve its own dependencies."""
    if platform != "linux":
        return
    if shutil.which("patchelf") is None:
        raise RuntimeError("Linux runtime packaging requires patchelf")
    for library in sorted((BIN_DIR / platform / arch).glob("*.so*")):
        if library.is_file() and is_elf(library):
            # Normalize packaged copies only, before smoke hashes are recorded.
            # Upstream Dawn lacks SONAME and accelerator RUNPATHs name Bazel dirs.
            original_mode = library.stat().st_mode
            try:
                # Bazel outputs retain read-only permissions through copy2.
                library.chmod(original_mode | 0o200)
                command = ["patchelf", "--set-rpath", "$ORIGIN"]
                # Only Dawn needs a new identity. Adding a SONAME to the host
                # relocates ELF notes and breaks its LLVM profiling shutdown.
                if library.name == "libwebgpu_dawn.so":
                    command.extend(["--set-soname", library.name])
                run([*command, str(library)], cwd=library.parent)
            finally:
                library.chmod(original_mode)


def stage_runtime_overrides(upstream_tag: str, platform: str, arch: str) -> None:
    overridden = apply_prebuilt_overrides(
        upstream_tag,
        platform=platform,
        arch=arch,
    )
    if overridden:
        print(
            f"Applied {overridden} pinned runtime overrides for "
            f"{platform}/{arch}",
            flush=True,
        )


def stage_windows_runtime_dependencies(source_root: Path, arch: str) -> None:
    prebuilt_target = PREBUILT_TARGETS.get(("windows", arch))
    if prebuilt_target is None:
        return
    source_dir = source_root / "prebuilt" / prebuilt_target
    stage_dir = BIN_DIR / "windows" / arch
    stage_dir.mkdir(parents=True, exist_ok=True)
    for source in sorted(source_dir.glob("*.dll")):
        destination = stage_dir / source.name
        copy_artifact(source, destination)
        print(f"Staged runtime dependency {destination}", flush=True)
    stage_windows_dxc(stage_dir)


def stage_windows_vc_runtime(platform: str, arch: str) -> None:
    """Ship the Visual C++ runtime app-locally; stock Windows hosts lack it (#87)."""
    if platform != "windows":
        return
    windows_runtime.stage_vc_runtime(
        BIN_DIR / platform / arch, arch, windows_runtime.vc_redist_dir()
    )


def stage_macho_runtime_dependencies(
    output: Path,
    source_root: Path,
    platform: str,
    arch: str,
) -> None:
    stage_dir = BIN_DIR / platform / arch
    staged = stage_dir / RUNTIME_TARGETS[(platform, arch)]["library"]
    queued = [staged]
    seen = set()
    dependency_cache: dict[str, Path | None] = {}

    while queued:
        current = queued.pop()
        if current in seen:
            continue
        seen.add(current)
        for install_name in macho_needed_libraries(current):
            if is_system_macho_needed(install_name):
                continue
            library_name = Path(install_name).name
            if library_name == current.name:
                continue
            destination = stage_dir / library_name
            if not destination.exists():
                dependency = find_runtime_dependency(
                    source_root,
                    output,
                    library_name,
                    dependency_cache,
                )
                if dependency is None:
                    raise RuntimeError(
                        f"{current} depends on {install_name}, but {library_name} "
                        "was not found in the Bazel output tree."
                    )
                copy_artifact(dependency, destination)
                print(f"Staged runtime dependency {destination}", flush=True)
            queued.append(destination)


def macho_needed_libraries(path: Path) -> list[str]:
    result = subprocess.run(
        ["otool", "-L", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    libraries: list[str] = []
    for line in result.stdout.splitlines()[1:]:
        stripped = line.strip()
        if not stripped:
            continue
        libraries.append(stripped.split(" ", 1)[0])
    return libraries


def is_system_macho_needed(install_name: str) -> bool:
    return (
        install_name.startswith("/System/Library/")
        or install_name.startswith("/usr/lib/")
        or install_name == Path(install_name).name
    )


def find_runtime_dependency(
    source_root: Path,
    output: Path,
    library_name: str,
    cache: dict[str, Path | None],
) -> Path | None:
    if library_name in cache:
        return cache[library_name]

    roots = [
        output.parent,
        output.parent / f"{output.name}.runfiles",
        source_root / "bazel-bin",
        source_root / "bazel-out",
    ]
    for root in roots:
        if not root.exists():
            continue
        for candidate in root.rglob(library_name):
            if candidate.is_file():
                cache[library_name] = candidate
                return candidate
    cache[library_name] = None
    return None


def validate_exported_symbols(output: Path, upstream_tag: str) -> None:
    data = output.read_bytes()
    required_symbols = (
        required_c_api_symbols(upstream_tag)
        + required_bridge_symbols(upstream_tag)
    )
    missing = [
        symbol.decode("ascii")
        for symbol in required_symbols
        if symbol not in data
    ]
    if missing:
        raise RuntimeError(
            f"{output} does not contain required LiteRT-LM/bridge symbols: "
            + ", ".join(missing)
        )
    print(f"Validated LiteRT-LM and bridge symbols in {output}", flush=True)


SHARED_LITERT_NAMES = frozenset({"liblitert.so", "liblitert.dll", "liblitert.dylib", "litert"})


def validate_in_process_litert_linkage(output: Path, platform: str, upstream_tag: str) -> None:
    """Fails if a runtime that reports in-process LiteRT loads it from another binary."""
    if in_process_litert_abi_version(upstream_tag) != 1:
        return
    if platform in {"linux", "android"}:
        imported = elf_needed_libraries(output)
    elif platform == "windows":
        imported = list(windows_runtime.read_pe(output).all_imports())
    else:
        imported = macho_needed_libraries(output)
    shared = sorted(name for name in imported if Path(name).name.lower() in SHARED_LITERT_NAMES)
    if shared:
        raise RuntimeError(
            f"{output.name} imports {', '.join(shared)}; a runtime reporting "
            "litert_lm_native_in_process_litert_abi_version() 1 must compile "
            "LiteRT in so external-weight options stay ABI-valid (#111)")
    print(f"Validated in-process LiteRT linkage in {output}", flush=True)


def validate_android_global_visibility(output: Path, platform: str) -> None:
    if platform != "android":
        return
    if not elf_has_global_flag(output):
        raise RuntimeError(
            f"{output} is missing the ELF DF_1_GLOBAL flag required for "
            "dlopened LiteRT GPU sampler plugins to resolve runtime symbols."
        )
    print(f"Validated Android global symbol visibility in {output}", flush=True)


def validate_android_gpu_samplers(output: Path, platform: str, upstream_tag: str) -> None:
    if platform != "android":
        return
    missing = sorted(
        set(android_static_gpu_sampler_symbols(upstream_tag)) - elf_exported_symbols(output))
    if missing:
        raise RuntimeError(
            f"{output} does not define the GPU sampler functions "
            f"{', '.join(missing)}; generation fails on the GPU backend they "
            "serve (#120)")
    print(f"Validated linked OpenCL and WebGPU samplers in {output}", flush=True)


def validate_android_gpu_environment_teardown(output: Path, platform: str) -> None:
    if platform != "android":
        return
    validate_library(output, find_ndk_llvm_objdump(os.environ.get("ANDROID_NDK_HOME")))
    print(f"Validated WebGPU teardown ordering in {output}", flush=True)


def validate_runtime(output: Path, platform: str, upstream_tag: str) -> None:
    validate_exported_symbols(output, upstream_tag)
    validate_in_process_litert_linkage(output, platform, upstream_tag)
    validate_android_global_visibility(output, platform)
    validate_android_protobuf_isolation(output, platform, upstream_tag)
    validate_android_gpu_samplers(output, platform, upstream_tag)
    validate_android_gpu_environment_teardown(output, platform)


def require_source_build(compatibility_tag: str) -> None:
    if not active_source_carries(compatibility_tag):
        raise RuntimeError("Use the historical native release ref to build LiteRT-LM before v0.20.0")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=f"Build the upstream {UPSTREAM_REPO} C runtime library."
    )
    parser.add_argument("--upstream-tag", required=True)
    parser.add_argument(
        "--upstream-ref",
        help=(
            "Exact source tag or commit. Defaults to --upstream-tag; development "
            "builds pass a full commit while --upstream-tag remains the stable "
            "compatibility baseline."
        ),
    )
    parser.add_argument("--platform", required=True)
    parser.add_argument("--arch", required=True)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--jobs")
    args = parser.parse_args()
    upstream_ref = args.upstream_ref or args.upstream_tag
    require_source_build(args.upstream_tag)

    key = (args.platform, args.arch)
    if key == ("macos", "x64"):
        raise SystemExit(f"Unsupported target macos/x64: {UNSUPPORTED_MACOS_ARCH_REASON}")
    if key not in RUNTIME_TARGETS:
        supported = ", ".join(f"{p}/{a}" for p, a in sorted(RUNTIME_TARGETS))
        raise SystemExit(f"Unsupported target {args.platform}/{args.arch}; supported: {supported}")

    if args.source_root:
        source_root = args.source_root.resolve()
        output = build_runtime(
            source_root,
            args.platform,
            args.arch,
            args.upstream_tag,
            args.jobs,
            upstream_ref,
        )
        validate_runtime(output, args.platform, args.upstream_tag)
        stage_runtime(output, args.platform, args.arch)
        stage_runtime_dependencies(output, source_root, args.platform, args.arch)
        stage_runtime_overrides(args.upstream_tag, args.platform, args.arch)
        stage_windows_vc_runtime(args.platform, args.arch)
        if args.platform == "ios" and provider_free_ios(args.upstream_tag):
            validate_ios_directory(BIN_DIR / "ios" / args.arch, remove_unused_provider=True)
        normalize_linux_runtime_metadata(args.platform, args.arch)
        return 0

    tmp_parent = None
    if os.name == "nt":
        tmp_parent = REPO_ROOT / ".tmp"
        tmp_parent.mkdir(exist_ok=True)

    with tempfile.TemporaryDirectory(
        prefix="litert-lm-native-build-",
        dir=tmp_parent,
        ignore_cleanup_errors=os.name == "nt",
    ) as tmp:
        source_root = download_upstream(
            upstream_ref, args.upstream_tag, Path(tmp)
        )
        output = build_runtime(
            source_root,
            args.platform,
            args.arch,
            args.upstream_tag,
            args.jobs,
            upstream_ref,
        )
        validate_runtime(output, args.platform, args.upstream_tag)
        stage_runtime(output, args.platform, args.arch)
        stage_runtime_dependencies(output, source_root, args.platform, args.arch)
        stage_runtime_overrides(args.upstream_tag, args.platform, args.arch)
        stage_windows_vc_runtime(args.platform, args.arch)
        if args.platform == "ios" and provider_free_ios(args.upstream_tag):
            validate_ios_directory(BIN_DIR / "ios" / args.arch, remove_unused_provider=True)
        normalize_linux_runtime_metadata(args.platform, args.arch)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
