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
- Ship the small StreamProxy companion library needed by asynchronous FFI
  clients to copy LiteRT-LM streaming callback strings safely.
- Package web assets around official LiteRT-LM/LiteRT.js distribution paths.
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
  libraries from tagged source with Bazel/Bazelisk and stages StreamProxy.
- `tools/package_ios_runtime.py`: extracts official upstream
  `CLiteRTLM.xcframework` slices into the dylib-style iOS runtime payload used
  by downstream FFI clients.
- `tools/build_stream_proxy.py`: builds the companion callback-copy helper
  library used by downstream FFI stream bindings.
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
  It builds upstream C runtime libraries and StreamProxy for Android
  arm64/x64, macOS arm64/x64, Linux x64/arm64, and Windows x64, copies upstream
  `prebuilt/` companion libraries for Android, Apple, Linux, and Windows,
  converts official upstream `CLiteRTLM.xcframework` slices into iOS runtime
  archives with StreamProxy, includes the official upstream release assets,
  then publishes a GitHub release with `manifest.json` and `SHA256SUMS`.
- `Auto Upstream Release`: runs daily and dispatches `Native Build & Release`
  when `google-ai-edge/LiteRT-LM` has a latest release tag that this repo has
  not published yet.

The release workflow uses upstream's public C API (`c/engine.h`) as the
production FFI boundary. Downstream loaders should bind directly to the upstream
runtime library for the selected platform and use StreamProxy only as a
callback-memory companion for streaming.

## Consumer Contract

Downstream packages should read `manifest.json`, choose a target by platform,
architecture, runtime kind (`native` or `web`), and accelerator metadata, then
verify checksums before bundling or loading the files.

Upstream LiteRT-LM's native C ABI is the compatibility boundary. This repository
does not add a second wrapper ABI unless a future upstream change requires it.
