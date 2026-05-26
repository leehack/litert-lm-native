#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"
UPSTREAM_REPO = "google-ai-edge/LiteRT-LM"
UPSTREAM_ARCHIVE_URL = (
    "https://github.com/google-ai-edge/LiteRT-LM/archive/refs/tags/{tag}.tar.gz"
)

RUNTIME_TARGETS = {
    ("android", "arm64"): {
        "bazel_target": "//c:libLiteRtLm.so",
        "bazel_config": "android_arm64",
        "output": "bazel-bin/c/libLiteRtLm.so",
        "library": "libLiteRtLm.so",
    },
    ("android", "x64"): {
        "bazel_target": "//c:libLiteRtLm.so",
        "bazel_config": "android_x86_64",
        "output": "bazel-bin/c/libLiteRtLm.so",
        "library": "libLiteRtLm.so",
    },
    ("linux", "arm64"): {
        "bazel_target": "//c:libLiteRtLm.so",
        "bazel_configs": ["linux", "linux_arm64"],
        "output": "bazel-bin/c/libLiteRtLm.so",
        "library": "libLiteRtLm.so",
    },
    ("linux", "x64"): {
        "bazel_target": "//c:libLiteRtLm.so",
        "bazel_config": "linux",
        "output": "bazel-bin/c/libLiteRtLm.so",
        "library": "libLiteRtLm.so",
    },
    ("macos", "arm64"): {
        "bazel_target": "//c:libLiteRtLm.dylib",
        "bazel_configs": ["macos", "macos_arm64"],
        "output": "bazel-bin/c/libLiteRtLm.dylib",
        "library": "libLiteRtLm.dylib",
    },
    ("macos", "x64"): {
        "bazel_target": "//c:libLiteRtLm.dylib",
        "bazel_config": "macos",
        "output": "bazel-bin/c/libLiteRtLm.dylib",
        "library": "libLiteRtLm.dylib",
    },
    ("windows", "x64"): {
        "bazel_target": "//c:LiteRtLm.dll",
        "bazel_config": "windows",
        "output": "bazel-bin/c/LiteRtLm.dll",
        "library": "LiteRtLm.dll",
    },
}

REQUIRED_C_API_SYMBOLS = [
    b"litert_lm_engine_settings_create",
    b"litert_lm_engine_create",
    b"litert_lm_conversation_create",
    b"litert_lm_conversation_send_message_stream",
]

SHARED_TARGETS = """

# Added by litert-lm-native packaging. Upstream publishes the C API as a static
# cc_library for most platforms; Dart/Flutter FFI needs a loadable library.
cc_binary(
    name = "libLiteRtLm.so",
    linkshared = True,
    deps = [
        ":engine",
        "//schema/capabilities:capabilities_c",
    ],
)

cc_binary(
    name = "libLiteRtLm.dylib",
    linkshared = True,
    deps = [
        ":engine",
        "//schema/capabilities:capabilities_c",
    ],
)

cc_binary(
    name = "LiteRtLm.dll",
    linkshared = True,
    deps = [
        ":engine",
        "//schema/capabilities:capabilities_c",
    ],
)
"""


def run(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    printable = " ".join(command)
    print(f"+ {printable}", flush=True)
    if os.name == "nt":
        subprocess.run(printable, cwd=cwd, env=env, check=True, shell=True)
    else:
        subprocess.run(command, cwd=cwd, env=env, check=True)


def download_upstream(tag: str, work_dir: Path) -> Path:
    archive_path = work_dir / f"LiteRT-LM-{tag}.tar.gz"
    url = UPSTREAM_ARCHIVE_URL.format(tag=tag)
    print(f"Downloading {url}", flush=True)
    urllib.request.urlretrieve(url, archive_path)
    with tarfile.open(archive_path, "r:gz") as archive:
        archive.extractall(work_dir, filter="data")
    candidates = [path for path in work_dir.iterdir() if path.is_dir()]
    if len(candidates) != 1:
        raise RuntimeError(f"Expected one extracted source directory, got {candidates}")
    return candidates[0]


def patch_upstream_build(source_root: Path) -> None:
    build_path = source_root / "c" / "BUILD"
    text = build_path.read_text(encoding="utf-8")
    if "name = \"libLiteRtLm.so\"" in text:
        patched_build = text
    else:
        insert_before = "\ncc_test(\n    name = \"engine_test\","
        if insert_before not in text:
            raise RuntimeError("Could not find insertion point in upstream c/BUILD")
        patched_build = text.replace(insert_before, SHARED_TARGETS + insert_before)
    build_path.write_text(patched_build, encoding="utf-8")

    workspace_path = source_root / "WORKSPACE"
    workspace_text = workspace_path.read_text(encoding="utf-8")
    zlib_url = 'url = "https://zlib.net/fossils/zlib-1.3.1.tar.gz",'
    if zlib_url in workspace_text:
        workspace_path.write_text(
            workspace_text.replace(
                zlib_url,
                """urls = [
        "https://github.com/madler/zlib/releases/download/v1.3.1/zlib-1.3.1.tar.gz",
        "https://zlib.net/fossils/zlib-1.3.1.tar.gz",
    ],""",
            ),
            encoding="utf-8",
        )


def bazel_command() -> list[str]:
    if shutil.which("bazelisk"):
        return ["bazelisk"]
    if shutil.which("bazel"):
        return ["bazel"]
    if shutil.which("npx"):
        return ["npx", "--yes", "@bazel/bazelisk@latest"]
    raise RuntimeError("Could not find bazelisk, bazel, or npx")


def build_runtime(source_root: Path, platform: str, arch: str, jobs: str | None) -> Path:
    target = RUNTIME_TARGETS[(platform, arch)]
    configs = [
        f"--config={config}"
        for config in target.get("bazel_configs", [target.get("bazel_config")])
        if config
    ]
    command = bazel_command()
    output_user_root = os.environ.get("BAZEL_OUTPUT_USER_ROOT")
    if output_user_root:
        if not os.path.isabs(output_user_root):
            output_user_root = str((REPO_ROOT / output_user_root).resolve())
        command.append(f"--output_user_root={output_user_root}")
    command += [
        "build",
        *configs,
        *target.get("bazel_options", []),
        target["bazel_target"],
        "--define=litert_link_capi_so=true",
        "--define=resolve_symbols_in_exec=false",
    ]
    if jobs:
        command.append(f"--jobs={jobs}")
    run(command, source_root)

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
    shutil.copy2(output, staged)
    print(f"Staged {staged}", flush=True)
    return staged


def validate_exported_symbols(output: Path) -> None:
    data = output.read_bytes()
    missing = [
        symbol.decode("ascii")
        for symbol in REQUIRED_C_API_SYMBOLS
        if symbol not in data
    ]
    if missing:
        raise RuntimeError(
            f"{output} does not contain required LiteRT-LM C API symbols: "
            + ", ".join(missing)
        )
    print(f"Validated LiteRT-LM C API symbols in {output}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=f"Build the upstream {UPSTREAM_REPO} C runtime library."
    )
    parser.add_argument("--upstream-tag", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--arch", required=True)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--jobs")
    args = parser.parse_args()

    key = (args.platform, args.arch)
    if key not in RUNTIME_TARGETS:
        supported = ", ".join(f"{p}/{a}" for p, a in sorted(RUNTIME_TARGETS))
        raise SystemExit(f"Unsupported target {args.platform}/{args.arch}; supported: {supported}")

    if args.source_root:
        source_root = args.source_root.resolve()
        patch_upstream_build(source_root)
        output = build_runtime(source_root, args.platform, args.arch, args.jobs)
        validate_exported_symbols(output)
        stage_runtime(output, args.platform, args.arch)
        return 0

    with tempfile.TemporaryDirectory(
        prefix="litert-lm-native-build-",
        ignore_cleanup_errors=os.name == "nt",
    ) as tmp:
        source_root = download_upstream(args.upstream_tag, Path(tmp))
        patch_upstream_build(source_root)
        output = build_runtime(source_root, args.platform, args.arch, args.jobs)
        validate_exported_symbols(output)
        stage_runtime(output, args.platform, args.arch)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
