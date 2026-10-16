#!/usr/bin/env python3
"""Compile real upstream merger stages and evaluate without fetching any assets."""
from __future__ import annotations

import argparse
import json
import random
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from build_upstream_runtime import patch_asr_untimed_overlap

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests/asr_overlap"))
from sim import ops, utter, windows  # noqa: E402


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
    flags = shlex.split(subprocess.check_output([
        "pkg-config", "--cflags", "--libs", "absl_status", "absl_statusor",
        "absl_status_macros", "absl_strings", "absl_synchronization",
        "absl_log_internal_message", "absl_vlog_config_internal"], text=True))
    compiler = shutil.which("clang++") or shutil.which("c++")
    if not compiler:
        raise RuntimeError("A C++17 compiler is required")
    outputs = []
    for name, merger in (("upstream", source / "omni/asr/timestamp_text_merger.cc"),
                         ("fixed", target)):
        output = work / name
        subprocess.run([compiler, "-std=c++17", "-O2", "-Wall", "-Wextra",
                        "-I", str(source), "-I", str(work),
                        str(REPO / "native/bridge/litert_lm_asr_merger_test.cc"),
                        str(merger), str(source / "omni/asr/levenshtein_align.cc"),
                        *flags, "-o", str(output)], check=True)
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
                edits = [sum(ops(ref.split(), hyp.split())) for ref, hyp in zip(refs, out)]
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args()
    upstream, fixed = compile_replays(args.source_root.resolve(), args.work_dir.resolve())
    result = dict(unchanged=check_unchanged(upstream, fixed),
                  rows=evaluate(upstream, fixed),
                  repeated_rows=evaluate(upstream, fixed, repeated=True))
    (args.work_dir / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
