# Platform Strategy

## Native

Native platforms use upstream LiteRT-LM's C runtime ABI directly. This keeps the
release payload aligned with the runtime that downstream FFI bindings load and
avoids publishing a second model wrapper ABI that does not add behavior.

The release automation publishes these runtime artifact groups:

- upstream LiteRT-LM C runtime libraries built from the tagged source archive,
  with StreamProxy symbols embedded for downstream FFI streaming on source-built
  platforms
- upstream `prebuilt/` companion libraries copied from the tagged source archive
- official upstream release assets, including the iOS `CLiteRTLM.xcframework`
  archive when Google publishes it
- iOS framework-style runtime wrappers derived from `CLiteRTLM.xcframework`,
  with StreamProxy symbols embedded in `LiteRtLm.framework/LiteRtLm` and
  upstream symbols re-exported from `CLiteRTLM.framework/CLiteRTLM`

The upstream C runtime is the production FFI target for downstream packages. If
we later need a repo-owned compatibility layer, it should be introduced as a real
wrapper over upstream LiteRT-LM rather than a scaffold library.

Initial native targets:

| Platform | Arch | Tier | Expected path |
| --- | --- | --- | --- |
| Android | arm64-v8a | 1 | `.so` bundle |
| macOS | arm64 | 1 | `.dylib` or `.framework` bundle |
| iOS | arm64 | 2 | `.framework` wrapper plus upstream runtime from `.xcframework` |
| Linux | x64 | 2 | `.so` bundle |
| Windows | x64 | 2 | `.dll` bundle |
| Linux | arm64 | 3 | `.so` bundle |
| macOS | x64 | 3 | `.dylib` or `.framework` bundle |
| Android | x86_64 | 3 | `.so` bundle |
| iOS simulator | arm64, x64 | 3 | `.framework` wrapper plus upstream runtime from `.xcframework` |

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
- upstream LiteRT-LM tag
- file name and SHA-256
- library names required by loaders
- accelerator support metadata
- minimum OS/toolchain notes when known

Downstream packages should not infer platform support from filenames alone.
