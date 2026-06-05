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
- Apple Swift Package Manager XCFramework zips produced from the same iOS
  wrappers, macOS source-built runtime, and macOS companion dylibs used by the
  native-assets payloads

The upstream C runtime is the production FFI target for downstream packages. If
we later need a repo-owned compatibility layer, it should be introduced as a real
wrapper over upstream LiteRT-LM rather than a scaffold library.

SPM artifacts are intentionally split by binary target. `LiteRtLm` carries the
primary iOS runtime/wrapper and a macOS framework wrapper around the
source-built runtime. `CLiteRTLM` is published for iOS re-export support. macOS
companion dylibs are published as separate XCFramework targets when the native
release payload contains them.

The macOS LiteRT-LM SPM path must account for the architecture coverage of the
native payload. Upstream `v0.13.1` publishes arm64 macOS companion dylibs, while
the x64 source-built runtime links only to `libLiteRt.dylib`; those macOS dylibs
are built for macOS 14. Keep native-assets runtime archives as the source of
truth, and only wire macOS SPM dependencies in downstream packages when the
required binary targets cover the selected architecture and deployment target.

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
| iOS simulator | arm64; x64 when upstream ships it | 3 | `.framework` wrapper plus upstream runtime from `.xcframework` |

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
