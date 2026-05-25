# litert-lm-native

Native and web distribution pipeline for Google LiteRT-LM artifacts.

## Purpose

This repository owns the platform-specific LiteRT-LM runtime payload consumed
by Dart, Flutter, and other wrappers. It intentionally stays independent from
`llamadart` so the artifacts can be reused outside the Dart package.

Responsibilities:

- Track upstream `google-ai-edge/LiteRT-LM` releases.
- Fetch or build native LiteRT-LM libraries per platform.
- Provide a stable C ABI shim for FFI consumers.
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

- `include/litert_lm_c_api.h`: stable C ABI owned by this repo.
- `src/`: native shim implementation and stream callback proxy.
- `bin/`: generated release payloads by platform and architecture.
- `web/`: web package scaffold for JS/Wasm/WebGPU/WebNN integration.
- `tools/fetch_upstream.py`: resolves and downloads upstream release assets.
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

- `Validate`: builds the scaffold shim, validates package metadata, and checks
  Python/web tooling on pushes and pull requests.
- `Native Build & Release`: manually packages a selected upstream LiteRT-LM tag.
  It builds the current shim for host macOS/Linux/Windows, copies upstream
  `prebuilt/` runtime libraries for Android, Apple, Linux, and Windows, includes
  official upstream release assets when available, then publishes a GitHub
  release with `manifest.json` and `SHA256SUMS`.
- `Auto Upstream Release`: runs daily and dispatches `Native Build & Release`
  when `google-ai-edge/LiteRT-LM` has a latest release tag that this repo has
  not published yet.

The current release workflow packages upstream-provided prebuilts. Full
from-source builds for every target and the production C ABI implementation are
the next layer on top of this conveyor.

## Consumer Contract

Downstream packages should read `manifest.json`, choose a target by platform,
architecture, runtime kind (`native` or `web`), and accelerator metadata, then
verify checksums before bundling or loading the files.

The native C ABI is the compatibility boundary. Upstream LiteRT-LM can change
internals without forcing downstream FFI bindings to change.
