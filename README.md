# litert-lm-native

Native and web distribution pipeline for Google LiteRT-LM artifacts.

## Purpose

This repository owns the platform-specific LiteRT-LM runtime payload consumed
by Dart, Flutter, and other wrappers. It intentionally stays independent from
`llamadart` so the artifacts can be reused outside the Dart package.

Responsibilities:

- Track upstream `google-ai-edge/LiteRT-LM` releases.
- Fetch or build native LiteRT-LM libraries per platform.
- Preserve upstream LiteRT-LM's C runtime ABI as the FFI boundary.
- Embed the small LiteRtLmBridge callback helper into runtime libraries used by
  asynchronous FFI clients.
- For LiteRT-LM 0.16+, expose the upstream C++ ASR session through a narrow,
  versioned C bridge because the released upstream C ABI omits speech engines.
- Package web assets around official LiteRT-LM/LiteRT.js distribution paths.
- Publish Apple Swift Package Manager XCFramework zip assets built from the
  same bridge runtimes as the native release payload.
- Publish `manifest.json` and `SHA256SUMS` for deterministic consumers.

The high-level model API, backend router, and model download/cache manager stay
in downstream packages such as `llamadart`.

## Platform Tiers

Tier 1:

- Android arm64
- macOS arm64
- Web

Tier 2:

- iOS arm64
- Linux x64
- Windows x64

Tier 3:

- Linux arm64
- macOS x64
- Android x86_64
- Simulator builds

Acceleration is platform-specific. Android and macOS are the primary paths for
GPU/NPU validation; web should use JavaScript interop instead of FFI.

## Repository Layout

- `bin/`: generated release payloads by platform and architecture.
- `web/`: web package scaffold for JS/Wasm/WebGPU/WebNN integration.
- `tools/fetch_upstream.py`: resolves and downloads upstream release assets.
- `tools/build_upstream_runtime.py`: builds upstream LiteRT-LM C runtime
  libraries from tagged source with Bazel/Bazelisk through the repo-owned
  `native/bridge` Bazel package, embeds LiteRtLmBridge symbols into
  source-built runtime libraries without patching upstream source files, and
  stages them for release.
- `tools/package_ios_runtime.py`: extracts official upstream
  `CLiteRTLM.xcframework` slices when present, or wraps source-built iOS
  `libLiteRtLm.dylib` outputs when upstream no longer publishes the archive.
  It stages `LiteRtLm.framework`, `CLiteRTLM.framework`, and any required
  companion frameworks.
- `tools/package_macos_runtime.py`: extracts official upstream
  `CLiteRTLM_mac.xcframework` slices when present, or wraps source-built macOS
  `libLiteRtLm.dylib` outputs when upstream no longer publishes the archive.
  The compatibility `libCLiteRTLM_mac.dylib` re-exports the primary runtime.
- `tools/package_apple_xcframeworks.py`: packages iOS framework wrappers and
  macOS bridge wrappers as SPM-compatible XCFramework zip assets.
- `tools/package_release.py`: builds local manifest and checksums.
- `tools/validate_artifacts.py`: validates manifest, checksums, and layout.
- `docs/platform_strategy.md`: platform and distribution strategy.
- `third_party/LiteRT-LM`: optional upstream source checkout or submodule.

## Local Workflow

Inspect the latest upstream release:

```bash
python3 tools/fetch_upstream.py --latest --metadata-only
```

Download upstream release assets:

```bash
python3 tools/fetch_upstream.py --latest
```

Generate release metadata for local `bin/` and `web/dist/` contents:

```bash
python3 tools/package_release.py --upstream-tag v0.12.0
python3 tools/validate_artifacts.py
```

## Release Automation

- `Validate`: validates package metadata and checks Python/web tooling on
  pushes and pull requests.
- `Native Build & Release`: manually packages a selected upstream LiteRT-LM tag.
  It builds upstream C runtime libraries with embedded LiteRtLmBridge symbols for
  Android arm64/x64, iOS arm64/arm64-sim, Linux x64/arm64, macOS arm64/x64, and
  Windows x64, copies upstream `prebuilt/` companion libraries for Android,
  Apple, Linux, and Windows, uses official Apple XCFramework archives when
  upstream publishes them, falls back to the source-built Apple runtimes when
  those archives are missing, packages Apple SPM XCFramework zips from the same
  runtime payloads, includes the official upstream release assets, then
  publishes a GitHub release with `manifest.json` and `SHA256SUMS`. The workflow
  accepts a separate `release_tag`; use it when repackaging the same upstream
  tag without mutating an existing native release.
- `Auto Upstream Release`: runs daily and dispatches `Native Build & Release`
  when `google-ai-edge/LiteRT-LM` has a latest release tag that this repo has
  not published yet. Existing releases are treated as immutable; if validation
  rules change and an existing release no longer matches, the scheduled workflow
  reports it but does not overwrite the tag automatically.

For upstream `v0.15.0`, packaging applies two checksum-pinned Android arm64/x64
corrections. `libLiteRtTopKOpenClSampler.so` comes from upstream commit
`8bee4dddc3794958b4bdd8a3a4ba75bcb71f6fbb` because the tagged binaries omit
three symbols required by `sampler_factory` and otherwise fall back to CPU
sampling. `libwebgpu_dawn.so` comes from the upstream `v0.14.0` commit
`f73637c57f0940b53da184e0d5adfc52a4e55eef` because the tagged v0.15 Dawn
binary produced `VK_ERROR_DEVICE_LOST` on a Mali-G715 during generation, while
the exact v0.14 binary completed the same workload. The release manifest
records the exact override source commits, paths, and checksums, and packaging
rejects sampler libraries that do not expose the full seven-symbol plugin
contract.

## Native Version Management

The published native release tag is the version contract consumed by downstream
package hooks and Swift Package manifests. For the first package of an upstream
LiteRT-LM tag, the native release tag normally matches the upstream tag. If a
packaging fix is needed for the same upstream sources, publish a new native
release tag such as `v0.13.1-native.1` instead of overwriting `v0.13.1`.

When moving to a new LiteRT-LM tag:

1. Run `Native Build & Release` for `upstream_tag`, or let `Auto Upstream
   Release` dispatch it for the latest upstream release.
2. Verify the release contains runtime archives, official upstream assets,
   Apple SPM XCFramework zips, `manifest.json`, and `SHA256SUMS`.
3. Update downstream `llamadart` hook pins, SPM URLs, and SPM checksums
   together so native-assets and SPM consumers use the same bridge-enabled
   runtime build.

To publish a corrected package for existing upstream sources without breaking
downstream checksum pins, dispatch the workflow with both tags:

```bash
gh workflow run native_release.yml \
  --repo leehack/litert-lm-native \
  --ref main \
  -f upstream_tag=v0.13.1 \
  -f release_tag=v0.13.1-native.1 \
  -f prerelease=false \
  -f target_platform=all \
  -f target_arch=all
```

The release workflow uses upstream's public C API (`c/engine.h`) as the
production FFI boundary. Downstream loaders should bind directly to the runtime
library for the selected platform. Source-built native runtimes are assembled
from a repo-owned Bazel package selected ahead of the upstream source tree with
`--package_path` on Unix-like runners and copied into the extracted source tree
on Windows to avoid Bazel's Windows package-path parser. The workflow does not
edit upstream LiteRT-LM source files in the repository.
LiteRtLmBridge symbols are embedded into the same runtime library surface; no
standalone bridge runtime artifact is part of the release contract. The bridge
exports the `stream_proxy_*` compatibility symbols used by asynchronous
callback loaders. For LiteRT-LM 0.15 and newer, it translates upstream opaque
stream chunks back to the stable text/final/error callback consumed by existing
FFI clients. `stream_proxy_callback_abi_version` lets consumers reject an
incompatible bridge before starting an asynchronous callback.

LiteRT-LM 0.16 source contains a stateful ASR pipeline but does not publish it
through `c/engine.h` or its official C binaries. Source-built 0.16+ runtimes
therefore also export `litert_lm_asr_*` bridge ABI version 1. It accepts bounded
mono float PCM and returns confirmed/unconfirmed transcript updates with
explicit backpressure, finish, reset, and between-window cancellation. See
[`docs/asr_bridge.md`](docs/asr_bridge.md) for the contract and real-model
smoke. Apple packaging intentionally keeps the source-built runtime for these
tags; an official C-binary wrapper cannot recover omitted ASR C++ objects.

Apple SPM consumers should depend on the release's direct
`litert-lm-native-apple-*-xcframework-<tag>.zip` assets. The `LiteRtLm`
XCFramework contains the primary iOS runtime and macOS framework wrapper.
`CLiteRTLM` is retained as an iOS compatibility re-export target, and
`CLiteRTLMMac` is retained as a macOS compatibility re-export target. Upstream
`v0.14.0` uses the official consolidated Apple XCFrameworks and does not require
a separate iOS `GemmaModelConstraintProvider` target. Source-built Apple
releases may still require companion XCFrameworks when the primary runtime
links against them.

## Consumer Contract

Downstream packages should read `manifest.json`, choose a target by platform,
architecture, runtime kind (`native` or `web`), and accelerator metadata, then
verify checksums before bundling or loading the files.

Upstream LiteRT-LM's native C ABI remains the default compatibility boundary.
Where upstream source exposes a needed engine but its released C ABI does not,
this repository may add a narrow, independently versioned bridge after runtime
and packaging validation. The LiteRT-LM 0.16+ ASR bridge is the first such
exception; high-level model selection and download policy remain downstream.
