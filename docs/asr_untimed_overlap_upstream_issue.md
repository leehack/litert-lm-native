# Draft: Untimed TimestampTextMerger repeats corrupted overlap boundaries

Target: google-ai-edge/LiteRT-LM. Draft only; not posted.

In v0.18.0 (`b2f686e2ed4718fb84ec398a61dd59ca0f0aff27`),
`TimestampTextMerger` estimates untimed overlap using word counts, searches
near that estimate with Levenshtein distance, then splits at a word-count pivot
and calls `DedupWords`. A corrupted leading word can leave a duplicated overlap.
Moonshine's stateless decoder emits words without timestamps.

Minimal model-free repro: feed these three untimed `std::vector<Word>` outputs
to a `TimestampTextMerger(&source, /*overlap_ratio=*/0.4f)`, call `Schedule()`
after each, then `Flush()`. Concatenate every `confirmed_text`:

```text
And so my fellow Americans ask not.
ask not. what your country can do for you.
One tree can do for you, ask what you can do for your country.
```

Actual:

```text
And so my fellow Americans ask not. what your country can do for you. tree can do for you, ask what you can do for your country.
```

Expected: preserve the preceding intact overlap and append the continuation
once, yielding `...what your country can do for you. ask what you can do for
your country.` These are constructed windows reproducing the reported JFK
failure, not captured model emissions.

Raising the overlap is not a general solution: in a 5-second-window simulation
with seeds 7/11/23, 400 utterances each, upstream 0.6 regressed 46 clean cases
that were exact at 0.4, fixing 25. It also used 8,926 windows versus 6,534.

The original candidate chose the longest canonical suffix/prefix anchor,
allowing one corrupt old trailing word and two corrupt new leading words. An
independent audit rejected it: periodic speech could retain only one window
(192 counting-loop words became 24 versus upstream's 123). On clean 5s
phrase-repeat inputs it regressed 462 exact cases while fixing 260; distant
bigrams regressed 375 while fixing 123. The old "repetition-heavy" evidence
covered adjacent single-word repeats and did not justify that general claim.

The revision confirms a nonempty old prefix in the expected search region,
requires a unique anchor and consistent candidate offsets, and uses conservative
lexical-diversity/repetition guards. Skips/trims require at least three anchor
words and cannot discard shared words. Ambiguous/low-diversity chunks retain
upstream behaviour. It affects all untimed presets, including Moonshine,
Whisper tiny and Qwen3-ASR; mixed/timed chunks bypass it.

The constructed JFK fix remains. At 5s the revised phrase-repeat row is
0 regressed / 5 fixed / 0 edit-distance-worse, distant bigrams 0 / 15 / 0.
Periodic clean/garbled streams match upstream, including every intermediate
event in the dedicated negatives. This sacrifices most repetition gains.
Ordinary/natural/prose garbled 5s rows keep about 56–62% of the original exact
fixes. At 30s small garbled regressions remain. There is no universal
zero-regression claim; text alone cannot resolve all acoustic ambiguity.
The complete per-corpus 5s/30s counts, seeds, methods and limits are in
[the downstream qualification report](asr_untimed_overlap.md).

Timed and single-window differential controls remain byte-identical. The
model-free native tests kill the one-word-anchor, three-word-minimum,
mixed-timestamp and empty-canonical mutations. Packaged real-model validation
is still required; no weights were downloaded for these measurements.

Downstream report: https://github.com/leehack/llamadart/issues/673
Compatibility/retirement tracker: https://github.com/leehack/litert-lm-native/issues/19
