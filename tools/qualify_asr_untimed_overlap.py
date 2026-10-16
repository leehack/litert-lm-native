#!/usr/bin/env python3
"""Compile real upstream merger stages and evaluate without fetching any assets."""
from __future__ import annotations

import argparse
import json
from functools import lru_cache
import random
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from build_upstream_runtime import patch_asr_untimed_overlap

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests/asr_overlap"))
from sim import utter, windows  # noqa: E402


ABSL_PACKAGES = (
    "absl_status", "absl_statusor", "absl_status_macros", "absl_strings",
    "absl_synchronization", "absl_log_internal_message", "absl_vlog_config_internal",
)


@lru_cache(maxsize=1)
def abseil_flags() -> tuple[list[str], list[str]]:
    missing = [name for name in ABSL_PACKAGES if subprocess.run(
        ["pkg-config", "--exists", name], capture_output=True).returncode]
    if missing:
        raise RuntimeError("Abseil pkg-config interface changed or is missing: "
                           + ", ".join(missing) + "; install/requalify Abseil "
                           "before updating the replay lane")
    return tuple(shlex.split(subprocess.check_output(
        ["pkg-config", option, *ABSL_PACKAGES], text=True))
        for option in ("--cflags", "--libs"))


def compiler_command(source: Path, work: Path) -> list[str]:
    compiler = shutil.which("clang++") or shutil.which("c++")
    if not compiler:
        raise RuntimeError("A C++17 compiler is required")
    cflags, _ = abseil_flags()
    return [compiler, "-std=c++17", "-O2", "-Wall", "-Wextra",
            "-I", str(source), "-I", str(work), *cflags]


@lru_cache(maxsize=None)
def compile_shared_objects(source: Path, work: Path) -> tuple[Path, Path]:
    # Reuse only within this process, never stale objects from a previous run.
    # Every mutant still compiles its own actual merger implementation.
    outputs = []
    for name, unit in (("driver", REPO / "native/bridge/litert_lm_asr_merger_test.cc"),
                       ("levenshtein", source / "omni/asr/levenshtein_align.cc")):
        output = work / (name + ".o")
        subprocess.run([*compiler_command(source, work), "-c", str(unit),
                        "-o", str(output)], check=True)
        outputs.append(output)
    return tuple(outputs)


def compile_driver(source: Path, work: Path, merger: Path, output: Path) -> None:
    shared = compile_shared_objects(source, work)
    _, ldflags = abseil_flags()
    subprocess.run([*compiler_command(source, work), str(merger),
                    *map(str, shared), *ldflags, "-o", str(output)], check=True)


def compile_replays(source: Path, work: Path) -> tuple[Path, Path]:
    work.mkdir(parents=True, exist_ok=True)
    patched = work / "patched"
    target = patched / "omni/asr/timestamp_text_merger.cc"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source / "omni/asr/timestamp_text_merger.cc", target)
    patch_asr_untimed_overlap(patched, "v0.18.0")
    # The merger uses only LiteRT's status macro. This alias avoids fetching
    # the full LiteRT dependency closure and preserves the same status behavior.
    shim = work / "litert/cc/litert_macros.h"
    shim.parent.mkdir(parents=True, exist_ok=True)
    shim.write_text('#include "absl/status/status_macros.h"\n'
                    '#define LITERT_ASSIGN_OR_RETURN ABSL_ASSIGN_OR_RETURN\n')
    outputs = []
    for name, merger in (("upstream", source / "omni/asr/timestamp_text_merger.cc"),
                         ("fixed", target)):
        output = work / name
        compile_driver(source, work, merger, output)
        outputs.append(output)
    subprocess.run([str(outputs[1])], check=True)
    return tuple(outputs)


def replay(driver: Path, cases: list[list[str]], ratio: float,
           states: bool = False) -> list[str]:
    args = [str(driver), str(ratio)] + (["--states"] if states else [])
    result = subprocess.run(args, input="\n===\n".join("\n".join(c) for c in cases)
                            + "\n", text=True, capture_output=True, check=True)
    out = result.stdout.splitlines()
    if len(out) != len(cases):
        raise AssertionError(f"Expected {len(cases)} results, got {len(out)}")
    return out


def evaluate(upstream: Path, fixed: Path, count: int = 400,
             repeated: bool = False) -> list[dict]:
    # Same exact metric, using the bit-vector distance already validated against
    # sim.ops by test_asr_untimed_overlap; Python's DP dominated lane runtime.
    from evaluate_asr_overlap import distance
    rows = []
    for seed in (7, 11, 23):
        rng = random.Random(seed)
        cases = [utter(rng, rng.randint(20, 40)) for _ in range(count)]
        if repeated:
            # Stress adjacent repetitions without altering word timings.
            for words, _ in cases:
                for i in range(1, len(words)):
                    if rng.random() < 0.3:
                        words[i] = (words[i - 1][0], *words[i][1:])
        refs = [" ".join(w for w, _, _ in words) for words, _ in cases]
        for garble in ((False,) if repeated else (False, True)):
            baseline = None
            baseline_edits = None
            for name, driver, ratio in (("upstream@0.4", upstream, 0.4),
                                        ("upstream@0.6", upstream, 0.6),
                                        ("fixed@0.4", fixed, 0.4)):
                rng = random.Random(seed + 1)
                chunks = [windows(w, t, ratio, rng, garble) for w, t in cases]
                out = replay(driver, chunks, ratio)
                exact = [a == b for a, b in zip(out, refs)]
                edits = [distance(ref.split(), hyp.split()) for ref, hyp in zip(refs, out)]
                if baseline is None:
                    baseline = exact
                    baseline_edits = edits
                row = dict(seed=seed, garbled=garble, variant=name, cases=count,
                           exact=sum(exact),
                           fixed=sum(q and not p for p, q in zip(baseline, exact)),
                           regressed=sum(p and not q for p, q in zip(baseline, exact)),
                           windows=sum(map(len, chunks)),
                           edit_distance_better=sum(q < p for p, q in zip(baseline_edits, edits)),
                           edit_distance_worse=sum(q > p for p, q in zip(baseline_edits, edits)))
                rows.append(row)
                if name == "fixed@0.4" and not garble and (row["regressed"] or row["edit_distance_worse"]):
                    raise AssertionError(row)
    return rows


def check_unchanged(upstream: Path, fixed: Path) -> dict:
    rng = random.Random(101)
    timed = []
    singles = []
    for _ in range(400):
        words, total = utter(rng, rng.randint(20, 40))
        singles.append([" ".join(w for w, _, _ in words)])
        # Include end-of-chunk timestamps, as real timestamped decoders do.
        timed.append([" ".join(f"{w}@{int((a-start)*1000)}"
                               for w, a, b in words if a >= start and a < start+5)
                      + " @5000" for start in (0, 3, 6, 9, 12)])
    # Compare every confirmed/unconfirmed event, including final flush.
    for ratio in (0, 0.4, 0.6):
        for chunks in (timed, singles):
            assert replay(upstream, chunks, ratio, True) == replay(fixed, chunks, ratio, True)
    return dict(timed_cases=400, single_window_cases=400, ratios=[0, 0.4, 0.6],
                comparison="every confirmed/unconfirmed output byte")


def check_adversarial(upstream: Path, fixed: Path) -> dict:
    # mono.py timing recipe, extended to both window lengths and corrupt cuts.
    import sim
    saved_window = sim.W
    periodic = []
    try:
        for seconds in (5, 30):
            sim.W = seconds
            for n in (96, 192):
                for phrase in (["no"], ["la"] * 4 + ["hey"], ["one", "two", "three"]):
                    rng = random.Random(n)
                    t, words = .2, []
                    for w in (phrase * (n // len(phrase) + 1))[:n]:
                        d = rng.uniform(.18, .4)
                        words.append((w, t, t + d))
                        t += d + rng.uniform(0, .15)
                    for garble in (False, True):
                        periodic.append(windows(words, t + .3, .4, random.Random(1), garble))
        # Every event must fall back identically; checking final length alone
        # misses a changed pending window that damages the next boundary.
        assert replay(upstream, periodic, .4, True) == replay(fixed, periodic, .4, True)
        # The 192-word counting repro progresses rather than stalling at 24 words.
        for chunks, a, b in zip(periodic, replay(upstream, periodic, .4), replay(fixed, periodic, .4)):
            assert len(b.split()) >= len(a.split())
            if len(chunks) > 4:
                assert len(b.split()) > len(chunks[0].split())
    finally:
        sim.W = saved_window
    phrases = [["of the people by", "by the people for the people"],
               ["we speak of the people by", "by the people for the people today"],
               ["in the house we go by", "by in the house for in the house"]]
    assert replay(upstream, phrases, .4, True) == replay(fixed, phrases, .4, True)
    return dict(periodic_cases=len(periodic), repeated_phrase_cases=len(phrases),
                comparison="every confirmed/unconfirmed byte against upstream@0.4")


def check_confidence_fixtures(fixed: Path) -> dict:
    fixtures = json.loads((REPO / "tests/asr_overlap/confidence_fixtures.json").read_text())
    actual = replay(fixed, [f["chunks"] for f in fixtures], .4, True)
    failures = [f["purpose"] for f, out in zip(fixtures, actual) if f["states"] != out]
    assert not failures, f"Confidence fixtures changed: {failures}"
    return dict(cases=len(fixtures), comparison="frozen confirmed/unconfirmed bytes")


def check_clean_boundaries(upstream: Path, fixed: Path, cache: dict | None = None) -> list[dict]:
    from evaluate_asr_overlap import evaluate as audit_evaluate
    rows = audit_evaluate(upstream, fixed, corpora=(
        "natural", "repeat_phrases", "periodic_bigram"), clean_only=True,
        quiet=True, baseline_cache=cache)
    failures = [row for row in rows if row["regressed"] or row["edit_worse"]]
    assert not failures, f"Clean boundary regression against upstream@0.4: {failures}"
    return rows


def check_mutations(source: Path, work: Path, upstream: Path, fixed: Path,
                    clean_cache: dict, equivalence_count: int = 40) -> dict:
    # Extends audit mut/mut.py. Mutations change the real merger source, then
    # compile and run the same native tests and negative differential controls.
    text = (work / "patched/omni/asr/timestamp_text_merger.cc").read_text()
    mutations = {
        "M4_one_word": ("min_anchor_words = 2", "min_anchor_words = 1"),
        "M5_three_words": ("min_anchor_words = 2", "min_anchor_words = 3"),
        "M7_mixed_timed": ("prev_timestamps_.empty() && curr_timestamps.empty()",
                           "(prev_timestamps_.empty() || curr_timestamps.empty())"),
        "M9_empty_canonical": ("!prev[start].empty() &&", ""),
        "P1_unbounded_anchor": ("best_start >= earliest && !ambiguous", "best_start >= 0"),
        "P2_ignore_confidence": ("best_start >= earliest && !ambiguous", "best_start >= earliest"),
    }
    from asr_overlap_mutations import AUDIT_MUTATIONS
    mutations.update(AUDIT_MUTATIONS)
    variants = {}
    for name, (before, after) in mutations.items():
        # U16's alternative is proven equivalent. Test the reverse change if
        # qualifying that implementation too; do not reject it on syntax alone.
        if name == "U16_ties_prefer_later" and text.count(before) == 0 and text.count(after) == 1:
            before, after = after, before
        assert text.count(before) == 1, name
        variants[name] = text.replace(before, after)
    # Exactly the auditor's combined weakening: retain floor=6, skip-shared,
    # and the earliest bound (with its zero floor); remove eight other guards.
    combined = text
    for name in ("U1_no_offset_consistency", "U2_no_uniqueness", "U3_no_short_tolerant",
                 "U5_no_half_distinct", "U6_no_repeated_bigram_short",
                 "U7_no_repeated_half", "U9_no_trim_shared", "U10_earliest_zero_floor"):
        before, after = AUDIT_MUTATIONS[name]
        combined = combined.replace(before, after)
    variants["COMBO_keep_floor6_skipshared"] = combined
    results = {}
    for name, variant in variants.items():
        mutant = work / (name + ".cc")
        mutant.write_text(variant)
        binary = work / name
        compile_driver(source, work, mutant, binary)
        native = subprocess.run([str(binary)], capture_output=True, text=True)
        negative = False
        try:
            check_adversarial(upstream, binary)
        except AssertionError:
            negative = True
        fixture = False
        try:
            check_confidence_fixtures(binary)
        except AssertionError:
            fixture = True
        # Reuse generated references and upstream distances, never mutant
        # results. Full 400-case seeds/schedules, both 5s and 30s, also in CI.
        clean = None
        if not (native.returncode != 0 or negative or fixture) or name.startswith("COMBO_"):
            clean = False
            try:
                check_clean_boundaries(upstream, binary, clean_cache)
            except AssertionError:
                clean = True
        results[name] = dict(native_killed=native.returncode != 0,
                             negative_killed=negative, fixture_killed=fixture,
                             clean_killed=clean)
        if not (native.returncode != 0 or negative or fixture or clean):
            if name != "U16_ties_prefer_later":
                raise AssertionError(f"Surviving mutation: {name}")
            # Equal-length ties cannot change an accepted candidate: see the
            # proof in docs/asr_untimed_overlap.md. Check every corpus/condition
            # at 40 cases/seed in CI; the full 400-case comparison is recorded
            # in confidence_results.json. This keeps the lane model-free and fast.
            from evaluate_asr_overlap import evaluate as audit_evaluate
            rows = audit_evaluate(fixed, binary, count=equivalence_count, quiet=True, require_equal=True)
            assert all(not any(row[k] for k in (
                "regressed", "fixed", "edit_worse", "edit_better")) for row in rows)
            results[name]["equivalent"] = dict(rows=len(rows),
                utterances=sum(row["cases"] for row in rows), output_differences=0)
        print(f"Mutation {name}: {results[name]}", file=sys.stderr, flush=True)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--mutations", action="store_true")
    parser.add_argument("--equivalence-count", type=int, default=40,
                        help="Cases/seed for the equivalent tie mutation (400 for the full audit)")
    args = parser.parse_args()
    if args.equivalence_count < 1:
        parser.error("--equivalence-count must be positive")
    upstream, fixed = compile_replays(args.source_root.resolve(), args.work_dir.resolve())
    clean_cache = {}
    result = dict(abseil_pkg_versions=dict(zip(ABSL_PACKAGES, subprocess.check_output(
                      ["pkg-config", "--modversion", *ABSL_PACKAGES], text=True).splitlines())),
                  confidence_fixtures=check_confidence_fixtures(fixed),
                  clean_boundaries=check_clean_boundaries(upstream, fixed, clean_cache),
                  unchanged=check_unchanged(upstream, fixed),
                  adversarial=check_adversarial(upstream, fixed),
                  rows=evaluate(upstream, fixed),
                  repeated_rows=evaluate(upstream, fixed, repeated=True))
    if args.mutations:
        result["mutations"] = check_mutations(args.source_root.resolve(), args.work_dir.resolve(),
                                               upstream, fixed, clean_cache,
                                               args.equivalence_count)
    (args.work_dir / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
