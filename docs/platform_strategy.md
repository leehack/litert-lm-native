# Platform Strategy

## Native

Native platforms use upstream LiteRT-LM's C runtime ABI directly. This keeps the
release payload aligned with the runtime that downstream FFI bindings load and
avoids publishing a second model wrapper ABI that does not add behavior.

The release automation publishes these runtime artifact groups:

- upstream LiteRT-LM C runtime libraries built from the tagged source archive,
  with LiteRtLmBridge symbols embedded by the repo-owned `native/bridge` Bazel
  package for downstream FFI streaming on source-built platforms
- upstream `prebuilt/` companion libraries copied from the tagged source archive
- official upstream release assets, including Apple `CLiteRTLM*.xcframework`
  archives when Google publishes them
- iOS framework-style runtime wrappers derived from official
  `CLiteRTLM.xcframework` slices when available, or from source-built
  `libLiteRtLm.dylib` outputs when upstream no longer publishes the archive
- macOS dylib runtime wrappers derived from official
  `CLiteRTLM_mac.xcframework` slices when available, or from source-built
  `libLiteRtLm.dylib` outputs when upstream no longer publishes the archive
- Apple Swift Package Manager XCFramework zips produced from the same iOS
  wrappers, macOS wrappers, and required companion frameworks used by the
  native-assets payloads

Native release tags are immutable consumer contracts. Use a separate native
release tag when repackaging the same upstream source tag, for example
`upstream_tag=v0.13.1` with `release_tag=v0.13.1-native.1`, so downstream
packages with pinned checksums keep resolving the original artifacts.

The upstream C runtime is the production FFI target for downstream packages.
LiteRtLmBridge is limited to narrow FFI helpers around that runtime surface. It
currently exports the `stream_proxy_*` compatibility symbols used by downstream
streaming callbacks. Source-built native runtimes use Bazel `--package_path` on
Unix-like runners and copy the bridge package into the extracted source tree on
Windows to avoid Bazel's Windows package-path parser, without patching upstream
source files in the repository.

SPM artifacts are intentionally split by binary target. `LiteRtLm` carries the
primary iOS runtime and macOS framework wrapper. `CLiteRTLM` is published for
iOS re-export support, and `CLiteRTLMMac` is published for macOS re-export
support. Source-built Apple releases can publish additional companion binary
targets, such as `GemmaModelConstraintProvider`, when the primary runtime links
against them.

The Apple LiteRT-LM SPM path must account for the architecture coverage of the
native payload. Upstream `v0.13.1` publishes universal Apple XCFrameworks;
upstream `v0.14.0` publishes no Apple XCFramework archives, so this repository
source-builds Apple runtimes and companion targets. Keep native-assets runtime
archives as the source of truth, and only wire SPM dependencies in downstream
packages when the required binary targets cover the selected architecture and
deployment target.

Initial native targets:

| Platform | Arch | Tier | Expected path |
| --- | --- | --- | --- |
| Android | arm64-v8a | 1 | `.so` bundle |
| macOS | arm64 | 1 | `.dylib` or `.framework` bundle |
| iOS | arm64 | 2 | `.framework` runtime plus companion frameworks |
| Linux | x64 | 2 | `.so` bundle |
| Windows | x64 | 2 | `.dll` bundle |
| Linux | arm64 | 3 | `.so` bundle |
| macOS | x64 | 3 | `.dylib` or `.framework` bundle |
| Android | x86_64 | 3 | `.so` bundle |
| iOS simulator | arm64; x64 when available | 3 | `.framework` runtime plus companion frameworks |

## Web

Web should not use FFI. It should use a small JavaScript package that wraps
official LiteRT-LM web APIs where available, and falls back to LiteRT.js
distribution paths only when those APIs support `.litertlm` inference.

The web package should expose:

- model loading from URL, Blob, File, or Cache API entry
- streaming generation callbacks
- cancellation
- benchmark metrics when supported
- feature flags for WebGPU, WebNN, Wasm, and CPU fallback

## Artifact Manifest

Each artifact entry records:

- runtime: `native` or `web`
- platform and architecture
- native release tag
- upstream LiteRT-LM tag
- file name and SHA-256
- library names required by loaders
- accelerator support metadata
- minimum OS/toolchain notes when known

Downstream packages should not infer platform support from filenames alone.
