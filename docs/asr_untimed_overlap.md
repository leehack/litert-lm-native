# Untimed ASR overlap qualification (#673)

## Design and scope

Carry `native/bridge/asr_untimed_overlap.patch` on the exact audited v0.18.0
merger. Its SHA-256 is `146edea2ddb06f1cc2f257604639336a142c2a99d31e482498462b7cf594f155`.
The build applies it before Bazel for both archive builds and `--source-root`.
Original and patched source hashes make application idempotent and fail closed
on drift. Other compatibility versions are unchanged.

The patch aligns the longest canonical exact suffix/prefix of at least two
words, allowing at most one trailing old word and two leading new words to be
corrupted by a cut boundary. It retains the old overlap spelling and the new
continuation, including repeated words, without `DedupWords` on that path.
Ties favor fewer old trailing words removed, then fewer new leading words
skipped. If there is no anchor, the existing algorithm remains the fallback.
Only two entirely untimed word chunks enter this path. The zero-overlap and
first-window branches precede it; timestamped words bypass it.

This is a 43-line declarative patch to one upstream function, rather than a
second merger in the C ABI bridge. It fixes the upstream stage before confirmed
text becomes irreversible and avoids changing ABI/config defaults or copying
session state into the bridge. In keeping with [#19](https://github.com/leehack/litert-lm-native/issues/19),
it has a pinned preimage, model-free repro, separate upstream issue draft, and
removal condition: an upstream tagged equivalent must pass this replay and
published-artifact Moonshine/JFK qualification, plus timed/repeated-word controls.
New source/version adoption needs explicit requalification, not blind rebasing.
This does not complete #19's existing source-patch manifest inventory work.

Untimed text cannot distinguish every real repeated phrase from acoustic
overlap. The zero-regression claim below is limited to these evaluated corpora;
short/ambiguous no-anchor cases still use upstream's heuristic. This patch does
not claim a universal ASR correctness guarantee or fix memory growth.

## Reproduce without models or downloads

```sh
export TMPDIR=/private/tmp/claude-501/-opt-UnitySrc-personal-llama-llamadart/d3f6dc35-082b-480b-9a68-73f9c56abb4d/scratchpad/codex/tmp673n
python3 tools/qualify_asr_untimed_overlap.py \
  --source-root /path/to/LiteRT-LM-v0.18.0 \
  --work-dir "$TMPDIR/qualification"
LITERT_LM_ASR_SOURCE=/path/to/LiteRT-LM-v0.18.0 \
  python3 -m unittest discover -s tools -p test_asr_untimed_overlap.py
```

Requires a C++17 compiler, pkg-config, and recent Abseil with status macros.
The runner compiles actual original/patched upstream `timestamp_text_merger.cc`
and unmodified `levenshtein_align.cc` against actual upstream stage headers.
It uses only a temporary LiteRT-to-Abseil status macro alias to avoid fetching
the full inference dependency closure. It does not approximate the merger in
Python. `tests/asr_overlap/sim.py` is the supplied auditor's simulation, retained
unchanged; its Python generates inputs/reference words only. The new replay
driver extends the auditor's `driver.cc` with timed inputs, event-level output,
reset/flush checks, and deterministic C++ regression cases.

The original source fixture is copied verbatim from the supplied v0.18.0 source
and matches SHA-256 `6458bdfb32cbb32250c5be8843d303a9759da96f5675eae2d23a5f01f41dc826`.
It is a patch application test preimage, not vendored runtime source.

## Measurements

Seeds 7, 11, 23; 400 utterances of 20-40 words per seed; 5-second windows,
step `5 * (1 - overlap)`. Clean boundaries retain or omit cut words according
to their visible fraction; garbled boundaries can replace cut words with
one/two garbage tokens. Both preserve the auditor's timings and RNG recipes.
Each ratio uses its corresponding windows. Exact means identical space-joined
reference tokens. Fixed means inexact at upstream 0.4, exact in the variant;
regressed means exact at upstream 0.4, inexact in the variant. These are counts
of utterances, not edit-distance improvements or inference measurements.

| Boundary | Seed | Variant | Exact / 400 | Fixed | Regressed |
| --- | --- | --- | ---: | ---: | ---: |
| Clean | 7 | upstream@0.4 | 391 | 0 | 0 |
| Clean | 7 | upstream@0.6 | 381 | 7 | 17 |
| Clean | 7 | fixed@0.4 | 400 | 9 | 0 |
| Garbled | 7 | upstream@0.4 | 203 | 0 | 0 |
| Garbled | 7 | upstream@0.6 | 263 | 115 | 55 |
| Garbled | 7 | fixed@0.4 | 381 | 178 | 0 |
| Clean | 11 | upstream@0.4 | 389 | 0 | 0 |
| Clean | 11 | upstream@0.6 | 387 | 10 | 12 |
| Clean | 11 | fixed@0.4 | 400 | 11 | 0 |
| Garbled | 11 | upstream@0.4 | 193 | 0 | 0 |
| Garbled | 11 | upstream@0.6 | 262 | 133 | 64 |
| Garbled | 11 | fixed@0.4 | 380 | 187 | 0 |
| Clean | 23 | upstream@0.4 | 391 | 0 | 0 |
| Clean | 23 | upstream@0.6 | 382 | 8 | 17 |
| Clean | 23 | fixed@0.4 | 400 | 9 | 0 |
| Garbled | 23 | upstream@0.4 | 192 | 0 | 0 |
| Garbled | 23 | upstream@0.6 | 263 | 123 | 52 |
| Garbled | 23 | fixed@0.4 | 380 | 188 | 0 |

Aggregate counts (1,200 utterances per row):

| Boundary | Variant | Exact | Fixed | Regressed | Windows |
| --- | --- | ---: | ---: | ---: | ---: |
| Clean | upstream@0.4 | 1171 | 0 | 0 | 6534 |
| Clean | upstream@0.6 | 1150 | 25 | 46 | 8926 |
| Clean | fixed@0.4 | 1200 | 29 | 0 | 6534 |
| Garbled | upstream@0.4 | 588 | 0 | 0 | 6534 |
| Garbled | upstream@0.6 | 788 | 371 | 171 | 8926 |
| Garbled | fixed@0.4 | 1141 | 553 | 0 | 6534 |
| Repeated, clean | upstream@0.4 | 477 | 0 | 0 | 6534 |
| Repeated, clean | upstream@0.6 | 291 | 136 | 322 | 8926 |
| Repeated, clean | fixed@0.4 | 1125 | 648 | 0 | 6534 |

The repetition stress corpus replaces each token after the first with its
preceding token at probability 0.3, preserving timestamps. It uses the same
seeds/counts, with a fresh deterministic RNG stream after utterance generation.
Clean ordinary and repetition-heavy inputs also have zero edit-distance
regressions (including cases already inexact upstream). On garbled input,
586 utterances improve edit distance and one already-inexact utterance worsens:
seed 23, case 156 retains one extra `tree` garbage word (3 insertions versus
upstream's 2), without dropping a reference word. Thus zero exact-to-inexact
regressions does not imply zero error-count increases on corrupted input.
Per-seed repetition counts, edit-distance comparisons, and window totals are in
[`tests/asr_overlap/results.json`](../tests/asr_overlap/results.json).

The fixed C++ unit tests cover clean suffixes, two corrupt new-prefix words,
one corrupt old-suffix word, repeated words and phrases across boundaries,
single windows with repetitions/punctuation, empty windows, zero overlap,
reset and idempotent final flush. The JFK three-window constructed repro
reproduces the exact reported upstream duplicate and yields the complete
normalized reference with this patch. It is **not captured Moonshine output**
and no real-model JFK inference was run: no cached model was available and
weights were not downloaded. Published-library real-model validation remains
required before release/adoption.

400 timed sequences and 400 single-window cases compare every confirmed and
unconfirmed event byte for byte, including flush, at ratios 0, 0.4, and 0.6:
all unchanged. No additional inference windows are introduced by the patch.

## Local build/test evidence (macOS arm64, 2026-10-16)

- C++17 compilation and execution of real original/patched merger targets:
  passed, including native unit cases and quantitative replay.
- Full tools discovery with `LITERT_LM_ASR_SOURCE` set: 292 tests,
  291 passed, 1 skipped (Linux-only loader coverage). An earlier run had one
  transient environmental error: `xcodebuild -create-xcframework` exited 70
  because `IDESimulatorFoundation` could not load `CoreSimulator.framework`.
  The full rerun, including that fixture and the opt-in merger test, passed.
- Diagnostics: 21 passed. Web self-test, actionlint, Python compilation, and
  schema-2 fixture byte comparison passed.
- Publication lifecycle: 29 attempted; 1 passed and 28 stopped in setup because
  only Bash 3.2 is installed; this suite requires Bash 4+.
- Bazel 7.6.1 merger/bridge test invocation in an isolated source tree with
  `--repository_disable_download` stopped during repository loading:
  `rules_shell` is not cached and downloads are disabled. An initial `--nofetch`
  attempt also lacked the built-in `bazel_tools` repository. Therefore the
  Bazel bridge audio-source and upstream gtest targets, full runtime linking,
  eight-platform builds, packaged-library/device/model smokes were not run.
  No model weights or large artifacts were downloaded and no port 8080 was used.

Focused checks also passed: 4 ASR tests (including the complete real-source
qualification), 4 bridge C/C++ callback/session lifecycle tests, and 20 upstream
build/patch tooling tests.

## Downstream adoption

After review/merge and full qualification, publish a new immutable same-upstream
rebuild `v0.18.0-N` (next available numeric rebuild; never `-native.N`), retaining
the exact upstream SHA and recording the new native commit. Rebuild all eight
source runtime targets (Android arm64/x64, iOS arm64/arm64-sim, Linux x64/arm64,
macOS arm64, Windows x64), repackage their native archives and Apple SPM
XCFramework zips, and regenerate checksums, manifest and release evidence.
Official upstream assets/companion prebuilts retain their upstream bytes.
llamadart then updates native hook pins and Apple SPM URLs/checksums together,
after published-artifact CPU ASR/JFK exact-WER and timed-model qualification.
Do not change Moonshine's default 0.4 overlap.
