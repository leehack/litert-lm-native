# LiteRT-LM v0.18.0 carried-fix audit

For v0.19.0 decisions, see [v0.19 qualification](v019_qualification.md).

Audited LiteRT-LM `b2f686e2ed4718fb84ec398a61dd59ca0f0aff27`, which pins
LiteRT `26895c9fbcc25c43faa8c1a98cd1fd28951602c3`. Source inspection is
not device or GPU qualification. PR qualification exercises the packaged CPU
paths; affected GPU devices remain separate release-adoption evidence.

| Carried fix | v0.18 decision | Evidence and limit |
| --- | --- | --- |
| GPU environment teardown ordering | Skip for v0.18; retain for supported older inputs | Upstream `GpuEnvironment::Initialize` records options before `InitializeOpenCl`. Existing commit-based selection skips the patch; every Android binary must still pass the disassembly gate. |
| SentencePiece BPE single-NUL compatibility | Keep | WORKSPACE retains SentencePiece 0.2.2 SHA-256 `92381f713e094a15a1ccff1ac4a5315a4c4b82a99ac1332d6ac53c9dc8e1bcf1`, whose unpatched NORMAL NUL rejection breaks the untouched Qwen tokenizer. Sanitizer qualification covers the patched accepted case and malformed variants. |
| iOS Metal accelerator framework path | Keep pending unpatched packaged-device proof | Upstream adds the bare `LiteRtMetalAccelerator` fallback, but the registry still joins it to the runtime directory and loads that path. It does not construct our nested `@executable_path/Frameworks/LiteRtMetalAccelerator.framework/LiteRtMetalAccelerator` path. Preserve the upstream fallback while applying the explicit bundle path. Bazel 7.6.1 patch application passed against both exact old and new source files. |
| iOS Metal sampler framework path | Keep | Upstream `sampler_factory.cc` still requests `libLiteRtTopKMetalSampler.dylib`; our iOS bundle ships `LiteRtTopKMetalSampler.framework/LiteRtTopKMetalSampler`. |
| iOS FST provider disable define | Keep | The upstream gate and provider dependency remain; disabling it preserves our provider-free closure policy. Binary provider/minimum-OS checks remain mandatory; this is not proof of execution on iOS 16.4. |
| zlib download URL workaround | No additional rewrite for v0.18 | Upstream WORKSPACE already supplies the accepted mirror list; the helper preserves it. Retain the older-source URL fallback. |
| Android Dawn rollback | Keep for v0.18 | Stock v0.18 loses the Vulkan device during Qwen inference on Pixel 9 Pro (API 35, Mali-G715). A controlled APK changing only arm64 Dawn to the checksum-pinned historical binary restores raw GPU inference. Extend the existing override to v0.18; this does not fix the separate Galaxy S24 allocation limit or qualify Android x64 hardware. See the linked device qualification record. |
| v0.15 OpenCL sampler override | Inactive for v0.18 | Already restricted to v0.15.0; retain historical build support. |
| Stream finish reasons | Apply only to audited v0.18.0 source hashes (v0.18.1 preimages are identical) | Upstream reports a stop token, the output-token budget and a full context identically, so consumers cannot detect truncation ([#78](https://github.com/leehack/litert-lm-native/issues/78)). See the tracking section below. |
| Untimed ASR overlap alignment | Apply only to audited v0.18.0 source hash (v0.18.1 preimage is identical) | A declarative patch aligns matching boundary words before the word-count fallback. Timed and single-window outputs are unchanged in differential replay; the revised confidence checks prevent the audited periodic collapse and avoid measured clean-corpus regressions, while garbled inputs retain small regressions and repetition gains are reduced. Applies to untimed presets using `TimestampTextMerger` (Moonshine, Whisper tiny, Qwen3-ASR); `tinygemma-asr` uses the Levenshtein merger and is unaffected. See [qualification and retirement gates](asr_untimed_overlap.md) and the [unposted upstream draft](asr_untimed_overlap_upstream_issue.md). Real-model packaged JFK validation remains required. |
| ASR `.litertlm` container routing | Backport to audited v0.18.0 source hashes (v0.18.1 preimages are identical) | Stock v0.18.0 `AsrEngine::Create` sends every `.litertlm` path to the LLM runner, so the published Whisper tiny container (one `tf_lite_encoder_decoder` section plus AsrMetadata and an HF tokenizer) fails with `tf_lite_prefill_decode not found` ([#77](https://github.com/leehack/litert-lm-native/issues/77)). Upstream [`bfdec21732`](https://github.com/google-ai-edge/LiteRT-LM/commit/bfdec21732) selects the decoder from AsrMetadata and loads the container's ASR section and tokenizer; it landed on `main` after the v0.18 branch, and v0.18.1 still lacks it. The backport is that commit's `asr_engine` change without the `kUnspecified` enum. Qwen3-ASR and LLM-only containers keep the LLM route. PR qualification runs the pinned container on CPU plus two derived negatives. |
| v0.18.1 Bazel WORKSPACE build repair | Apply only to audited v0.18.1 WORKSPACE/.bazelrc hashes | v0.18.1 took main's LiteRT `ca21dc99`/TensorFlow `a1179d3c` pin bump without the WORKSPACE plumbing that TensorFlow needs, so Bazel stops in the loading phase: `@rules_cc//cc:extensions.bzl` has no `compatibility_proxy_repo`. `native/bridge/v0181_workspace_build.patch` makes both files byte-identical to upstream main [`d99b438f`](https://github.com/google-ai-edge/LiteRT-LM/commit/d99b438f0a961ac2a449d341c2431e49332c1076), the same change (RevId 996789227) with the same pins: early `bazel_skylib` 1.9.0 and `rules_android` 0.7.2, `bazel_features_deps()`/`compatibility_proxy_repo()` after `tf_workspace3()`, and the MSVC XNNPACK AVX512-BF16 opt-out. It drops only the shadowed first pin assignment; effective pins are unchanged. |
| XNNPACK PF32 SME2 kernel rollback | Apply only to v0.18.1 (TensorFlow `a1179d3c`, XNNPACK `d89ef666`) | XNNPACK [`70a9c5e8ac`](https://github.com/google/XNNPACK/commit/70a9c5e8ac) moved the PF32 SME2 GEMM, GEMV and LHS packing to new KleidiAI kernels that return different f32 results from run to run with more than one thread on SME2 CPUs ([google/XNNPACK#11789](https://github.com/google/XNNPACK/issues/11789), [#82](https://github.com/leehack/litert-lm-native/issues/82)). v0.18.0 pins an XNNPACK from before it. `native/bridge/xnnpack_pf32_sme2.patch` reverts that commit's SME2 kernel wrappers and RHS-packing selection to the previous KleidiAI kernels, which the pinned KleidiAI still ships. The SME (non-SME2) path, other SME2 kernels and non-SME2 CPUs are unchanged. See the tracking section for determinism and speed. |
| XNNPACK SME2 PQS8/QC4W GEMM opt-out | Apply only to v0.18.1 (TensorFlow `a1179d3c`, XNNPACK `d89ef666`), after the PF32 rollback | XNNPACK [`76fa737a0`](https://github.com/google/XNNPACK/commit/76fa737a0b70fa506226b23432633e3781c2a470) sends int8-activation, int4-weight fully connected layers on SME2 CPUs to a packed-LHS path whose only kernel is the 32x32 SME2 MOPA one, so single-token decode runs it at M=1 ([google/XNNPACK#11793](https://github.com/google/XNNPACK/issues/11793), [#84](https://github.com/leehack/litert-lm-native/issues/84)). Gemma 4 E2B CPU decode on Apple M4 drops from about 45 to 30 tok/s. `native/bridge/xnnpack_pqs8_qc4w_sme2.patch` leaves the SME2 `pqs8_qc4w` GEMM config empty, so those layers keep the `qs8_qc4w` kernels v0.18.0 used. Non-SME2 CPUs are unchanged. See the tracking section for speed. |
| LiteRT CPU options identifier rollback | Apply only to v0.18.1 (LiteRT `ca21dc99`, audited Linux/Windows prebuilt `libLiteRt`) | LiteRT [`724a247cc5`](https://github.com/google-ai-edge/LiteRT/commit/724a247cc5) renamed the CPU options identifier from `xnnpack` to `cpu_options`. v0.18.1 compiles the host against a LiteRT with the rename but ships the 2026-09-28 prebuilt `libLiteRt` from before it, which Linux and Windows hosts link. Its XNNPACK accelerator finds no `xnnpack` options, so CPU inference ignores the thread count, weight cache and XNNPACK flags ([#89](https://github.com/leehack/litert-lm-native/issues/89)). `native/bridge/litert_cpu_options_identifier.patch` returns `xnnpack` again. Static runtimes (Android, Apple) read the identifier from the same function and are unaffected. See the tracking section. |

Primary sources:

- [v0.18 WORKSPACE](https://github.com/google-ai-edge/LiteRT-LM/blob/b2f686e2ed4718fb84ec398a61dd59ca0f0aff27/WORKSPACE)
- [LiteRT GPU environment](https://github.com/google-ai-edge/LiteRT/blob/26895c9fbcc25c43faa8c1a98cd1fd28951602c3/litert/runtime/gpu_environment.cc)
- [LiteRT GPU registry](https://github.com/google-ai-edge/LiteRT/blob/26895c9fbcc25c43faa8c1a98cd1fd28951602c3/litert/runtime/accelerators/gpu_registry.cc)
- [Sampler factory](https://github.com/google-ai-edge/LiteRT-LM/blob/b2f686e2ed4718fb84ec398a61dd59ca0f0aff27/runtime/components/sampler_factory.cc)
- [Android GPU qualification](android_gpu_qualification.md)

## #19 workaround tracking: untimed ASR alignment

The ASR workaround is carried only on the audited v0.18.0 merger preimage.
`upstream.sourcePatches` in schema-2 release manifests records the applied patch
path, SHA-256 and LF-normalized source pre/postimage hashes for source-built
runtimes; official prebuilts are outside that scope. Validators check the record.
This closes this workaround's provenance item, not #19's inventory of all other
source patches. Periodic/repeated-phrase ambiguity and empirical confidence
cutoffs are explicit release risks; the full 5s/30s trade-off table is in the
[qualification report](asr_untimed_overlap.md). Retirement requires an upstream
tagged equivalent, the model-free negative suite and packaged real-model proof.

## #77 workaround tracking: ASR `.litertlm` container routing

`tools/asr_litertlm_container_patch.py` pins the three patched v0.18.0 sources;
any other source fails closed and newer tags need an explicit decision. The
manifest records one `sourcePatches` entry per patched file. Retire the patch
when a tagged upstream release contains `bfdec21732`; upstream `main` has since
replaced `AsrEngine` with the Omni engine, so retirement moves with the bridge's
Omni migration.

## #78 workaround tracking: stream finish reasons

Upstream `ShouldStop` (`runtime/core/tasks.cc`) folds a stop token, the
output-token budget and a full KV cache into `TaskState::kDone`, and the
conversation C API forwards only text, final and error. Step counts cannot
recover the cause: a stop token sampled exactly at the budget step ends with
the same count as a cut-off reply. `native/bridge/stream_finish_reason.patch`
records which `ShouldStop` branch fired, in upstream precedence order, and
carries it through `Conversation` to the final conversation stream chunk.
`stream_proxy_finish_reason_abi_version()` returns 1 only for runtimes built
with the patch; see the [README](../README.md#bridge-finish-reasons).

`tools/stream_finish_reason_patch.py` pins the six patched v0.18.0 sources;
any other source fails closed and newer tags need an explicit decision. The
manifest records one `sourcePatches` entry per patched file. Session-API
streams and Web (`@litert-lm/core`) still report no cause. Retire the patch
when a tagged upstream release exposes an equivalent terminal cause.
`tools/litert_lm_finish_reason_smoke.py` is the opt-in real-model check.

## Stable v0.18.1 candidate

The explicit v0.18.1 carry decisions, dependency/provider delta, full inventory,
source controls and missing binary/device gates are in the
[local qualification report](v0181_qualification.md). No uncertain carry is
retired; the merged #80 finish-reason carry is retained on v0.18.1.

## v0.18.1 WORKSPACE build repair

Stock v0.18.1 does not build with Bazel: the release branch kept the old
`rules_cc` resolution that its own WORKSPACE comment says newer TensorFlow
cannot load. `tools/workspace_build_patch.py` pins the LF pre/postimage hashes
of `WORKSPACE` and `.bazelrc`; the repair runs on the extracted archive before
the owner WORKSPACE edits, and any other source fails closed. The manifest
records one `sourcePatches` entry per file. Retire it when a tagged upstream
release ships an equivalent WORKSPACE.

## #82 workaround tracking: XNNPACK PF32 SME2 kernels

v0.18.1 pins TensorFlow `a1179d3c`, whose XLA pins XNNPACK
`d89ef6669a14db203b3b7935b1b3862cb63fb6df`. That XNNPACK includes
`70a9c5e8ac`, which moved the PF32 SME2 GEMM, GEMV and LHS packing to new
KleidiAI kernels (`f32p4vsx1`). With more than one thread they give run-to-run
different f32 results. On an M4 Max, stock v0.18.1 Qwen3-0.6B greedy CPU chat
differed in 12 of 12 runs and EmbeddingGemma 2 audio embeddings differed
between calls.

`native/bridge/xnnpack_pf32_sme2.patch` reverts that commit in four files: the
`1x32` and `32x32` SME2 wrappers and the SME2 x32 LHS packer call the previous
`f32p2vlx1` KleidiAI kernels again, and the SME2 branch of
`init_pf32_gemm_config` packs weights with `xnn_pack_kai_f32_weights_and_biases_sme`,
the previous packer under its new name. The pinned KleidiAI still ships those
kernels. The commit's other changes (new `_sme2` packer, SME `pack_lh` guards,
tests, benchmarks) stay; the guards leave SME2 CPUs on the same LHS packing
routine v0.18.0 used.

`tools/xnnpack_pf32_sme2_patch.py` declares XLA's exact XNNPACK archive (same
SHA-256, strip prefix and URLs) ahead of `tf_workspace2()`, adding the patch;
XLA's `tf_http_archive` skips a repository that already exists. The WORKSPACE
edit fails closed if the effective TensorFlow pin changes or the WORKSPACE
already declares XNNPACK, and the build fails unless all four sources in
Bazel's `external/XNNPACK` match their pinned postimages. The manifest records
one `sourcePatches` entry per file. The patch applies to every target; it
changes code only on arm64 builds and behavior only on SME2 CPUs.

On an M4 Max at default threads, the rollback is deterministic (Qwen3 chat,
EmbeddingGemma 2 text, image and audio, Gemma 4 E2B text, image and audio) and
runs within 5% of v0.18.0-2 and stock v0.18.1 (median of 9 runs):

| Workload | v0.18.0-2 | Stock v0.18.1 | Rollback |
| --- | ---: | ---: | ---: |
| Qwen3-0.6B prefill / decode (tok/s) | 709 / 32.2 | 696 / 31.7 | 723 / 30.7 |
| EmbeddingGemma 2 image embedding (ms) | 321 | 328 | 325 |
| EmbeddingGemma 2 1 s / 11 s audio embedding (ms) | 76 / 457 | 77 / 451 | 76 / 448 |

Gemma 4 E2B text and image replies are byte-identical to stock v0.18.1, and its
audio transcript matches v0.18.0-2. Disabling the SME2 PF32 config instead
(f32 GEMMs on NEON) was also deterministic but cut Qwen3 prefill about 3x and
doubled image-embedding time. Routing SME2 CPUs to the SME PF32 kernels kept
speed but made image embeddings nondeterministic. Retire the patch when a
tagged upstream release pins an XNNPACK with a fix for google/XNNPACK#11789.

## #84 workaround tracking: XNNPACK SME2 PQS8/QC4W GEMM

XNNPACK `76fa737a0` (google/XNNPACK PR #10986), included in the `d89ef666`
pin, adds a packed-LHS fully connected path for int8 activations with
per-channel int4 weights on SME2 CPUs. It registers only the 32x32 SME2 MOPA
kernel; the 1x64 SME2 DOT kernel for one row exists only as a non-production
kernel (`NON_PROD_NEONSME2_MICROKERNEL_SRCS`), so production builds do not
compile it. Gemma
4 E2B's int4 layers therefore decode one token at a time through a 32-row
tile, which stops scaling beyond about four threads on Apple M4, instead of
v0.18.0's NEON `qs8_qc4w` 1x16c4 kernel.

`native/bridge/xnnpack_pqs8_qc4w_sme2.patch` gates off the SME2 branch of
`init_pqs8_qc4w_gemm_config`, so `xnn_init_pqs8_qc4w_gemm_config()` returns
NULL and XNNPACK's subgraph keeps the unpacked `qs8_qc4w` path. It is the second
patch on the XNNPACK archive declared for #82, applied after
`xnnpack_pf32_sme2.patch`; its `gemm-config.c` preimage is that patch's
postimage. The build checks the final postimage of every patched XNNPACK source,
and the manifest records one `sourcePatches` entry after the PF32 entries.

On an M4 Max at default threads (median of 9 runs over 3 interleaved rounds):

| Gemma 4 E2B CPU, tok/s | v0.18.0-3 | v0.18.1 with the PF32 rollback | Plus this opt-out |
| --- | ---: | ---: | ---: |
| Text prefill / decode | 594 / 44.9 | 684 / 29.9 | 582 / 46.8 |
| Image prompt decode | 45.8 | 30.3 | 46.5 |
| Audio prompt decode | 46.0 | 30.2 | 46.4 |

Gemma 4 and Qwen3 replies and EmbeddingGemma 2 vectors are byte-identical with
and without the opt-out and stay deterministic; Metal GPU decode is unchanged.
The opt-out gives back the path's prefill gain: about 15% at default threads and
3-4% at eight threads, but about 42-44% at one or two threads (293 to 172 and
525 to 292 tok/s on M4 Max). SME2 phones running few threads were not measured. Retire the patch when a tagged upstream release pins an
XNNPACK that registers a single-row kernel or otherwise fixes
google/XNNPACK#11793, verified on multithreaded SME2 decode.

## #89 workaround tracking: LiteRT CPU options identifier

Linux and Windows builds use `--define=litert_runtime_link_mode=dynamic`, so
`libLiteRtLm` creates compiled models through the upstream prebuilt
`libLiteRt` (`kLiteRtRuntimeBuiltin`). The host serializes CPU options under
`LrtGetCpuOptionsIdentifier()`, which LiteRT `ca21dc99` returns as
`cpu_options`; the prebuilt XNNPACK accelerator looks them up as `xnnpack`.
It finds nothing and creates the delegate with defaults: one thread, no weight
cache, default flags. v0.18.0 pins LiteRT `26895c9`, which still uses
`xnnpack`, so only v0.18.1 builds are affected.

`tools/litert_cpu_options_identifier_patch.py` pins the LF pre/postimage of
`litert/c/options/litert_cpu_options.cc` and the SHA-256 of the three
v0.18.1 prebuilt runtimes. Linux and Windows builds fail unless they link one
of those runtimes, and every build checks the postimage in Bazel's
`external/litert`. The manifest records one `sourcePatches` entry.

PR qualification runs `tools/litert_lm_cpu_threads_probe.py` on Linux x64,
Windows x64 and macOS arm64: a CPU session created with four threads must own
at least three more threads than one created with one thread.

Changing only the identifier string in a v0.18.1-3 Linux arm64 library
restores upstream scaling (Qwen3-0.6B CPU decode, tok/s, 64 tokens, Linux
arm64 container on M4 Max):

| Threads | v0.18.1-3 | Identifier patched | Upstream `litert-lm-api` 0.18.1 wheel |
| ---: | ---: | ---: | ---: |
| 1 | 11.4 | 11.8 | 11.6 |
| 4 | 11.5 | 25.5 | 25.8 |
| 8 | 11.5 | 28.7 | 28.3 |

Retire the patch when a tagged upstream release ships Linux and Windows
prebuilt runtimes built from its pinned LiteRT.

## #100 workaround tracking: Hugging Face grammar token bytes

Upstream v0.19.0 `83ce6067` gives llguidance the raw vocabulary returned by
`HuggingFaceTokenizer::GetTokens()`. A ByteLevel token such as `fÃ©` denotes
bytes `66 c3 a9` (`fé`), but the provider supplied `66 c3 83 c2 a9`. This
reproduces the schema failure after `{"ca` with the supported HF Qwen3 bundle.
It is independent of #48's original SentencePiece model-tokenizer repair:
ordinary inference on the supported HF bundle already emits correct Unicode.

`huggingface_token_bytes_v019.patch` adds a separate byte API for the provider;
raw vocabulary lookup and ordinary decoding stay intact. Its owner helper
inverts only an explicitly configured top-level ByteLevel decoder, before any
UTF-8 replacement. It preserves every token-ID slot, NUL, whitespace and partial
UTF-8. Added-token `special` flags are read by ID from the actual JSON inventory;
the provider prefixes their original spellings with llguidance's `0xff` marker.
Other added tokens follow ByteLevel's inverse map and whole-token fallback.
Configured provider special tokens still use their raw names. Other HF decoder
configurations return `Unimplemented` before creating the llguidance tokenizer;
SentencePiece's vocabulary mapping is unchanged and receives no new qualification.

The provider's `TextToTokenIds` callback accepts UTF-8 text, so it sets
`tokenize_assumes_string=true`. With the old false value, llguidance can send
an incomplete code point during forced-token computation to tokenizers-cpp's
`from_utf8(...).unwrap()`, aborting across its C ABI. llguidance 1.9.1 then
uses its lossless vocabulary trie for invalid UTF-8 spans and the actual text
tokenizer for valid spans. It never replaces invalid bytes with U+FFFD.

A model-free check of packaged owner `7ea10d0` (`libLiteRtLm` SHA-256
`8e028caab2819d6f4627b644ae9b6e79e37e40eab15814aa0092754b1722f782`)
reproduced SIGABRT on bytes `7b 22 63 61 66 c3` with the false value, at
`tokenizers_encode`'s UTF-8 unwrap. Changing only the flag to true passed
byte-exact incomplete UTF-8, isolated continuation, Japanese/emoji, NUL and
invalid-byte inputs. This isolates the callback contract; it does not qualify
model inference. Replaying the unchanged consumer schema (SHA-256
`1b55522bf6c9daa7a745be51da2dffd1609319e983c81b28a65b3ed4d82d405e`)
through the packaged grammar engine also aborts with false at an emoji
continuation byte (`8a 22`); true completes the fixed typed response in 20
mask/commit steps. No model is loaded in either check. The source controls
also reject a mutation restoring false.

Primary contract: [llguidance 1.9.1 tokenizer initialization](https://docs.rs/crate/llguidance/1.9.1/source/llguidance.h)
and [tokenizers-cpp v0.1.1 text encoding](https://github.com/mlc-ai/tokenizers-cpp/blob/v0.1.1/rust/src/lib.rs).

The build fails closed on changes to any of the six audited source preimages;
release `sourcePatches` records their patch and pre/postimage hashes. Newer tags
require an explicit carry or retirement decision. The model-free CI gate compiles
both actual patched HF and provider sources with raw-vocabulary/tokenizer-init
seams, checks byte lengths and special markers, and kills raw-vocabulary,
partial-UTF-8 replacement, special-spelling and text-callback contract regression
mutations. The default source controls do not execute the grammar or establish
model-backed release qualification.

Local full-vocabulary verification accepts a tokenizer extracted read-only from
the supported 613,722,264-byte Qwen3 artifact (`c5f39b41…`). Its tokenizer SHA-256
is `aeb13307a71acd8fe81861d94ad54ab689df773318809eed3cbe794b4492dae4`:
151,643 base entries, 26 added entries and 14 special IDs all match the independent
byte reference. To repeat with exact upstream source and that tokenizer:

```bash
python3 tools/qualify_huggingface_token_bytes.py \
  --source-root /path/to/LiteRT-LM --work-dir /tmp/hf-token-byte-check \
  --tokenizer-json /path/to/tokenizer.json --mutations
```

Retire this carry only after a tagged upstream byte-equivalent correction with
the UTF-8 callback contract and bounded-default formatting policy pass these
controls, and the unchanged supported-model schema qualifier, including literal
Unicode keys/values, succeeds against the packaged runtime.

### Default JSON formatting progress

The PR103 Mac diagnostic primary (`1a29401a…`) fixed the native abort but the
unchanged schema qualifier still failed: after the required `"empty":` key,
498 whitespace bytes occupied the remaining response. The original failure,
fixed 128-token budget, schema, adversarial BANANA prompt and typed oracle are
retained. This is a separate formatting-progress failure, not another UTF-8
callback defect.

The pinned llguidance 1.9.1 compiler defaults to the unlimited JSON skip regex
`[\x20\x0A\x0D\x09]+`. Model-free replay through that exact packaged grammar
and extracted supported-model tokenizer admits the observed byte path; `null`
and its prefix tokens remain legal throughout, while incorrect types and early
EOS are forbidden. Appending `null}` completes. Greedy longest-token and canonical
HF re-tokenizations both pass; actual generation token IDs and logits were not
captured, so these are byte-path controls, not a reconstruction of those values.

The provider now applies the documented once-per-gap pattern
`[\x20\x0A\x0D\x09]{1,8}` as its JSON-schema default. Ordered parsing preserves
property order. Explicit caller `whitespace_pattern` or `whitespace_flexible`
options, including unlimited formatting, retain their original input bytes.
Other `x-guidance` options retain their values. Boolean schemas retain their
meaning through an `allOf` wrapper; malformed schemas still reach llguidance's
existing validation. Regex and Lark constraints do not change. This deliberately
restricts insignificant JSON formatting and does not relax or rewrite schema
values, literal string whitespace, types or Unicode.

Compiled actual-provider controls preserve these contracts and kill mutations
restoring unlimited whitespace, overwriting caller options, sorting properties
and stripping literal spaces. The opt-in `grammar_runtime_test.cc` links actual
patched HF/provider sources to packaged llguidance and tokenizers, replacing only
the unused C++ constraint wrapper to access its C handle. It verifies eight
successive spaces are legal, the ninth is forbidden while `null` remains legal,
the retained loop is blocked, explicit unlimited formatting is respected, and a
Unicode string containing 20 literal spaces is unchanged. No weights are loaded.
This does not prove inference will complete, nor guarantee completion for every
schema within a caller's token budget.

Before constructing a DOM, the provider scans container nesting with bounded
state and no recursion, respecting quoted strings and escapes. Inputs deeper
than 128 containers pass unchanged to llguidance's existing validation; this is
a preprocessing bound, not a new public schema restriction. Independent review
found the original preprocessing could SIGSEGV on 200,000 nested `not` objects
(1,600,002 bytes), while the parent provider returned its existing INTERNAL
recursion-limit error. The depth guard preserves that controlled error before
any deep DOM insertion, serialization or destruction. Native subprocess controls
cover nesting at the boundary and 200,000 `not`/100,000 `allOf` wrappers; source
controls also preserve long quoted delimiters and escaped quotes, and remove the
guard as a genuine regression mutation. These tests load no model weights.


To repeat those optional host-linkable packaged grammar controls, add these
arguments to the full-vocabulary command above (all four are required):

```bash
  --runtime-library /path/to/libLiteRtLm.dylib \
  --llguidance-include /path/to/exact/llguidance-1.9.1 \
  --schema-json /path/to/unchanged-schema.json \
  --observed-output /path/to/retained-response.bin
```

The result records each input's SHA-256. The input is the extracted tokenizer,
not model weights. Primary contract: [pinned llguidance JSON whitespace handling](https://github.com/guidance-ai/llguidance/blob/f0971424ec072d3e4d4196bcc7f31a2f60527df9/docs/json_schema.md#whitespace-handling).
Existing [owner #100](https://github.com/leehack/litert-lm-native/issues/100)
tracks the remaining packaged qualifier. Retire the formatting part only after
a tagged upstream equivalent preserves explicit overrides, literal strings and
controlled overdeep-input errors,
passes the model-free controls, and passes the unchanged packaged-model qualifier.
