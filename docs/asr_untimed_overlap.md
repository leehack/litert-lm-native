# Untimed ASR overlap qualification (#673)

## Design and scope

Carry `native/bridge/asr_untimed_overlap.patch` on the exact audited v0.18.0
merger. Patch SHA-256: `665fe85a8a4e7f9abde048b3038ede1b4385aaac016aa90438210352b865e589`.
It applies before Bazel for archive builds and `--source-root`. Preimage and
postimage hashes normalize CRLF to LF, make application idempotent and reject
source drift. `.gitattributes` preserves patch bytes on Windows; `git apply`
accepts source context with either line ending and verifies the postimage.

This affects untimed presets using `TimestampTextMerger`, including Moonshine,
Whisper tiny and Qwen3-ASR, when both word chunks have no timestamps.
`tinygemma-asr` is also untimed but uses `LevenshteinTextMerger`, so it is
unaffected. Timed/mixed chunks,
zero overlap and first windows retain upstream behaviour. It changes no ABI,
model, preset, default overlap ratio or number of inference windows.

The first patch chose the longest exact canonical suffix/prefix with at least
two words, allowing one old trailing word and two new leading words to differ.
That is unsafe for periodic speech: a whole-window match confirms nothing.
It also mistakes nearby recurring phrases for acoustic overlap. The original
repetition test covered adjacent single-word repeats, not refrains or distant
phrase repetition. Its zero-regression conclusion did not generalize.

The revised patch uses the upstream word-count fallback unless all confidence
checks pass:

- Confirm at least one old word, with anchor start at least
  `max(1, floor(previous_words * (1 - overlap)) - search_window)`.
- Require one occurrence of the selected anchor in each window. All candidate
  matches, including shorter/trimmed ones, must agree on the alignment offset.
- Require at least three words when skipping/trimming; clean two-word anchors
  remain useful for preserving legitimate boundary repeats.
- Require at least six distinct canonical words and more than 50% distinct
  words in each window. Repeated bigrams rule out two-word anchors; if at least
  half the word positions start a recurring bigram, use upstream instead.
- Skipped new words must not occur in the old window, and trimmed old words
  must not occur in the new window. Shared words undermine a cut-word claim.

Accepted anchors retain old spelling and new continuation without a second
`DedupWords` pass. The confidence cutoffs are empirical conservative choices,
not a proof that text alone can locate acoustic overlap. The six-distinct-word
floor deliberately returns the audited mono/counting/chorus corpora to upstream.
It also sacrifices many good alignments in short or repetitive speech.

There is no clean trade-off retaining all original gains. Recommend this
conservative variant over the original patch: the JFK fix remains, periodic
streams match upstream event for event, and clean corpora have no measured
regressions. Garbled cases still have small regressions, especially at 30s.
Packaged-library real-model qualification remains required before release.

## Reproduce without models or downloads

```sh
# CODEX_TMP must name an existing writable temporary directory.
export TMPDIR="$CODEX_TMP"
python3 tools/qualify_asr_untimed_overlap.py \
  --source-root /path/to/LiteRT-LM-v0.18.0 \
  --work-dir "$TMPDIR/qualification" --mutations
python3 tools/evaluate_asr_overlap.py \
  "$TMPDIR/qualification/upstream" "$TMPDIR/qualification/fixed" \
  --output "$TMPDIR/audit-results.json"
LITERT_LM_ASR_SOURCE=/path/to/LiteRT-LM-v0.18.0 \
  python3 -m unittest discover -s tools -p test_asr_untimed_overlap.py
```

Requires a C++17 compiler, pkg-config and recent Abseil with status macros.
The runner compiles the actual original/patched upstream merger and unmodified
`levenshtein_align.cc` against actual stage headers. A LiteRT-to-Abseil status
macro alias avoids the inference dependency closure. Python only generates
windows/references and calculates edit distance; it does not emulate the merger.
The fast distance implementation is checked against the original simulator.
The source fixture is the exact upstream preimage with SHA-256
`6458bdfb32cbb32250c5be8843d303a9759da96f5675eae2d23a5f01f41dc826`.

## Full adversarial evaluation

The audit's `adv.py`, `real.py`, `mono.py` recipes are extended in
`tests/asr_overlap/adversarial.py` and `tools/evaluate_asr_overlap.py`.
`sim.py` remains unchanged. Ordinary/adjacent use its original timing recipe;
other rows use pause probabilities 0.12 and 0.35 from the audit. Seeds are
101/202/303, except prose 5/17/29/41. There are 400 cases per seed/schedule
(prose uses 400 rather than the audit script's 500). The prose tokens are frozen
from the same LICENSE/documentation extraction recipe; provenance and checksum
are in `prose.source.json`. These are simulated windows, not audio inference.

At 5s, utterances have 20–45 words. At 30s, word counts scale sixfold to 120–270
so the evaluation still exercises multiple boundaries; using 20–45 words would
mostly test only single windows. Overlap is 0.4 throughout. Each clean/garbled
row uses the same timing/reference recipe but can produce different cut tokens.
Ordinary/adjacent each use one pause schedule; the others use both.

R = upstream-exact to patched-inexact; F = upstream-inexact to patched-exact;
W = utterances with higher word edit distance, including already-inexact cases.
These are utterance counts against **upstream 0.4**, not WER percentages.

| Corpus | Seconds | Utterances | Clean R / F / W | Garbled R / F / W |
| --- | ---: | ---: | ---: | ---: |
| Ordinary | 5 | 1,200 | 0 / 31 / 0 | 0 / 367 / 0 |
| Adjacent word repeats | 5 | 1,200 | 0 / 107 / 0 | 0 / 214 / 0 |
| Natural | 5 | 2,400 | 0 / 38 / 0 | 0 / 459 / 0 |
| Phrase repeats | 5 | 2,400 | 0 / 5 / 0 | 0 / 56 / 1 |
| Distant bigrams | 5 | 2,400 | 0 / 15 / 0 | 0 / 376 / 1 |
| Real prose | 5 | 3,200 | 0 / 4 / 0 | 0 / 576 / 0 |
| Periodic | 5 | 2,400 | 0 / 0 / 0 | 0 / 0 / 0 |
| Ordinary | 30 | 1,200 | 0 / 86 / 0 | 1 / 150 / 8 |
| Adjacent word repeats | 30 | 1,200 | 0 / 683 / 0 | 1 / 640 / 2 |
| Natural | 30 | 2,400 | 0 / 342 / 0 | 1 / 381 / 16 |
| Phrase repeats | 30 | 2,400 | 0 / 7 / 0 | 0 / 10 / 0 |
| Distant bigrams | 30 | 2,400 | 0 / 473 / 0 | 4 / 561 / 11 |
| Real prose | 30 | 3,200 | 0 / 348 / 0 | 2 / 471 / 16 |
| Periodic | 30 | 2,400 | 0 / 0 / 0 | 0 / 0 / 0 |

Natural mixes function/content words and recurring phrases; phrase-repeat
repeats n-grams 2–3 times; distant-bigram repeats two-word phrases with gaps
0–3. Periodic combines `no`, `la la la la hey`, and `one two three` loops.
The baseline is already very inaccurate on periodic speech: falling back
prevents the new collapse but does not repair upstream transcript loss.

For example, the audit mono.py 192-word counting-loop recipe produces 123 words
upstream and with the revised patch, versus 24 with the original patch. The
native qualifier additionally checks all intermediate output bytes for 24
periodic sequences (96/192 words, 5/30s, clean/garbled, three patterns).
Accepted matches must confirm a nonempty prefix, preventing the original
whole-window anchor from retaining the same pending window indefinitely.

The 5s clean phrase-repeat row changed from the original patch's **462 regressed,
260 fixed, 1,167 edit-distance-worse** to **0 / 5 / 0**. Distant-bigram changed
from **375 / 123 / 401** to **0 / 15 / 0**. This deliberately loses most of the
original repetition gains. On ordinary, natural and prose 5s garbled inputs,
the revision retains roughly 56–62% of the original exact fixes. At 30s it
retains roughly 65–71% for those corpora, with small nonzero regressions.
All nine 30s garbled upstream-exact → patched-inexact cases (1 ordinary,
1 adjacent, 1 natural, 4 distant-bigram, 2 prose) first lose reference alignment
at a fast-path ↔ upstream-fallback transition. The paths retain different
pending overlap text; switching after a corrupt cut can then duplicate or drop
words at the next boundary. The first bad confirmation is at that transition,
not necessarily at the first fast-path match. This is a state-history effect,
not evidence that the confidence rules prove alignment on corrupted speech.

The actual 30s preset is **Whisper tiny** (`whisper_tiny_30s_i8.tflite`). The
30s rows are simulated text windows, not Whisper inference. Still owed before
release: real Whisper-tiny audio at overlap 0.4 spanning multiple 30s windows,
including corrupted cuts and repeated speech, with confirmed/pending emissions
captured through fast-path/fallback transitions and compared against upstream
using the packaged candidate library. Model-backed Moonshine JFK and Qwen3-ASR
qualification remain separate gates. No claim of zero regressions on
repetition-heavy or corrupted speech is made.
The complete prior/revised rows, exact totals, edit improvements and examples
are in [audit_results.json](../tests/asr_overlap/audit_results.json).
Original three-seed qualification results and mutations are in
[results.json](../tests/asr_overlap/results.json).

## CI and negative tests

`pr_release_qualification.yml` has a required `asr-compatibility` lane alongside
SentencePiece qualification. It checks out the exact pinned upstream commit,
installs Abseil/pkg-config, and runs the real-merger qualifier with `--mutations`.
Build, verification and the aggregate result require its success. No model is
needed by this lane. The shared tooling suite also tests patch application.

Homebrew's stock `brew install abseil` is an unversioned formula; that command
cannot select an exact release. Pinning it would require maintaining an
extracted formula/tap and compatible bottles. This lane keeps the stock formula
and guards **all seven pkg-config names** (including internal logging names)
before compiling, with an actionable error on removal/renaming. It records each
package version in `results.json`; the real compile additionally checks the
headers/link interface. This is an explicit interface guard, not a version pin.

The Bazel `litert_lm_asr_merger_test` has the same `:asr_api` compatibility
selector as adjacent ASR tests. No existing workflow runs Bazel tests; adding
a full Bazel dependency fetch is not cheap for this sparse, model-free lane.
The lane compiles and runs that exact C++ test source directly, but the Bazel
`cc_test` target itself is **not run**.

Native tests cover the JFK constructed repro, two-word boundary repeats,
corrupt edges, one-word fallback, empty canonical anchors, both mixed timestamp
transitions, reset and idempotent flush. Differential controls compare all
confirmed/unconfirmed bytes for 400 timed sequences and 400 single windows at
ratios 0, 0.4, 0.6, plus repeated-phrase and periodic negatives at 0.4.

The qualifier also enforces clean R == 0 and W == 0 against upstream at 0.4
on natural, phrase-repeat and distant-bigram corpora, at both 5s and 30s. It
uses all 400 utterances per seed/schedule (2,400 per row), sharing generated
references and upstream distances across surviving mutants. Mutants already
killed by a native test, frozen fixture or differential control skip the more
expensive clean check; the combined weakening always runs it. The driver and
Levenshtein object files compile once per invocation; each mutated merger is
still compiled separately. Objects are never reused across invocations. Original qualification rows use
the same exact bit-vector edit distance as the larger evaluator (validated
against `sim.ops`), avoiding the older Python DP runtime without changing any
row values.

`confidence_fixtures.json` freezes 15 small, deterministic confirmed/pending
traces. Each confidence guard has an isolated witness: offset consistency,
anchor uniqueness in each window, short tolerant anchors, both distinct-word
cutoffs, both repeated-bigram checks, skipped/trimmed shared words and earliest
start. Surface spelling and three-window history expose otherwise invisible
state changes. Existing native cases also protect search slack, skip/trim,
spelling and continuation repeats. The carried matcher and patch hashes are
unchanged.

The exact `--mutations` CI command now compiles the original six mutations,
all U1–U19 from `mine/mymut.py`, and the auditor's combined weakening. The latter
also changes the earliest floor to zero, as its saved `.cc` does. Eighteen U
mutations and the combination are killed; U16 is behaviour-equivalent with all
other guards intact. CI compares all 28 clean/garbled rows at 40 cases per
seed/schedule, including final text **and every confirmed/pending byte**,
requiring zero output or evaluation differences. The independent full 400-case
comparison covers 60,800 utterances with zero differences; this larger
comparison is recorded in `confidence_results.json` rather than repeated on
every CI run. Reproduce the full equivalence audit by adding
`--equivalence-count 400` to the qualifier command.

U16 proof: equal end and length fix the same start; different skip means a
different alignment offset and is rejected. For equal-length untrimmed/trimmed
ties, equal offsets require both start and skip to move back one position. The
untrimmed choice then skips a word present in the old anchor, failing
skip-shared; the trimmed choice discards an old word present in the untrimmed
current anchor, failing trim-shared. Both choices fall back. The tie rule is
retained unchanged; it is not an independent confidence guard.

The mutation script extends the audit's `mut/mut.py`, and the CRLF matrix extends
`crlf.sh`/`crlf2.sh` with LF/CRLF source and autocrlf true/false, Windows-style
patch checkout, idempotence and incorrect-postimage rejection.

## Provenance, limits and retirement (#19)

The schema-2 manifest now records this workaround in `upstream.sourcePatches`,
including its repository path, patch SHA-256 and LF-normalized pre/postimage
SHA-256 values. Validation rejects missing or altered v0.18.0 patch provenance.
Its scope explicitly excludes official upstream prebuilts; the patch is applied
to source-built runtimes. Older compatibility fixtures retain their shape.
This completes the ASR provenance item for [#19](https://github.com/leehack/litert-lm-native/issues/19),
not the inventory of every carried workaround. See the
[carried-fix tracking text](upstream_patch_audit.md) and
[unposted upstream draft](asr_untimed_overlap_upstream_issue.md).

Third-round evidence (macOS arm64, 2026-10-16): the matcher patch bytes and
all 28 evaluation rows, including examples, remain unchanged. Tools discovery
ran 301 tests: 299 passed, with the Linux-only loader and optional redundant
source-driven unittest skipped. The real-source qualifier runs separately.
The final `--mutations` CI command completed in 85 seconds locally; its original
27 qualification rows and mutation outcomes are unchanged by the runner's
runtime optimizations. Actionlint, Python compilation and `git diff --check`
passed. The updated
[confidence evidence](../tests/asr_overlap/confidence_results.json) records the
mutation kill table, full U16 equivalence and exact CI replays with regenerated
patches and updated postimage hashes. All 18 behaviour-changing single mutants
and the combined weakening exit nonzero; U16 exits zero and is equivalent.
Earlier-round diagnostics (21), web self-test and schema-2 fixture byte
comparison also passed. Windows checkout/application
behaviour was simulated with Git configuration; windows-latest itself was not
run. Full runtime/Bazel linking, eight-platform packaging, device tests and
model-backed JFK/Whisper/Qwen3-ASR inference were not run. The provided source
slice is sufficient for the merger but lacks the full Bazel workspace/dependency
closure. No weights or large artifacts were downloaded; no port 8080 was bound.
The JFK repro remains constructed text, not captured Moonshine emissions.

Retire the workaround when an upstream tagged equivalent passes these same
replays, repetition/periodic controls and published-artifact model qualification.
Requalification is required on source/version drift. Newer tags than v0.18.0
(and unknown/non-release refs used as compatibility tags) now fail closed in
both source building and release-manifest generation/validation. Supporting one
requires a checked-in revalidated patch or a version-specific opt-out with
evidence in `tools/asr_overlap_patch.py` and this document; there is no CLI or
environment bypass. Older tags retain their pre-workaround behavior. A future immutable
`v0.18.0-N` rebuild must qualify all source platforms and regenerate manifests,
checksums, SPM archives and release evidence before downstream adoption. Keep
Moonshine's default 0.4 overlap. No release or downstream pin change is part of
this follow-up.
