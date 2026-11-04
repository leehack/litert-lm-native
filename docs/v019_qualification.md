# LiteRT-LM v0.19.0 owner qualification

Upstream tag `v0.19.0` is `83ce6067f2e2a3fb697556928f93936693ded971` (LiteRT
`dcb657e8`, TensorFlow `4f8e6d47`, XNNPACK `28d1fc6d`). Issue
[#75](https://github.com/leehack/litert-lm-native/issues/75) was written against
raw `main`; these differ at the tag:

- Removed: TopK prebuilts on every platform (`43b79e88`); samplers are compiled
  from source and linked into `libLiteRtLm`.
- Not in the tag: `c57b9ae0` and `769af92e`, so it still ships prebuilt
  `libLiteRt`, accelerators and Dawn; `a48771d2` (Windows FD loading); `b3934770`
  (zero-state, upstream #3945).

## Qualification source refresh

The upstream v0.19.0 tag now resolves to `83ce6067` rather than the original
`771b06e1`. The intervening commit updates only upstream `Package.swift` binary
URLs/checksums and README release notes. Runtime sources, C headers, prebuilt
pins and build declarations are unchanged; owner packaging does not consume
upstream `Package.swift`.

Earlier owner candidate `94db8c5` artifacts and qualification receipts remain
bound to `771b06e1`; they must not be relabeled as evidence for this refreshed
source identity. Rebuild every candidate platform and repeat artifact/model
qualification under the refreshed owner heads before publication or adoption.
The exact-tag verification gate remains enabled.

## Migration

| Area | v0.19.0 | Owner change |
| --- | --- | --- |
| C API | 1.0: status codes and out parameters, `litert_lm_get_api_version`, thread-local last error | The bridge selects the new stream getters with `--define=litert_lm_c_api_v1=true`; tools use `tools/litert_lm_c_api.py`. A session or conversation must not be reused after cancel, only deleted. |
| ASR | `omni/asr` and the legacy engine are gone; `omni/speech2text` factories route through `OmniRegistry` and require a container | C ASR ABI v1 is unchanged. Containers use the registry; a `.tflite` plus tokenizer uses a bridge factory (`litert_lm_asr_omni_engine.cc`). Container metadata and Parakeet sections pick the registry name, so file names, free-form `model_name`s and `decoder_type` do not change routing, and a `model_name` naming another family fails at engine creation. Other LLM containers lost the generic LLM route and need a registered name. Start tokens are dropped for LM-backed families, whose decoders reject them. |
| Protos | `Asr*` became `Speech2Text*` | Internal to the adapter. |
| Packaging | No `LiteRtTopK*Sampler` library; `libLiteRtLm` links Dawn | Validators and manifests key this on `has_prebuilt_topk_samplers`. |

`ubuntu-latest` moved to 26.04, so a Linux x64 build there needs glibc 2.43 and
fails to load on Ubuntu 24.04. Linux x64 now builds on `ubuntu-24.04` and
`validate_runtime_dependencies.py` rejects anything newer than glibc 2.39.

The ASR cache is disabled (`:nocache`): upstream's default writes beside the
model and the ABI has no cache directory. Default overlap stays 0.4; upstream's
is 0.75.

## Android protobuf isolation

The Android C API 1.0 wrapper link localizes bundled protobuf definitions while
retaining public runtime, bridge and plugin exports and the GLOBAL loader
contract. This addresses the constructor collision tracked in owner #105;
rebuilt artifact and affected-device GPU qualification remain required. See
[the link policy, regression controls and remaining gates](android_protobuf_isolation.md).

## Push-source regression gate

`tools/qualify_asr_omni_input.py` compiles the production v0.19 PCM source
against the exact upstream Omni stage headers, using system Abseil and protobuf.
The model-free qualification lane runs it before runtime builds. It checks bounded
backpressure, step-sized chunks without duplicate overlap, tail and single EOF
delivery, cancellation, reset of pending PCM and queued outputs, and reuse.
This gate covers the input source; real-model session cancellation, reset and
backpressure still require their own qualification.

## Conservative Android Qwen3 GPU restriction

The source-built v0.19 C API adds a pre-factory safety check for the exact
614,236,160-byte Qwen3-0.6B bundle with SHA-256
`555579ff2f4fd13379abe69c1c3ab5200f7338bc92471557f1d6614a6e5ab0b4`.
Its known 155,582,464-byte shared constant exceeded the historical Adreno 750
storage binding limit of 134,217,728 bytes. The independent compiler crash
remains a separate concern. See upstream #3866/#3867 and owner #51.

Only Android requests for the main LiteRT GPU executor enter this guard. File
assets are hashed through a retained descriptor and that same descriptor is
passed to the factory through a local settings copy; renaming/replacing a path
cannot substitute a different file after inspection. Existing mapped assets are
read through their retained mapping. Model contents must remain immutable while
in use. DataStream assets, unavailable reads and changing file metadata refuse
before GPU initialization; current C constructors expose path/FD assets only.

For the exact fixture, a Vulkan-instance-only probe reads vendor/device/driver
and maxStorageBufferRange without creating a GPU device or compute pipeline.
The historical tuple vendor `0x5143`, device `0x43051401`, driver `2150604839`
is refused. Missing, incomplete or multiple-adapter facts also refuse this
fixture with an explicit safety-unknown diagnostic. Other identified fixtures,
CPU requests and non-Android platforms are outside this deny policy. Passing
it does not establish GPU support. No adapter is claimed to be the accelerator's
selected adapter, and the C API cannot guarantee an OpenCL route; the exact
restriction may therefore conservatively refuse OpenCL too.

Failure uses the existing FAILED_PRECONDITION status/last-error path with a null
engine output and CPU remedy. The source patch is hash-audited in owner
sourcePatches. It does not publish a new artifact, change core pins, qualify a
v0.19 device, fix opaque delegate error propagation or close #51. Full candidate
builds, independent review, same-device guard/CPU/reload controls and #1677's
typed-error/automatic-fallback integration remain release gates.

## Carried patches

| Patch | Decision | Evidence |
| --- | --- | --- |
| Untimed ASR overlap | Keep, re-ported to `MergeByWordCount` | v0.19's seam fallback drops words on repeated phrases at 0.4: Moonshine JFK gives "…what your country can do for your country." With the port it gives the full sentence. Replay: no exact regressions in 60,800 utterances; see `asr_untimed_overlap.md`. |
| HF grammar bytes and JSON formatting | New carry (#100) | Lossless ByteLevel bytes and the UTF-8 callback contract prevent native aborts. Default JSON formatting now bounds insignificant whitespace per gap while retaining caller overrides and string contents. Exact HF/provider controls, all 151,669 supported-Qwen token IDs and model-free packaged grammar controls pass; unchanged model/schema qualification remains required. See `upstream_patch_audit.md`. |
| Stream finish reason | Keep, re-ported | Upstream still folds stop, budget and context into `kDone`. Budget, stop and cancel pass on CPU. |
| ASR container routing | Retire | `bfdec21732` is in the tag. Whisper container passes. |
| v0.18.1 WORKSPACE repair | Retire | `d99b438f` is in the tag. Bazel builds unpatched. |
| CPU options identifier | Retire | Prebuilt `libLiteRt` for Linux, Windows and macOS contains `cpu_options`. Thread probe adds 3 threads at 4. |
| SentencePiece BPE NUL | Retire | Upstream ships the equivalent `third_party/sentencepiece/sentencepiece.patch`. Original Qwen3-0.6B bundle `555579ff…` loads and generates. |
| XNNPACK PF32 SME2 and PQS8/QC4W | Keep | [google/XNNPACK#11789](https://github.com/google/XNNPACK/issues/11789) and [#11793](https://github.com/google/XNNPACK/issues/11793) are open and the sources still match. |
| iOS Metal accelerator path | Keep | The registry still joins the bare name to the runtime directory. |
| iOS Metal sampler path | Retire | The prebuilt it pointed at no longer exists. |
| Android Dawn rollback | Keep pending device run | v0.19 rebuilds Dawn and the accelerator; no Pixel Mali-G715 run has qualified either choice. |
| GPU environment teardown | Not selected | Upstream records options before `InitializeOpenCl`; the Android disassembly gate remains. |
