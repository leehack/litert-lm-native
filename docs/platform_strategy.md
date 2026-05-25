# Platform Strategy

## Native

Native platforms use a C ABI shim compiled against LiteRT-LM. The shim hides
upstream C++/Swift/Kotlin implementation details and exposes stable lifecycle,
conversation, streaming, cancellation, and benchmark calls.

The release automation publishes three kinds of artifacts:

- upstream LiteRT-LM C runtime libraries built from the tagged source archive
- upstream `prebuilt/` companion libraries copied from the tagged source archive
- `litert_lm_native` shim libraries built by this repo for host macOS, Linux,
  and Windows

The upstream C runtime is the production FFI target for downstream packages. The
shim is still useful as a compatibility/test target while the downstream
`llamadart` backend stabilizes around upstream's `c/engine.h` ABI.

Initial native targets:

| Platform | Arch | Tier | Expected path |
| --- | --- | --- | --- |
| Android | arm64-v8a | 1 | `.so` bundle |
| macOS | arm64 | 1 | `.dylib` or `.framework` bundle |
| iOS | arm64 | 2 | `.xcframework` archive |
| Linux | x64 | 2 | `.so` bundle |
| Windows | x64 | 2 | `.dll` bundle |
| Linux | arm64 | 3 | `.so` bundle |
| macOS | x64 | 3 | `.dylib` or `.framework` bundle |
| Android | x86_64 | 3 | `.so` bundle |

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
