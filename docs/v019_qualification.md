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
| Android GPU samplers | `libLiteRtLm` links `ml_drift_gpu_accelerator`, which serves OpenCL and WebGPU, but upstream links only the OpenCL sampler unless built with `--copt=-DLITERT_USE_WEBGPU_ACCELERATOR`. Without OpenCL the WebGPU route loads, then fails at the first token with `Can not find OpenCL library on this device` ([litert-lm-native#120](https://github.com/leehack/litert-lm-native/issues/120), [llamadart#1998](https://github.com/leehack/llamadart/issues/1998)) | The bridge links `//runtime/components:top_k_webgpu_sampler_static` on Android (`--define=litert_lm_android_webgpu_sampler=true`). Build and package validators compare exact dynamic exports and reject a candidate missing either sampler set (`android_static_gpu_sampler_symbols`). Re-audit on the next upstream bump: upstream `main` already splits the Android accelerator by `gpu_accelerator`. |
| Apple GPU | `LiteRtLm` links its GPU accelerator: ml_drift Metal on iOS, WebGPU on macOS | LiteRT registers it before searching for a shared one, so the prebuilt Metal accelerator is never opened ([llamadart#1798](https://github.com/leehack/llamadart/issues/1798)). Packaging after `v0.19.1-2` skips it on iOS and macOS, requires the static accelerator symbol in `LiteRtLm`, and rejects a candidate that still ships it (`has_prebuilt_apple_metal_accelerator`). |
| Apple LiteRT companions | `LiteRtLm` embeds LiteRT and its GPU accelerator | dyld traces on macOS (CPU, GPU, vision, audio, MTP, embeddings, ASR) and an iOS simulator probe load neither `libLiteRt` nor `libLiteRtWebGpuAccelerator` ([llamadart#1911](https://github.com/leehack/llamadart/issues/1911)). Packaging after `v0.19.1-3` skips the macOS `libLiteRt` and `libLiteRtWebGpuAccelerator` and the iOS loose `libLiteRt`, and rejects a candidate that still ships them (`has_prebuilt_apple_litert_companions`). |

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

## v0.19.1

Upstream tag `v0.19.1` is `7a03724cece417f1724c923b3d527b4319730841`, three
commits over `83ce6067`. Its only runtime change, `e4e00eee`, makes the main
executor's `max_num_images` default 4 (`kDefaultMaxNumImages`) instead of 0,
with or without a vision backend; an explicit positive value, including one set
through `litert_lm_engine_settings_set_max_num_images`, still wins. Only the
Artisan executor, which is not in the open-source tree, reads it; the CPU and
LiteRT GPU executors these runtimes build are unaffected. The rest
updates upstream `Package.swift` binary checksums, which owner packaging does
not read, and Web tests. The release notes' Artisan vision and audio support has
no other source change in the tag.

The `c/` tree, `omni/`, `prebuilt/`, `WORKSPACE`, `.bazelrc` and every carried
preimage are byte-identical to v0.19.0, so LiteRT `dcb657e8`, TensorFlow
`4f8e6d47`, XNNPACK `28d1fc6d` and the prebuilt `libLiteRt`, accelerators and
Dawn are unchanged. Every v0.19.0 decision above applies unchanged; v0.19.2 and
later still fail closed until audited. The bridge and ASR bridge use neither
`max_num_images` nor any changed file. Earlier v0.19.0 artifacts and smoke
evidence are bound to `83ce6067` and do not qualify this source.

### Step-zero state reset

Source builds of v0.19.1 backport
[LiteRT-LM e1f86b05](https://github.com/google-ai-edge/LiteRT-LM/commit/e1f86b05bf8a731331622a2622440e9f93d9a9f5)
for [#70](https://github.com/leehack/litert-lm-native/issues/70). Independent
conversations on one engine start from zero-filled state, including the
separate batched decode state. A linear attention tensor summarizes every
preceding token, so a positional mask cannot isolate a new conversation.
The source patch record binds the preimage, postimage and patch digest.
Official upstream prebuilts retain their original source identity.

On the exact upstream commit above, apply
`native/bridge/step_zero_state_v0191_test.patch` to a scratch source checkout
and run `bazel test //runtime/executor:llm_litert_compiled_model_executor_test`.
On macOS arm64, materialize the Git LFS dylibs in `prebuilt/macos_arm64`
and add `--config=macos_arm64`. Run the same target after applying
`native/bridge/step_zero_state_v0191.patch`.
Remove the step-zero restore branch, the `state_` clear and the
`decode_state_` clear individually to verify that each omission breaks its
regression case. The test patch is for qualification only.

Run `tools/litert_lm_step_zero_smoke.py` against each macOS arm64 runtime
archive, before and after the backport and again from the published release.
Supply the expected archive and extracted dylib hashes plus the pinned
Qwen3.5-0.8B and corrected Qwen3-0.6B model files. Run both `--backend cpu`
and `--backend gpu` with separate evidence directories. The JSON and native
logs record the streamed content, fresh-process controls, reload, conversation
reuse, drained cancellation, placement and timing. The Qwen3.5 comparison
uses the joined content bytes. For the attention-only model, compare counting
variants with the independent-process results and check the arithmetic control.

On macOS WebGPU, models that declare linear-attention state use
executor-managed decode inputs. The sampler still selects tokens on the GPU.
The lookahead path can consume divergent logits after an engine is reused.
The GPU placement check uses `--require-executor-managed-inputs` to verify this
routing and check that the attention-only arithmetic control still uses
sampler-managed input. The counting oracle also checks an independent request
after an unrelated word prompt. Removing the sampler guard must re-enable
lookahead in the linear-attention executor test.

### Spatial tensor bindings during GPU command-buffer preparation

Source builds of v0.19.1 carry
[LiteRT aa9e40cd](https://github.com/google-ai-edge/LiteRT/commit/aa9e40cd5e2d892b3a5d8579a7ec6faa696e321e)
for [llamadart#2134](https://github.com/leehack/llamadart/issues/2134). Cached
WebGPU and Vulkan dispatches stage new spatial bindings while the preceding
dispatch records its next command buffer. Reads see staged bindings immediately,
and dispatch applies them after joining the recording thread. Without staging,
Qwen3-0.6B can replay a cached buffer with another step's KV cache bindings and
repeat a token, or Dawn can reject a command buffer with overlapping bindings.

The patch retains the pinned LiteRT's `last_ctx_` behavior. Upstream
[LiteRT b6b64443](https://github.com/google-ai-edge/LiteRT/commit/b6b64443)
tracks that state per WebGPU environment for concurrent in-process engines and
requires separate qualification. Qwen3.5 retains the linear-attention sampler
guard described above.

The build pins the LiteRT archive at
`dcb657e8a537b2dc944e53e14c7eb43bcd9ededa`. Before invoking Bazel, both build
entry points verify the effective archive declaration, revision and digest.
After Bazel, the build verifies the four extracted postimages. The manifest records these LF-normalized hashes and patch SHA-256
`6012c5203a7f2586294cac3642dc0a7cc16d36c33cf1d8aee02f23599ed95436`
for source-built runtimes.

| Source in `ml_drift_delegate/delegate/` | Preimage SHA-256 | Postimage SHA-256 |
| --- | --- | --- |
| `gpu_backend_vulkan.cc` | `94510294e45a568440e87366facbae6294a1087a52bbbcbab05e5f6ceec6d3dd` | `ee5943a90770691b5e959152c02aaad642d9f6b42ddfbe08b1e3cb79bf8e614a` |
| `gpu_backend_vulkan.h` | `10482b2f4cc84e5db67f7385499307dcc930ffa24bfba397e42d2299808d9736` | `0695e45c94da94b87bbb91325b37ff0162c48deaaf5755abeaa51e68f6d1f0ed` |
| `gpu_backend_webgpu.cc` | `633b5483a3b25660135e5fff01edbebf43854c547726b85583a0fe4906fb7b8e` | `d2d0fc662b7dfd0b9fa5f95c04ada48f414b08c8f350a9e1169022371d3df968` |
| `gpu_backend_webgpu.h` | `bf318922fa10a4de702c9ac39212188e90809a0f9de918c29480c5317229c65c` | `5b756ac60ad2f183eae4981679bf6235befb2e70b82d6ad0807f7831277706b4` |

Run the model-free test on a macOS arm64 host with Metal from the prepared
v0.19.1 LiteRT-LM workspace with its materialized LFS dylibs. Set
`owner` to the absolute path to this checkout.

```bash
bazel test --package_path="$owner/native:$PWD" --config=macos --config=macos_arm64 \
  --macos_minimum_os=14.0 --nocache_test_results \
  //bridge:litert_stage_spatial_tensors_test
```

The stock build failed staging, the late-hint guard, and the ping-pong replay
(`255` instead of `767` after step 2). The uncached control passed. The
patched build passed all four cases. Bypassing staging, omitting the flush, and
allowing a late hint each failed its corresponding case. Mutating a pinned
postimage digest failed both the build verifier and the source-identity test.
Set `LITERT_STAGE_SPATIAL_TENSORS_SOURCE` to the unpatched LiteRT source root
to run that test with `python3 -m unittest discover -s tools`.

`tools/litert_lm_spatial_staging_smoke.py` reconstructs the investigation's
Montréal probe and uses the same harness for arithmetic. It opens one engine
per prompt, runs at least 100 independent conversations under eight SHA-256
workers, and records exact outputs, Metal placement, lookahead, and Dawn
validation errors.
Use the corrected Qwen3-0.6B bundle (`c5f39b41…`) and separate evidence folders.
Run both archives with `--backend gpu --count 200` and with `--backend cpu`
at the default count. Add `--expect-reproduction` only for the published
v0.19.1-6 GPU run.

```bash
python3 tools/litert_lm_spatial_staging_smoke.py \
  --archive "$archive" --archive-sha256 "$archive_sha256" \
  --library-sha256 "$dylib_sha256" --model "$qwen3_model" \
  --backend gpu --count 200 --evidence "$evidence"
```

The packaged macOS arm64 candidate archive SHA-256 was
`77a347a414f2d088718e6c3588caf48ee9a2d9f54ecfdb04b7140c8c504456e9`
and its `libLiteRtLm.dylib` SHA-256 was
`57c0bfb13f77ad588bafbbd330b0a92bbeefbe7fd59061bd170f68b44ab2d26f`.

On Apple M4 Max Metal, both libraries reported sampler lookahead. The first
100-turn v0.19.1-6 control reproduced four Montréal duplicates and returned
exact arithmetic. The matched 200-turn comparison reproduced both failures.

| Prompt | v0.19.1-6 exact | Candidate exact | Dawn validation errors, before → after |
| --- | ---: | ---: | ---: |
| `3 + 4 = 7` | 196/200 | 200/200 | 8 → 0 |
| `Montréal 👋` | 189/200 | 200/200 | 0 → 0 |

Both CPU packages returned 100/100 exact for each prompt under the same
eight-worker load, with zero Dawn validation errors.
The packaged candidate also passed the Qwen3.5-0.8B and Qwen3-0.6B step-zero
smoke on CPU and Metal. Warm Qwen3-0.6B Metal decode with lookahead measured
141.1 tok/s on v0.19.1-6 and 141.4 tok/s on the candidate, using the median of
three interleaved rounds of five warm turns each.

Revisit the carry when a tagged LiteRT-LM release pins a LiteRT containing
the staging fix. Re-run the cached-dispatch test and packaged Metal probes
against the unpatched replacement before retiring it.
