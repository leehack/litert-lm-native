# LiteRT-LM v0.19.0 owner qualification

Upstream tag `v0.19.0` is `771b06e1a2c7f70a399a718599109facf37e38fd` (LiteRT
`dcb657e8`, TensorFlow `4f8e6d47`, XNNPACK `28d1fc6d`). Issue
[#75](https://github.com/leehack/litert-lm-native/issues/75) was written against
raw `main`; these differ at the tag:

- Removed: TopK prebuilts on every platform (`43b79e88`); samplers are compiled
  from source and linked into `libLiteRtLm`.
- Not in the tag: `c57b9ae0` and `769af92e`, so it still ships prebuilt
  `libLiteRt`, accelerators and Dawn; `a48771d2` (Windows FD loading); `b3934770`
  (zero-state, upstream #3945).

## Migration

| Area | v0.19.0 | Owner change |
| --- | --- | --- |
| C API | 1.0: status codes and out parameters, `litert_lm_get_api_version`, thread-local last error | The bridge selects the new stream getters with `--define=litert_lm_c_api_v1=true`; tools use `tools/litert_lm_c_api.py`. A session or conversation must not be reused after cancel, only deleted. |
| ASR | `omni/asr` and the legacy engine are gone; `omni/speech2text` factories route through `OmniRegistry` and require a container | C ASR ABI v1 is unchanged. Containers use the registry; a `.tflite` plus tokenizer uses a bridge factory (`litert_lm_asr_omni_engine.cc`). A container whose metadata names another family fails at engine creation. Start tokens are dropped for LM-backed families, whose decoders reject them. |
| Protos | `Asr*` became `Speech2Text*` | Internal to the adapter. |
| Packaging | No `LiteRtTopK*Sampler` library; `libLiteRtLm` links Dawn | Validators and manifests key this on `has_prebuilt_topk_samplers`. |

`ubuntu-latest` moved to 26.04, so a Linux x64 build there needs glibc 2.43 and
fails to load on Ubuntu 24.04. Linux x64 now builds on `ubuntu-24.04` and
`validate_runtime_dependencies.py` rejects anything newer than glibc 2.39.

The ASR cache is disabled (`:nocache`): upstream's default writes beside the
model and the ABI has no cache directory. Default overlap stays 0.4; upstream's
is 0.75.

## Carried patches

| Patch | Decision | Evidence |
| --- | --- | --- |
| Untimed ASR overlap | Keep, re-ported to `MergeByWordCount` | v0.19's seam fallback drops words on repeated phrases at 0.4: Moonshine JFK gives "…what your country can do for your country." With the port it gives the full sentence. Replay: no exact regressions in 60,800 utterances; see `asr_untimed_overlap.md`. |
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
