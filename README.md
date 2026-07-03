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
  It stages `LiteRtLm.framework`, `CLiteRTLM.framework`, and required companion
  frameworks such as `GemmaModelConstraintProvider.framework`.
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
currently exports the `stream_proxy_*` compatibility symbols used by
asynchronous callback loaders.

Apple SPM consumers should depend on the release's direct
`litert-lm-native-apple-*-xcframework-<tag>.zip` assets. The `LiteRtLm`
XCFramework contains the primary iOS runtime and macOS framework wrapper.
`CLiteRTLM` is retained as an iOS compatibility re-export target, and
`CLiteRTLMMac` is retained as a macOS compatibility re-export target. For
source-built Apple releases such as upstream `v0.14.0`, downstream SPM
integration must also include required companion XCFrameworks published by this
repo, for example `GemmaModelConstraintProvider`.

## Consumer Contract

Downstream packages should read `manifest.json`, choose a target by platform,
architecture, runtime kind (`native` or `web`), and accelerator metadata, then
verify checksums before bundling or loading the files.

Upstream LiteRT-LM's native C ABI is the compatibility boundary. This repository
does not add a second model wrapper ABI unless a future upstream change requires
it; bridge helpers remain narrow FFI utilities around that runtime surface.
