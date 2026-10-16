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

A candidate fix first finds a canonical exact suffix/prefix of at least two
words, allowing one corrupt trailing old word and two corrupt leading new
words. It keeps the old overlap and new continuation without a second dedup
pass; without an anchor, it retains the existing fallback. Restricting this to
pairs of entirely untimed chunks leaves timed and single-window outputs
unchanged. This produced 1,200/1,200 exact clean and 1,141/1,200 exact garbled
cases, with zero exact-to-inexact regressions against 0.4 in either set. A
separate repetition-heavy clean set also had zero such regressions. Clean
inputs also had zero edit-distance increases. One already-inexact garbled case
retained one additional garbage token; no claim of perfect corrupt-edge
recovery is made. Untimed
repeated phrases remain inherently ambiguous; this is bounded evidence, not a
proof for arbitrary speech.

Downstream report: https://github.com/leehack/llamadart/issues/673
Compatibility/retirement tracker: https://github.com/leehack/litert-lm-native/issues/19
