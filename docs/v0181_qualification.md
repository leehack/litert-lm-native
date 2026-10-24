# LiteRT-LM v0.18.1 local qualification

This prepares an owner candidate; it is not a published runtime or a consumer
pin. No carried protection is retired without equivalent upstream behavior and
its original trigger passing. Source equivalence does not qualify binaries.

## Exact inputs and stable delta

- Owner base: `8182448814867ad329be7e995b4e8aab5efd79c8` (main after
  [#79](https://github.com/leehack/litert-lm-native/pull/79) and
  [#80](https://github.com/leehack/litert-lm-native/pull/80)).
- Published owner baseline: [`v0.18.0-3`](https://github.com/leehack/litert-lm-native/releases/tag/v0.18.0-3),
  built from that same owner commit on upstream
  `b2f686e2ed4718fb84ec398a61dd59ca0f0aff27`, with overlap, container and
  finish-reason source patches.
- Stable candidate: upstream `v0.18.1`,
  `bda624851d74be34d4e1f7fac1fc4155939539c7`.
- [Upstream release](https://github.com/google-ai-edge/LiteRT-LM/releases/tag/v0.18.1)
  describes a source-build ABI repair for EmbeddingGemma 2. Its dependency change
  is `984426a2573bf19983910141616dacd9e680b4f9`: effective LiteRT
  `ca21dc99de51c76bdcc572afeea1dd937d3c9e5c`, TensorFlow
  `a1179d3c224967bd979950b823d5ce2a7e8f4c94`, and eight replaced constraint-provider
  payloads. The remaining three commits update demos, macOS packaging and SwiftPM.
- `git diff b2f686e2 bda62485 -- c runtime omni` is empty. This excludes the
  raw-main C API 1.0/Omni migration from this candidate; it proves neither an
  EmbeddingGemma success nor retained binary compatibility.
- WORKSPACE assigns LiteRT/TensorFlow twice; Starlark's final assignment wins.
  Teardown patch selection now follows the final LiteRT assignment. Bidirectional
  regression controls detect selecting the stale first pin.
- Stock v0.18.1 does not build with Bazel: the loading phase fails because the
  resolved `rules_cc` lacks `compatibility_proxy_repo`, which TensorFlow
  `a1179d3c` loads. The owner carries a WORKSPACE/.bazelrc repair whose
  postimages equal upstream main `d99b438f` (same change, same pins); see the
  [audit](upstream_patch_audit.md#v0181-workspace-build-repair).

The [source inventory](v0181_source_qualification.json) records exact commits,
all provider/Dawn LFS pointer identities, effective pins and four ASR preimages.
LFS object hashes identify intended payloads; they are not downloaded-byte proof.
Official v0.18.1 publishes both required C-runtime XCFramework archives.

## Carry and contract inventory

`Unverified` below means no exact tagged replacement/first release is established;
it never means that a protection is safe to remove. Existing owner revisions and
linked tests preserve the original reproduction recipes. Historical records are
not reruns on v0.18.1.

| Surface / original trigger and owner revision | Upstream equivalent / first release | v0.18.1 decision, provenance and decisive validation |
| --- | --- | --- |
| `litert_gpu_environment_destroy_callback.patch`: OpenCL load failure loses WebGPU destroy callback; `e486b51` (#67) | [LiteRT `9c8ae4e0fcdb3865a9b194509d0b69cb389af035`](https://github.com/google-ai-edge/LiteRT/commit/9c8ae4e0fcdb3865a9b194509d0b69cb389af035); first audited LM release v0.18.0 | Already inactive; keep historical allowlist and Android disassembly validator. Actual candidate LiteRT source sets `options_` before `InitializeOpenCl`; no device retirement claim. |
| `sentencepiece_bpe_null.patch`: untouched Qwen BPE NORMAL NUL rejected by SentencePiece 0.2.2; `5ca3c79` (#43) | Unverified; candidate still pins exact 0.2.2 archive `92381f71…8e1bcf1` | Keep all three source edits. Workspace hash/version guard accepts candidate. Existing sanitizer/token-ID/malformed-model qualifier remains required; not rerun here because its default downloads a model. |
| `litert_ios_framework_paths.patch`: accelerator dylib lookup cannot find bundled framework; `baef0ee` | Partial bare-name fallback exists in baseline and candidate LiteRT; complete bundle-path equivalent/first release unverified | Keep. `git apply --check --unidiff-zero` passes on actual candidate registry. Preserve upstream fallback. Physical device and Simulator unpatched bundle lookup are still missing. |
| Imperative iOS sampler path rewrite: dylib name differs from packaged framework; `baef0ee` | Unverified; candidate sampler source is unchanged | Keep. Production helper transforms candidate's actual source successfully. Still imperative and outside manifest `sourcePatches`; declaration/provenance follow-up remains #19. |
| Untimed ASR overlap patch: JFK boundary loss; `497e5ce` (#76), original `9e6187d` | Unverified; candidate merger is byte-identical | Keep unchanged patch bytes and LF pre/postimage guards for explicit v0.18.0/v0.18.1 allowlist. Actual merger replay, periodic/repetition negatives and mutation suite pass on candidate sources. Known garbled-input trade-offs remain [documented](asr_untimed_overlap.md). |
| ASR container patch: Whisper `.litertlm` incorrectly uses LLM route, missing `tf_lite_prefill_decode`; `3f8bce7` (#79) | `bfdec2173263f9ecd5b9515ef37d41d12145a250`; no released equivalent through v0.18.1 | Keep unchanged three-file backport. Exact candidate preimages match; production build test verifies postimages before Bazel. Packaged Whisper positive/missing-ASR/Qwen-metadata controls remain required. |
| Android Dawn rollback: Pixel Mali Vulkan device loss; `7a70690`, `dd86d49`, `a4bf19d` | Unverified | Keep both architectures and immutable commit `f73637c57f0940b53da184e0d5adfc52a4e55eef` plus existing full hashes. Candidate Android Dawn pointer bytes equal baseline; changed LiteRT dependency still requires Pixel hardware rerun. CPU/emulator cannot retire it. |
| Android v0.15 OpenCL sampler override: plugin mismatch; `c11034c` (#16) | Corrected payload `8bee4dddc3794958b4bdd8a3a4ba75bcb71f6fbb`; exact first tagged replacement unverified | Inactive on v0.18.1; retain v0.15 historical mapping and checksum/symbol tests. |
| iOS FST define/provider-free closure; `526b786` (#62) | Upstream disable gate exists; no provider-free official packaging equivalent established | Keep. Actual candidate BUILD passes all three provider dependency-gate checks. Continue binary undefined-symbol/load-command, floor <=16.4, and framework metadata checks; no iOS16.4 execution proof. |
| zlib mirror URL rewrite; `ec11a0f` and older fetch fixes | Accepted mirror list already present in v0.18.0 | Inactive extra rewrite on v0.18.1; helper accepts actual WORKSPACE. Keep historical fallback and checks. |
| Linux dynamic core/runtime sibling lookup; `8174e0e` (#50), `3eb4079` (#52) | Unverified | Keep matching tagged prebuilt core, dynamic define, SONAME/RUNPATH normalization and dependency closure checks; candidate Linux package not built locally. |
| Windows DXC companion pair; `941c308` (#55) | Unverified | Keep DXC v1.9.2602 archive/per-file digests and licenses. Unit staging checks pass; Windows shader execution missing. |
| Android 16 KiB ELF layout and global symbol visibility; `838b649` / runtime packaging | Packaging contract, no replacement established | Keep max/common page size, global-link flag and plugin/dependency validators. Android binaries not built locally. |
| macOS install-name identity, sibling framework layout and arm64-only support; `deef598` (#32), `a4e8050` (#41), `3d9572e` (#73) | Packaging/support contracts; upstream #71 invalid Metal signatures unresolved | Keep normalization before smoke, exact final-byte digest binding, arm64 closure, signing/platform checks and x64 rejection. Upstream packaging commit `22884c8b` is not code-signature execution proof. |
| Apple privacy manifests and binary-derived OS floors; `3200a6e` (#66), `ec6e83f` (#61) | Distribution contracts, not source fixes | Keep metadata, privacy, platform, minimum-OS and closure validators. No inferred macOS Metal or iOS qualification. |
| Windows package-path workaround; `6baac6e`, `c3318ae`; short Bazel root `3d40d7f` | Unverified | Keep bridge copy on Windows and nested-root source-patch negatives; no hosted Windows build here. |
| Immutable downloads/LFS materialization/retries, historical Intel rules_rust patches | Acquisition/historical support; no broad removal authority | Retain hash verification and drift rejection. Only supported eight source targets are qualified by current workflow; historical Intel logic does not restore macOS x64 support. |
| `stream_proxy_*` copied string ownership, callback ABI versions, global plugin loader; `008e851`, `b44761f`, `945ba69` | Permanent consumer FFI contract | Keep, including consumer freeing copied strings and proxy lifetime through final callback. Stable C headers are unchanged. Never substitute raw upstream callback ABI. |
| `litert_lm_asr_*` ABI v1, bounded push PCM, backpressure, final flush/reset, cancellation; `5c24b35` (#18) | No official equivalent through stable v0.18.1 | Keep [ASR contract](asr_bridge.md), C/C++ tests and symbol inventory. Cancellation is between windows; reset/delete follow caller serialization. Official Apple C archives remain provenance inputs, not speech runtime substitutes. |
| `v0181_workspace_build.patch`: stock v0.18.1 Bazel loading fails on `compatibility_proxy_repo` | Upstream main `d99b438f` (same RevId and pins); no tagged release | New, v0.18.1 only. Pre/postimage-hashed; postimages equal `d99b438f`. Applied before owner WORKSPACE edits; recorded per file in `sourcePatches`. |
| `stream_finish_reason.patch`: stop/length/context-exhausted causes folded into `kDone`; `8182448` (#80, #78) | No stable equivalent through v0.18.1 | Keep. All six LF preimages equal v0.18.0, so the gate admits v0.18.1 explicitly with unchanged pre/postimage hashes; real v0.18.1 sources patch cleanly and idempotently. CI ABI-only check and the opt-in real-model smoke remain the binary gates. |
| `xnnpack_pf32_sme2.patch`: XNNPACK `70a9c5e8ac` PF32 SME2 kernels give run-to-run different CPU results with more than one thread on SME2 CPUs; `7e59a01` (#83, #82) | None; [google/XNNPACK#11789](https://github.com/google/XNNPACK/issues/11789) open, no tagged LiteRT-LM release pins a fix | New, v0.18.1 only. Declares XLA's exact XNNPACK `d89ef666` archive ahead of `tf_workspace2()` with the patch; four LF pre/postimages, final postimages checked in Bazel's `external/XNNPACK` after every build, one `sourcePatches` entry per file. M4 Max determinism and speed are in the [audit](upstream_patch_audit.md#82-workaround-tracking-xnnpack-pf32-sme2-kernels). |
| `litert_cpu_options_identifier.patch`: Linux and Windows CPU inference ignores `num_threads` because the host names CPU options `cpu_options` and the prebuilt runtime reads `xnnpack` (#89) | None; v0.18.1 prebuilts predate LiteRT `724a247cc5` | New, v0.18.1 only. One LF pre/postimage, checked in Bazel's `external/litert` after every build; Linux/Windows builds also pin the prebuilt `libLiteRt` digests. PR qualification adds a CPU thread-count probe. See the [audit](upstream_patch_audit.md#89-workaround-tracking-litert-cpu-options-identifier). |
| `xnnpack_pqs8_qc4w_sme2.patch`: XNNPACK `76fa737a0` runs M=1 int4 decode on the 32x32 SME2 MOPA kernel, slowing Gemma 4 E2B CPU decode about 1.5x on Apple M4 (#84) | None; [google/XNNPACK#11793](https://github.com/google/XNNPACK/issues/11793) open, XNNPACK master still registers only the 32x32 kernel | New, v0.18.1 only. Second patch on the same archive, applied after the PF32 rollback; one LF pre/postimage whose preimage is the PF32 postimage, final postimage checked after every build, one `sourcePatches` entry. M4 Max speed is in the [audit](upstream_patch_audit.md#84-workaround-tracking-xnnpack-sme2-pqs8qc4w-gemm). |

[Issues #19](https://github.com/leehack/litert-lm-native/issues/19),
[#70](https://github.com/leehack/litert-lm-native/issues/70),
[#71](https://github.com/leehack/litert-lm-native/issues/71) and
[#75](https://github.com/leehack/litert-lm-native/issues/75) remain independent.
The linear-attention reuse bug has no stable runtime source change here.
No claim is made that dependency changes repair it without a model rerun.

## Local evidence and missing release gates

Exact-head evidence for this candidate (CI, local macOS arm64 build, packaged
checks and model runs) is recorded in the pull request, not here. The notes
below are the earlier source-only preparation pass.

- Owner tooling: 319 tests pass, 2 optional tests skipped. The first sandboxed
  run failed loopback HTTP binding; the authorized unrestricted rerun passes.
- New v0.18.1 tests cover both production patch calls before Bazel, idempotence,
  source drift, all four manifest records, both Dawn records, lost-provenance
  rejection, final-assignment selection and exact workflow pinning. Against
  owner main they fail (four tests; the assignment test has two subcases).
- Actual candidate merger: `qualify_asr_untimed_overlap.py --mutations` passes,
  compiling upstream/patched sources and testing the original constructed JFK
  boundary, timed/single-window controls, 5s/30s clean boundaries, confidence
  fixtures, periodic controls and all mutations. No inference occurs.
- Diagnostics: 21 tests pass. `actionlint`, Web scaffold self-test and
  `git diff --check` pass.
- Actual candidate source checks: provider-free FST gate, SentencePiece guarded
  workspace transformation, iOS sampler transformation, iOS accelerator patch
  check and all six #80 preimages pass.

No three-way packaged-runtime comparison of published v0.18.0-2, unpatched
v0.18.1 and patched v0.18.1 was performed. The before/after controls above
are source/tooling and real-merger replays only.

Not run: a complete source build; packaged export/dependency/signature/OS-floor
validation; EmbeddingGemma 2 CPU/GPU model inference; packaged Whisper/Moonshine/
Qwen-ASR; real multiwindow Whisper corruption/repetition; Qwen3.5 fresh-conversation
state reuse; Android Pixel/Mali, Galaxy S24, physical iOS16.4, Simulator, Windows
and Linux execution. Existing local Bazel storage had no reusable target execroot;
this bounded pass does not download a full new build closure or models.

The workflow now pins exact stable v0.18.1 for future CI qualification.
It still requires every existing platform, model, patch, artifact and publication
gate. Later/unknown compatibility tags fail closed. Source-patch records still
cover the ASR transformations only: the older source edits above remain a
provenance-inventory gap under #19, not a claim of complete manifest coverage.
No release identity, channel restriction, consumer checksum or default pin is
changed. Independent exact-head review is required before a candidate is ready.
