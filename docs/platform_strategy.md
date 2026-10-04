# Platform Strategy

## Native

Native platforms use upstream LiteRT-LM's C runtime ABI directly by default.
When released upstream source contains a required engine that the public C ABI
omits, a narrow versioned bridge may expose that existing behavior without
patching upstream. LiteRT-LM 0.16+ ASR is the first such exception.

The release automation publishes these runtime artifact groups:

- upstream LiteRT-LM C runtime libraries built from the tagged source archive,
  with LiteRtLmBridge symbols embedded by the repo-owned `native/bridge` Bazel
  package for downstream FFI streaming on source-built platforms
- upstream `prebuilt/` companion libraries copied from the tagged source archive
- narrowly scoped, checksum-pinned prebuilt corrections when a released
  upstream binary is known to violate its runtime plugin contract; override
  provenance is recorded in `manifest.json`
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

Native release tags are immutable consumer contracts. New rebuilds preserve the
exact upstream or development prefix and append compact `-N`; legacy
`vMAJOR.MINOR.PATCH-native.N` tags remain read-only. See
[`release_protocol.md`](release_protocol.md) for collision, rollback, rebuild,
development identity, and approval rules.

The upstream C runtime is the production FFI target for downstream packages.
LiteRtLmBridge is limited to narrow FFI helpers around that runtime surface. It
exports the `stream_proxy_*` compatibility symbols used by downstream streaming
callbacks. LiteRT-LM 0.15+ opaque stream chunks are translated to that stable
callback contract inside the bridge. Consumers can probe
`stream_proxy_callback_abi_version` before registering callbacks. Source-built
native runtimes use Bazel `--package_path` on Unix-like runners and copy the
bridge package into the extracted source tree on Windows to avoid Bazel's
Windows package-path parser, without patching upstream source files in the
repository.

For LiteRT-LM 0.16+, the same runtime exports `litert_lm_asr_*` ABI version 1.
It adapts upstream `AsrEngine`/`AsrSession` to bounded push PCM and
confirmed/unconfirmed transcript results. Official 0.16 Apple C binaries omit
those C++ ASR objects, so Apple packaging selects the source-built runtime even
when official XCFramework archives exist. The official archives remain
published as provenance-preserving upstream assets, not the speech-capable
runtime payload.

SPM artifacts are intentionally split by binary target. `LiteRtLm` carries the
primary iOS runtime and macOS framework wrapper. `CLiteRTLM` is published for
iOS re-export support, and `CLiteRTLMMac` is published for macOS re-export
support. Source-built Apple releases can publish additional companion binary
targets when the primary runtime links or dynamically loads them. The v0.16 iOS
package includes `GemmaModelConstraintProvider`, `LiteRtMetalAccelerator`, and
`LiteRtTopKMetalSampler`; the Metal modules use framework-relative loader paths
that are compatible with App Store bundle layout.

The Apple LiteRT-LM SPM path must account for the architecture coverage of the
native payload. Upstream `v0.13.1` and `v0.14.0` publish universal Apple
XCFrameworks. For `v0.14.0`, the official archives were added after the release
was first published, so the packaging workflow pins their checksums and requires
them instead of silently falling back to a different payload. Keep native-assets
runtime archives as the source of truth, and only wire SPM dependencies in
downstream packages when the required binary targets cover the selected
architecture and deployment target.

### iOS deployment floors

Generated framework plists declare the greater of the packaging baseline
(iOS 15.0) and the executable's actual Mach-O deployment target. Device and
simulator slices are checked separately; merged simulator frameworks retain the
highest minimum across their slices. Official framework metadata, final runtime
frameworks, and SwiftPM inputs must never declare a lower minimum than their
executables require. Missing, ambiguous, or wrong-platform targets fail
packaging rather than falling back to the baseline.

This metadata rule does not make an upstream prebuilt compatible with older
iOS versions. In the `v0.17.0-6` release, the device Gemma constraint provider
requires iOS 26.4 despite its generated plist declaring 15.0. Because the runtime
links that provider, downstream apps embedding it cannot claim iOS 16.4 support
from the primary runtime or wrapper's lower deployment target. A compatible
upstream provider or an explicitly adopted higher app deployment floor is
required before consumer qualification. Do not lower a prebuilt's Mach-O target
or overwrite an immutable published release to hide this requirement.

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

Schema 2 records release-wide identity and compatibility data at the top level:

- `release`: native release tag, channel, kind, rebuild ordinal, and GitHub
  prerelease classification
- `upstream` and `native`: repositories, exact commits, upstream tag or
  development identity, compatibility baseline, and any prebuilt overrides
- `abi` and `capabilities`: the complete ABI and capability contract for the
  release
- `platforms`: exactly nine platform/architecture bundles; each entry names its
  release asset, linked `artifactPaths`, and the accelerator union of those
  linked artifacts
- `realModelSmokes`: pinned model, tokenizer, audio, library, source URL,
  expectation, and transcript evidence, separate from artifact entries

Each `artifacts` entry records only the file-level contract:

- runtime family: `native`, `archive`, or `web`
- platform and architecture (null for release-wide archives)
- repository-relative path and file name
- file SHA-256
- upstream tag, exact upstream commit, and native release tag provenance
- accelerator support metadata using the schema's allowed values: generic
  `gpu`, `metal`, `opencl`, and `webgpu`

Downstream packages should not infer platform support from filenames alone.

## Desktop WebGPU runtime linkage

For Linux and Windows builds using LiteRT-LM v0.16 or newer, pass
`--define=litert_runtime_link_mode=dynamic` so the host uses the same shared
LiteRT runtime as its prebuilt accelerators. `litert_link_capi_so=true` is a
legacy setting and does not select the modern runtime dependency path. Keep
`resolve_symbols_in_exec=false` for the shared-library host. Older versions and
Apple/Android build configurations are outside this desktop correction.

This follows the pinned [v0.17 build instructions](https://github.com/google-ai-edge/LiteRT-LM/blob/v0.17.0/docs/getting-started/build-and-run.md)
and the independently reported [Windows configuration repair](https://github.com/google-ai-edge/LiteRT-LM/issues/2957#issuecomment-5289900291).
It is a candidate correction for [native issue #47](https://github.com/leehack/litert-lm-native/issues/47), not evidence that every desktop GPU/model works.
Before publishing or removing a consumer GPU gate, inspect the rebuilt host's
shared-runtime dependency and run real GPU generation on Linux Vulkan and
Windows D3D12, alongside CPU controls. Preserve driver/backend identity and
streaming/disposal evidence. Never infer hardware support merely from successful
library registration or a CPU-only hosted CI smoke.

Linux packaging must also retain `prebuilt/<target>/libLiteRt.so` from the same
upstream snapshot as the accelerator. A source-built core with the same SONAME
is not ABI-equivalent evidence: the L4 control still crashed with that core and
passed after replacing only it with the matching prebuilt. Missing matching
prebuilts fail the build instead of falling back to an arbitrary Bazel output.

Windows packaging stages the pinned DirectX Shader Compiler pair
(`dxil.dll`, `dxcompiler.dll`) beside the runtime DLLs, because Dawn's D3D12
backend opens both by name through its own module directory and otherwise fails
engine creation with `DynamicLib.Open: dxil.dll`. `tools/windows_dxc.py` holds
the single pin: the official Microsoft archive URL, its SHA-256, and a digest
per extracted file. The archive's `LICENSE-LLVM.txt`, `LICENSE-MIT.txt`, and
`LICENSE-MS.txt` ship as `DXC-LICENSE-*.txt` in the same directory;
`dxcompiler.dll` is LLVM/NCSA plus MIT, and `dxil.dll` is a Microsoft-signed
redistributable governed by the Microsoft terms. Releases from upstream v0.17.0
onward require the pair and the licences; already-published v0.16 bundles
predate it. Placement is not by itself GPU evidence: qualify real Windows D3D12
generation without runtime directories on `PATH`.

Linux flat runtime bundles normalize the packaged Dawn SONAME and use `$ORIGIN`
for dependency lookup, after dependency staging and before model smoke hashes.
Upstream build-tree RUNPATHs and a missing Dawn SONAME must not require callers
to configure `LD_LIBRARY_PATH`. Only packaged copies are normalized; upstream
sources remain unchanged. Linux packaging requires `patchelf`, and qualification
runs a real-loader regression without loader environment overrides.

## Pull-request qualification selection

Every pull request runs the shared `Validate` workflow once, including tooling,
metadata compatibility fixtures, release lifecycle checks, and Linux loader
regressions. The `v0.12.0` metadata fixture is historical compatibility coverage;
it does not select or qualify the runtime release.

`tools/qualification_scope.py` uses an explicit allowlist for documentation and
existing tooling tests. Unknown paths, shared build/packaging inputs, native
sources, workflow changes, and missing comparison data retain all nine targets.
Renames and deletions consider both sides of the change.

Changes confined to the macOS packager or identity helper select both macOS
architectures; iOS packager changes select both supported iOS targets. These
candidates retain the real Apple XCFramework packaging gate, with unselected
Apple prebuilts excluded first. Artifact/dependency checks and real-model evidence
must match the selected targets; macOS also retains its Qwen inference gate.
Partial validation does not claim a full release candidate. Shared changes still
run the complete nine-target inventory and all three desktop model gates.

`qualification-result` always reports the selected job results and fails for
missing, failed, cancelled, or unexpectedly skipped work. Only superseded PR runs
are cancelled; main and manual `Validate` runs are independent. Publication,
release evidence requirements, and runtime pins are unchanged. See
[llamadart issue #532](https://github.com/leehack/llamadart/issues/532).

## Provider-free iOS source-build candidate

New owner source builds using the v0.17.0 or later compatibility baseline disable
Gemma FST constraints **only on iOS**, with upstream's existing
`--define=LITERT_LM_FST_CONSTRAINTS_DISABLED=1`. The builder verifies the selected
source's Gemma3, FunctionGemma, and Gemma4 BUILD gates before invoking Bazel; a
changed or absent gate fails the build. Older baselines and non-iOS builds keep
their existing options. Preserved official upstream archives remain unchanged
provenance inputs, separate from the source-built candidate runtime.

Gemma FST constrained decoding is unavailable in these candidate iOS artifacts.
Ordinary inference, thinking, and generic function calling (tool formatting and
parsing) are not disabled by this option. For upstream Gemma3, FunctionGemma,
and Gemma4, requesting `enable_constrained_decoding=true` reaches an upstream
C++ `FailedPrecondition` with a build-time-disabled diagnostic. The C API exposes
this as failed conversation creation (`nullptr`) and logs the diagnostic; it
does not directly return that typed C++ status. Consumers should request
constrained decoding false for these affected Gemma conversations, regardless
of whether a tool or response schema was requested. The C API setter and
exports remain available; true still fails conversation creation. This repository does not add a consumer API or
change its pins.

Source staging and iOS framework packaging validate every surviving dylib and
framework for provider load commands and **all** undefined provider symbols,
then remove unused flat/provider framework inputs. SwiftPM packaging rejects
provider-contaminated iOS inventories. Dependency and final manifest guards
inspect iOS archive members and embedded Mach-O binaries too; macOS-only
provider XCFramework slices remain valid after every actual Mach-O architecture
is verified against recognized XCFramework platform/variant metadata. Missing,
unknown, or inconsistent slice metadata fails closed. Production CLIs require the selected
upstream compatibility tag, including development releases. Release archives
receive a final validation after creation. Schema 2 capability keys remain
unchanged: they do not promise Gemma FST constraints. The existing exact native
commit provenance identifies this build policy.

Candidate validation also rejects any iOS Mach-O architecture requiring above
16.4, any wrong/missing/ambiguous platform target, and framework declarations
above 16.4. This is an artifact condition, not old-OS runtime proof.

The candidate does not yet restore or qualify the consumer's advertised iOS
16.4 floor. Framework deployment metadata remains derived from actual Mach-O
slices; no metadata lowering is permitted. Local SDK-compiled fixtures validate
packaging and fail-closed controls, not LiteRT execution. Before publishing or
changing consumer pins, qualify the rebuilt device/simulator archives and real
Metal exports, run the closest affected Gemma family with constrained decoding
false and true, and establish the actual minimum OS on supported devices. The
shared owner change retains the full nine-platform build qualification and
three Qwen smoke jobs. Gemma4 weights are available locally for later testing;
rebuilt iOS artifacts and an iOS 16.4 environment remain required.
