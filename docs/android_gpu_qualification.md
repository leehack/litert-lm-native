# Android GPU qualification

The v0.17.0 native wrapper must retain the Android Dawn correction in
`tools/prebuilt_overrides.py`. Do not remove this compatibility override merely
because the upstream version advances; repeat the affected device/model rows.

## Controlled Pixel comparison

On 2026-09-16, a Pixel 9 Pro (Mali-G715, Android 17/API 37) ran the maintained
llamadart engine and chat-feature smokes through a temporary Flutter application
(target SDK 36). GPU was explicitly requested and native logs selected Vulkan.

| Runtime | Qwen3 0.6B GPU | Gemma 4 E2B GPU |
| --- | --- | --- |
| v0.16.0-native.2 baseline | PASS | PASS |
| Published v0.17.0-2 | Vulkan device loss/readback failure | Vulkan device loss/readback failure |
| v0.17.0-2 with only the pinned Dawn replacement | PASS | PASS |

The candidate APK changed exactly one non-signature entry:
`lib/arm64-v8a/libwebgpu_dawn.so`. Its SHA256 is
`7282aacdb076ce89f0c9d93107a145b991b99eb1dfbd5b5746dd0d99466ab3c3`,
from upstream commit `f73637c57f0940b53da184e0d5adfc52a4e55eef`.
The corrected production packager independently downloaded matching bytes.
All other runtime libraries and application payload entries were unchanged.
This isolates a sufficient packaging repair; it does not identify an upstream
Dawn source-level defect.

Qwen3 exercised tokenization, detokenization and 32-token generation with a
1024-token context. It emitted nonempty thinking within that bounded budget.
Gemma exercised plain chat, thinking, tool calls and native tool history.
These are functional checks, not accuracy or performance benchmarks. The first
Qwen3 candidate initialization took about 147 seconds; cached and cold timings
must not be compared as a performance claim.

Model SHA256 identities:

- Qwen3 0.6B: `555579ff2f4fd13379abe69c1c3ab5200f7338bc92471557f1d6614a6e5ab0b4`
- Gemma 4 E2B: `181938105e0eefd105961417e8da75903eacda102c4fce9ce90f50b97139a63c`

## Scope and remaining qualification

The Vulkan comparison intentionally omits optional vendor OpenCL library
visibility declarations in every arm. Adding those declarations to the new
runtime selects OpenCL but produced a separate native crash; this is not an
OpenCL qualification or recommendation to remove application declarations.

Qwen3.5 0.8B int8 GPU allocation failures reproduced on both original runtimes;
the Dawn correction does not establish support for that workload. Gemma's
Metal shader binding failure on the iOS simulator also reproduced on both
original runtimes and is outside this Android change. CPU rows passed before
this repair. Other Android GPUs and Android x64 remain untested on hardware.

Apply the correction through the owner packaging workflow, publish a new
immutable wrapper version, then qualify its exact packaged artifact before
updating downstream pins. The local single-library candidate does not qualify
a future release or authorize consumer PR #503 to merge unchanged.

## GPU environment teardown patch

LiteRT `9fe5be45`, pinned by LiteRT-LM 0.17.x, loads OpenCL before it records
the GPU environment options. When OpenCL cannot be loaded, as in an Android app
that does not declare `libOpenCL.so`, the WebGPU delegate's destroy callback is
never recorded, so deleting an engine never destroys its Dawn device and the
driver keeps the engine's graphics memory.
`native/bridge/litert_gpu_environment_destroy_callback.patch` applies the
ordering of LiteRT `9c8ae4e0fc` to the source-built runtime.

Only the Android libraries change. Upstream's `linux` and `windows` Bazel
configurations define `LITERT_DISABLE_OPENCL_SUPPORT`, and Apple builds default
to no OpenCL support, so the early return is not compiled there and the patch
moves a statement between two points with nothing in between.

`tools/build_upstream_runtime.py` selects the patch by the `LITERT_REF` pinned in
the upstream `WORKSPACE`. The listed commits are the ones the patch has been
matched against (LiteRT-LM v0.15.0, v0.16.x, v0.17.x and one development pin
share the same `gpu_environment.cc`); the list is not the proof. Every Android
build then disassembles `GpuEnvironment::Initialize` in the built library with
the NDK's `llvm-objdump` and fails unless the call that records the options
precedes the OpenCL setup, so an unlisted pin with the old ordering, a patch
that silently stops taking effect, or a build without the function cannot
produce an artifact. The same check runs on any library:

```sh
python3 tools/gpu_environment_teardown.py path/to/libLiteRtLm.so
```

A later pin that already contains the reordering builds without the patch and
passes the check. Remove the patch and its list entries once no supported
upstream line pins a listed commit.

Galaxy S24 (`SC-51E`, Android 16, Adreno 750), Qwen3 0.6B on WebGPU/Vulkan,
engine create, 32-token generation and delete in one process, measured with
`dumpsys meminfo` on 2026-10-06. The two runs used different physical devices
of the same model and build:

| Runtime | Sequence | Graphics before / engine alive / after delete | Outcome |
| --- | --- | --- | --- |
| Published `v0.17.0-7` | four CPU engines, then GPU engines | 55 / 2058 / 2058 MB | Killed by lmkd during the second GPU engine |
| `v0.17.0-7` with only `libLiteRtLm.so` rebuilt with the patch | four GPU engines | 55 / 2017 to 2058 / 55 MB | Passed, no growth |

The published runtime never logs `Destroyed WebGPU delegate environment.`; the
patched one logs it once per delete. The patched library was a local
android-arm64 build with NDK r28c, not a packaged release artifact; release
builds use r28b. Other Android GPUs and Android x64 are untested on hardware.


## v0.18 candidate qualification (2026-10-07)

Candidate owner head `f9819d3b89cdd765d414f193986696cba20a2a50` builds
LiteRT-LM `b2f686e2ed4718fb84ec398a61dd59ca0f0aff27` / LiteRT
`26895c9fbcc25c43faa8c1a98cd1fd28951602c3`. Physical Firebase Test Lab
execution used the maintained public Dart API, Flutter 3.47.1, context 1024,
32 generated tokens, and the exact Qwen/Gemma hashes above. The test consumer
has isolated harness changes; its dirty-source report is supplemented by exact
native-library and patch provenance, not treated as a clean production build.
The generic validator reports `qualified=false` because its structured
accelerator/provenance fields are incomplete; native adapter/delegate logs and
library hashes provide supplemental evidence for the specific rows below.

| Device / model | Stock v0.18 | Only Dawn replaced with the pinned historical binary |
| --- | --- | --- |
| Pixel 9 Pro, API 35, Mali-G715 / Qwen3 0.6B | Raw GPU inference times out after Vulkan `VK_ERROR_DEVICE_LOST` | Raw GPU inference passes |
| Galaxy S24, API 36, Adreno 750 / Qwen3 0.6B | Engine creation rejects a 155582464-byte buffer against a 134217728-byte storage binding limit | Same allocation failure; Dawn replacement is insufficient |

In the controlled comparison, non-signature APK entries compare byte-for-byte; only `lib/arm64-v8a/libwebgpu_dawn.so`
changes, to SHA256
`7282aacdb076ce89f0c9d93107a145b991b99eb1dfbd5b5746dd0d99466ab3c3`.
The original API 37 Pixel row is unavailable in the current device catalog;
API 35 is supplemental device-family evidence.

The consumer's existing Qwen template separately fails v0.18 native chat:
upstream now normalizes content to arrays, while the override concatenates
strings. This is not a GPU driver failure. A consumer template adjustment must
preserve string and text-part-array prompts, real `tool_response` payloads,
thinking, history and explicit rejection of unsupported content. Changing only
the message wire representation is insufficient because v0.18 normalizes it.
The final combined Pixel Qwen run passed all 17
selected cases, including three reloads, using the tool-safe template adjustment
and the pinned Dawn replacement. A second run also
passed all 17 cases and observed final disposal for 15 seconds: graphics memory
fell from about 2344 MiB to 61 MiB and remained there for five samples.
Peak graphics memory was about 2392 MiB. Exact library hashes and the isolated
consumer patch remain part of the qualification evidence. Do not move consumer pins until the
consumer adjustment is carried by a reviewed change.

Pixel Gemma 4 E2B also passed all 17 selected public-API cases with the
pinned Dawn replacement, including cancellation, three reloads and recovery.
Post-disposal graphics memory returned from about 2049 MiB to 61 MiB and
remained there for five samples; peak graphics memory was about 2083 MiB.
The initial Android Gemma attempts failed during model download or isolated
test-harness preparation before inference. The passing run used privately
staged, SHA256-verified weights and a single initialized instrumentation
automation connection shared by staging and the memory sampler.

Physical iPhone 16 Pro / iOS 18.3 candidate Metal tests passed Qwen (with the
consumer template adjustment) and Gemma: all 17 selected public-API cases,
including cancellation, three reloads and recovery, with native Metal
initialization and five environment destruction events. This proves the retained
framework-path/provider-free bundle works; it does not prove the patch can be
removed. iOS 16.6 produced only Firebase infrastructure errors, and iOS 16.4 is
unavailable. Neither row is a minimum-OS pass.

The new bridge also built against real upstream v0.17.0
`e9fd8c53ff968071774206163027dd84bedfe925` on Ubuntu 24.04 / Linux x64;
the Moonshine/JFK ASR smoke transcribed the audio and emitted one final event.
The published v0.17.0-8 S24 control also logs
the same 128 MiB binding validation error, although it proceeds through engine
creation and most generation/lifecycle cases. Three text assertions fail. Thus
the limit error is preexisting; v0.18 additionally fails delegate initialization.
Do not classify the entire device/model failure as a new v0.18 regression or
claim that the old runtime is qualified on this S24 row. Adapter-supported and
requested/device limits still need comparison before changing limit policy.

The S24 failure is tracked in [issue #51](https://github.com/leehack/litert-lm-native/issues/51).
It remains an unsupported device/model row; keep the runtime failure explicit
and do not call the v0.17 control a pass. Missing minimum-iOS execution evidence
remains a qualification limit. Hosted CPU checks do not close these gaps.
