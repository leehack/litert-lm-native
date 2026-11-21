#!/usr/bin/env python3
"""Qualify packaged Qwen3 greedy decoding on macOS arm64 under CPU load."""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import tarfile
import tempfile
import time
from collections import Counter
from pathlib import Path

from litert_lm_step_zero_smoke import LIBRARY, LOOKAHEAD, MODELS, Runtime, stream_ok
from validate_artifacts import sha256_file

PROBES = {
    "arithmetic": ("What is 3 + 4? Reply with the equation only.",
                   "3 + 4 = 7", "3 + 3 + 4 = 7"),
    "montreal": ("Reply with exactly: Montréal 👋",
                 "Montréal 👋", "Montréal 👋 Montréal"),
}
WORKERS = 8
MAX_OUTPUT_TOKENS = 32
TOP_P = 0.9
CONTROL_LIBRARY_SHA256 = "3bd6e53c6c42962c1533e82ed5f4dcf608c031bb5c74dcafab3244435adf57a1"
WORKER_CODE = """\
import hashlib
import time

data = bytes(1024 * 1024)
deadline = time.monotonic() + 120
while time.monotonic() < deadline:
    hashlib.sha256(data).digest()
"""


def collect(library: Path, model: Path, backend: str, prompt: str, count: int) -> dict:
    runtime = Runtime(library)
    timings: dict = {}
    with tempfile.TemporaryDirectory(prefix="litert-spatial-staging-") as temp:
        with runtime.engine(model, backend, Path(temp), timings) as engine:
            turns = []
            for _ in range(count):
                with runtime.conversation(engine, MAX_OUTPUT_TOKENS, top_p=TOP_P) as conversation:
                    turns.append(runtime.generate(conversation, prompt, MAX_OUTPUT_TOKENS))
    return {"api_version": runtime.version, "engine_seconds": timings, "turns": turns}


def summarize(backend: str, result: dict, log: str, expected: str, wrong: str,
              count: int, expect_reproduction: bool) -> dict:
    turns = result["turns"]
    outputs = Counter(turn["content"] for turn in turns)
    lookahead = LOOKAHEAD in log
    adapters = [line for line in log.splitlines() if "Selected adapter:" in line]
    validation_errors = log.count("Validation error:")
    failures = []
    if len(turns) != count or not all(stream_ok(turn) for turn in turns):
        failures.append("incomplete or invalid conversation stream")
    if backend == "gpu":
        if not lookahead:
            failures.append("sampler lookahead was not observed")
        if not any("backend=Metal" in line for line in adapters):
            failures.append("Metal placement was not observed")
    elif lookahead or adapters:
        failures.append("GPU execution observed in CPU control")
    if expect_reproduction:
        if not outputs[wrong]:
            failures.append(f"control did not reproduce {wrong!r}")
    else:
        if outputs[expected] != count:
            failures.append(f"{count - outputs[expected]}/{count} outputs differ from {expected!r}")
        if validation_errors:
            failures.append(f"{validation_errors} Dawn validation errors")
    return {
        "exact": outputs[expected],
        "n": count,
        "outputs": dict(outputs),
        "lookahead": lookahead,
        "adapters": adapters,
        "validation_errors": validation_errors,
        "failures": failures,
    }


def run_probe(library: Path, model: Path, backend: str, label: str, count: int,
              expect_reproduction: bool, evidence: Path) -> dict:
    prompt, expected, wrong = PROBES[label]
    output = evidence / f"{label}.json"
    log = evidence / f"{label}.log"
    command = [sys.executable, str(Path(__file__).resolve()), "--worker",
               str(library), str(model), backend, prompt, str(count), str(output)]
    workers = []
    started = time.monotonic()
    try:
        for _ in range(WORKERS):
            workers.append(subprocess.Popen([sys.executable, "-c", WORKER_CODE]))
        time.sleep(0.5)
        with log.open("xb") as stream:
            subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT,
                           check=True, timeout=118,
                           env={**os.environ, "DYLD_LIBRARY_PATH": str(library.parent)})
        if any(worker.poll() is not None for worker in workers):
            raise RuntimeError(f"CPU contention stopped before {label} completed")
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.terminate()
        for worker in workers:
            worker.wait()

    result = json.loads(output.read_text(encoding="utf-8"))
    summary = summarize(backend, result, log.read_text(encoding="utf-8", errors="replace"),
                        expected, wrong, count, expect_reproduction)
    return {**summary, "prompt": prompt, "expected": expected,
            "elapsed_seconds": time.monotonic() - started}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--archive-sha256", required=True)
    parser.add_argument("--library-sha256", required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--backend", choices=("cpu", "gpu"), required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--expect-reproduction", action="store_true")
    args = parser.parse_args()
    if (platform.system(), platform.machine()) != ("Darwin", "arm64"):
        parser.error("this probe qualifies macOS arm64")
    if args.count < 100:
        parser.error("--count must be at least 100")
    if args.expect_reproduction and (args.backend != "gpu" or
                                     args.library_sha256 != CONTROL_LIBRARY_SHA256):
        parser.error("--expect-reproduction requires GPU and the published v0.19.1-6 dylib")

    archive = args.archive.resolve()
    model = args.model.resolve()
    if sha256_file(archive) != args.archive_sha256:
        raise RuntimeError(f"SHA-256 mismatch for {archive}")
    if sha256_file(model) != MODELS["attention"]:
        raise RuntimeError(f"SHA-256 mismatch for {model}")
    evidence = args.evidence.resolve()
    evidence.mkdir(parents=True)
    with tarfile.open(archive, "r:gz") as packaged:
        packaged.extractall(evidence, filter="data")
    library = evidence / "macos/arm64" / LIBRARY
    if sha256_file(library) != args.library_sha256:
        raise RuntimeError(f"SHA-256 mismatch for {library}")

    report = {
        "host": platform.platform(),
        "archive_sha256": args.archive_sha256,
        "library_sha256": args.library_sha256,
        "model_sha256": MODELS["attention"],
        "backend": args.backend,
        "expect_reproduction": args.expect_reproduction,
        "load_workers": WORKERS,
        "sampling": {"temperature": 0.0, "top_k": 1, "top_p": TOP_P, "seed": 1,
                     "enable_thinking": False, "max_output_tokens": MAX_OUTPUT_TOKENS},
        "probes": {},
    }
    for label in PROBES:
        probe = run_probe(library, model, args.backend, label, args.count,
                          args.expect_reproduction, evidence)
        report["probes"][label] = probe
        print(f"{label} {probe['exact']}/{probe['n']} exact, "
              f"{probe['validation_errors']} Dawn validation errors, "
              f"lookahead={probe['lookahead']}, outputs={probe['outputs']}, "
              f"failures={probe['failures']}", flush=True)
    (evidence / "summary.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )
    return int(any(probe["failures"] for probe in report["probes"].values()))


if __name__ == "__main__":
    if sys.argv[1:2] == ["--worker"]:
        _, _, library, model, backend, prompt, count, output = sys.argv
        result = collect(Path(library), Path(model), backend, prompt, int(count))
        Path(output).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    else:
        raise SystemExit(main())
