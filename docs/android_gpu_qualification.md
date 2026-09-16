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
