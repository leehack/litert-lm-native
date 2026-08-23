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
  source-built runtime libraries, applies the scoped iOS framework-path
  compatibility rewrites required by upstream's dynamic Metal loaders, and
  stages them for release. The rewrites apply only to the extracted build tree;
  upstream sources are not vendored here. Local upstream checkouts may retain
  Git LFS pointers
  for link-time dependencies; the build resolves those objects from upstream
  media URLs and verifies their embedded size and SHA-256 first.
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
python3 tools/package_release.py \
  --upstream-tag v0.12.0 \
  --upstream-commit ffed38adbc33509480b5340e5173638bc20a68ff \
  --compatibility-tag v0.12.0 \
  --release-tag v0.12.0 \
  --native-commit "$(git rev-parse HEAD)" \
  --official-upstream-assets
python3 tools/validate_artifacts.py
```

## Release Automation

- `Validate`: validates package metadata and checks Python/web tooling on
  pushes and pull requests.
- `Native Build & Release`: prepares or explicitly publishes an exact upstream
  LiteRT-LM tag/commit and exact native commit.
  It builds upstream C runtime libraries with embedded LiteRtLmBridge symbols for
  Android arm64/x64, iOS arm64/arm64-sim, Linux x64/arm64, macOS arm64/x64, and
  Windows x64, copies upstream `prebuilt/` companion libraries for Android,
  Apple, Linux, and Windows, uses official Apple XCFramework archives when
  upstream publishes them, falls back to the source-built Apple runtimes when
  those archives are missing, packages Apple SPM XCFramework zips from the same
  runtime payloads, includes the official upstream release assets, then
  writes a fail-closed schema 2 `manifest.json` plus `SHA256SUMS`, and uploads a prepared
  candidate by default. Publication requires the explicit `publish` input,
  exact-input revalidation, required real-model evidence, draft validation, and
  draft promotion. Existing releases are never edited or overwritten.
- `Detect Upstream Release`: runs daily with read-only permissions. It detects
  and records a consumable stable candidate as `preparation.json`; it never
  dispatches the build and never publishes.

See [`docs/release_protocol.md`](docs/release_protocol.md) for the common stable,
development, rebuild, provenance, rollback, and orchestration contract.

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
contract. Upstream `v0.16.0` and same-commit metadata release `v0.16.1` keep the
same checksum-pinned Dawn rollback: the tagged Android arm64 binary reproduced
`VK_ERROR_DEVICE_LOST` on a Pixel 9 Pro,
while the rollback completed the same Gemma 4 GPU workload and exact-answer
gate. The v0.16 sampler binaries do not require the v0.15 sampler override.

## Native Version Management

The published native release tag is the version contract consumed by downstream
package hooks and Swift Package manifests. Stable releases exactly mirror an
upstream `vMAJOR.MINOR.PATCH`; stable rebuilds append compact `-N`.
Development builds use `g<first-12-of-full-upstream-SHA>` and development
rebuilds append the same compact `-N`. Historical `-native.N` releases remain
immutable and consumable but are never emitted again.

When moving to a new LiteRT-LM tag:

1. Let `Detect Upstream Release` prepare exact inputs, or resolve the exact
   upstream tag/commit and native commit manually.
2. Run `Native Build & Release` with `publication_approval=prepare-only` and
   inspect the candidate manifest, `release-result.json`, and evidence.
3. After separate publication approval, rerun the exact inputs with
   `publication_approval=publish`.
4. Verify the release contains runtime archives, official upstream assets,
   Apple SPM XCFramework zips, `manifest.json`, `release-result.json`, and
   `SHA256SUMS`.
5. Update downstream `llamadart` hook pins, SPM URLs, and SPM checksums
   together so native-assets and SPM consumers use the same bridge-enabled
   runtime build.

The exact `native_commit` must already be reachable from `main`; release
preparation and the final publication recheck both enforce that provenance.

Release-tooling pull requests automatically run a read-only exact-input
qualification. It builds all nine targets and requires the pinned ASR
real-model smoke on Linux x64, Windows x64, and macOS arm64. It uploads the
runtime/evidence artifacts for review but has no publication input or write
permission.

To prepare a corrected package for existing upstream sources without breaking
downstream checksum pins, dispatch the workflow with all exact identities:

```bash
gh workflow run native_release.yml \
  --repo leehack/litert-lm-native \
  --ref main \
  -f release_tag=v0.16.0-3 \
  -f upstream_tag=v0.16.0 \
  -f upstream_commit=924e79c91542761242244e4f1651851f822e4cbb \
  -f upstream_compatibility_tag=v0.16.0 \
  -f native_commit=<exact-litert-lm-native-commit> \
  -f correlation_id=<caller-audit-id> \
  -f publication_approval=prepare-only \
  -f target_platform=all \
  -f target_arch=all
```

After reviewing the candidate and obtaining separate publication approval,
rerun those exact inputs with `publication_approval=publish`.

Publication also requires the repository administrator to configure the
`litert-release-publication` environment with at least one required reviewer.
The workflow verifies that protection before and after the reviewer wait and
fails closed while the environment is absent or unprotected.

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
releases also publish any required companion XCFrameworks. For v0.16 this
includes the iOS `LiteRtMetalAccelerator` and `LiteRtTopKMetalSampler` modules;
their framework-relative loader paths avoid flat dylibs that App Store bundles
cannot ship.

## Consumer Contract

Downstream packages should read `manifest.json`, choose a target by platform,
architecture, runtime kind (`native` or `web`), and accelerator metadata, then
verify checksums before bundling or loading the files.

Upstream LiteRT-LM's native C ABI remains the default compatibility boundary.
Where upstream source exposes a needed engine but its released C ABI does not,
this repository may add a narrow, independently versioned bridge after runtime
and packaging validation. The LiteRT-LM 0.16+ ASR bridge is the first such
exception; high-level model selection and download policy remain downstream.
