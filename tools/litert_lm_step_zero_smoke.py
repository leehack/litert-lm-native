#!/usr/bin/env python3
"""Qualify independent Qwen3.5 requests on a packaged Apple LiteRT-LM runtime."""
from __future__ import annotations

import argparse
import ctypes as ct
import json
import os
import platform
import re
import subprocess
import sys
import tarfile
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from litert_lm_c_api import CApi
from litert_lm_chat_smoke import response_text
from validate_artifacts import sha256_file

PROMPT = "List the numbers from one to twenty in English."
MARKER = "CEDAR"
MANAGED_INPUTS = "Using executor-managed decode inputs for WebGPU linear attention on macOS."
LOOKAHEAD = "Sampler will handle decode input tensors."
ARITHMETIC = "What is 3 + 4? Reply with exactly: 3 + 4 = 7"
MODELS = {
    "recurrent": "684d4d34adf7176eb47f6026ff65c33d42584737254e5524a8d1ad62edc21b98",
    "attention": "c5f39b4191926786c3e6668b62af4d6eb15248dfc7a5348252a9b406f33f2108",
}
LIBRARY = "libLiteRtLm.dylib"
EXTRA_CONTEXT = b'{"enable_thinking":false}'
CALLBACK = ct.CFUNCTYPE(None, ct.c_void_p, ct.c_void_p)


class Runtime:
    def __init__(self, library: Path) -> None:
        self.api = CApi(library)
        self.library = self.api.library
        self.version = self.api.api_version()
        if self.version[:2] != (1, 0):
            raise RuntimeError(f"Expected C API 1.0, found {self.version}")
        self.api.set_min_log_level(0)
        for name, types in {
            "engine_settings_set_max_num_tokens": [ct.c_void_p, ct.c_int],
            "session_config_set_max_output_tokens": [ct.c_void_p, ct.c_int],
            "conversation_config_set_extra_context": [ct.c_void_p, ct.c_char_p],
            "thinking_config_set_enable_thinking": [ct.c_void_p, ct.c_bool],
            "conversation_config_set_thinking_config": [ct.c_void_p, ct.c_void_p],
            "conversation_optional_args_set_thinking_config": [ct.c_void_p, ct.c_void_p],
            "conversation_send_message_stream": [
                ct.c_void_p, ct.c_char_p, ct.c_char_p, ct.c_void_p, CALLBACK, ct.c_void_p,
            ],
            "conversation_wait_until_done": [ct.c_void_p],
            "stream_chunk_get_text": [ct.c_void_p, ct.POINTER(ct.c_char_p)],
            "stream_chunk_get_error": [ct.c_void_p, ct.POINTER(ct.c_char_p)],
            "stream_chunk_is_final": [ct.c_void_p, ct.POINTER(ct.c_bool)],
        }.items():
            self.api._bind(f"litert_lm_{name}", ct.c_int, types)
        self.api._bind("litert_lm_thinking_config_delete", None, [ct.c_void_p])

    def call(self, name: str, *args) -> None:
        full_name = f"litert_lm_{name}"
        self.api._check(getattr(self.library, full_name)(*args), full_name)

    @contextmanager
    def owned(self, kind: str, handle: int):
        try:
            yield handle
        finally:
            getattr(self.library, f"litert_lm_{kind}_delete")(handle)

    @contextmanager
    def engine(self, model: Path, backend: str, cache: Path, timings: dict):
        started = time.monotonic()
        with self.owned("engine_settings", self.api.engine_settings_create(str(model), backend)) as settings:
            self.api.engine_settings_set_cache_dir(settings, str(cache))
            self.call("engine_settings_set_max_num_tokens", settings, 1024)
            if backend == "cpu":
                self.api.engine_settings_set_num_threads(settings, 2)
            engine = self.api.engine_create(settings)
        timings["load_seconds"] = time.monotonic() - started
        with self.owned("engine", engine):
            try:
                yield engine
            finally:
                started = time.monotonic()
        timings["delete_seconds"] = time.monotonic() - started

    @contextmanager
    def thinking_disabled(self):
        with self.owned("thinking_config", self.api._create("litert_lm_thinking_config_create")) as thinking:
            self.call("thinking_config_set_enable_thinking", thinking, False)
            yield thinking

    @contextmanager
    def conversation(self, engine: int, max_tokens: int):
        with (self.owned("session_config", self.api.session_config_create()) as session,
              self.owned("sampler_params", self.api.sampler_params_create(2, top_k=1, top_p=1.0, temperature=0.0, seed=1)) as sampler,
              self.owned("conversation_config", self.api.conversation_config_create()) as config,
              self.thinking_disabled() as thinking):
            self.call("session_config_set_max_output_tokens", session, max_tokens)
            self.call("session_config_set_sampler_params", session, sampler)
            self.call("conversation_config_set_session_config", config, session)
            self.call("conversation_config_set_extra_context", config, EXTRA_CONTEXT)
            self.call("conversation_config_set_thinking_config", config, thinking)
            conversation = self.api.conversation_create(engine, config)
        with self.owned("conversation", conversation):
            yield conversation

    def generate(self, conversation: int, prompt: str, max_tokens: int, *,
                 cancel: bool = False) -> dict:
        chunks = []
        errors = []
        callback_failures = []
        first_content = None
        cancellation_requested = False
        terminal_count = 0

        @CALLBACK
        def callback(_data, chunk):
            nonlocal first_content, cancellation_requested, terminal_count
            try:
                text, error, terminal = ct.c_char_p(), ct.c_char_p(), ct.c_bool()
                self.call("stream_chunk_get_text", chunk, ct.byref(text))
                self.call("stream_chunk_get_error", chunk, ct.byref(error))
                self.call("stream_chunk_is_final", chunk, ct.byref(terminal))
                if error.value:
                    errors.append(error.value.decode())
                content = response_text(text.value.decode()) if text.value else ""
                if content:
                    chunks.append(content)
                    if first_content is None:
                        first_content = time.monotonic() - started
                        if cancel and not terminal.value:
                            self.api.conversation_cancel_process(conversation)
                            cancellation_requested = True
                terminal_count += int(terminal.value)
            except Exception as exc:
                callback_failures.append(str(exc))

        message = json.dumps({"role": "user", "content": [{"type": "text", "text": prompt}]}).encode()
        with (self.owned("conversation_optional_args",
                         self.api.conversation_optional_args_create(max_tokens)) as options,
              self.thinking_disabled() as thinking):
            self.call("conversation_optional_args_set_thinking_config", options, thinking)
            started = time.monotonic()
            self.call("conversation_send_message_stream", conversation, message,
                      EXTRA_CONTEXT, options, callback, None)
            self.call("conversation_wait_until_done", conversation)
        return {
            "content": "".join(chunks),
            "stream_errors": errors,
            "callback_errors": callback_failures,
            "cancel_requested": cancellation_requested,
            "terminal_count": terminal_count,
            "first_content_seconds": first_content,
            "drained_seconds": time.monotonic() - started,
        }

    def independent(self, engine: int, prompt: str, *, cancel: bool = False) -> dict:
        max_tokens = 128 if cancel else 32
        with self.conversation(engine, max_tokens) as conversation:
            result = self.generate(conversation, prompt, max_tokens, cancel=cancel)
            drained = time.monotonic()
        return {**result, "conversation_delete_seconds": time.monotonic() - drained}


def collect(library: Path, model: Path, backend: str, mode: str, prompt: str) -> dict:
    runtime = Runtime(library)
    timings = {}
    with tempfile.TemporaryDirectory(prefix="w672-cache-") as tmp:
        cache = Path(tmp)
        with runtime.engine(model, backend, cache, timings.setdefault("initial", {})) as engine:
            independent = [runtime.independent(engine, prompt)
                           for _ in range(5 if mode == "repeated" else 1)]
            controls = {}
            if mode == "repeated" and prompt == PROMPT:
                controls["marker"] = runtime.independent(
                    engine, f"Reply with exactly the word {MARKER}.")
                controls["after_marker"] = runtime.independent(engine, prompt)
        result = {"independent": independent, "api_version": runtime.version, **controls}
        if mode == "repeated":
            with runtime.engine(model, backend, cache, timings.setdefault("reload", {})) as engine:
                reloaded = runtime.independent(engine, prompt)
                with runtime.conversation(engine, 32) as conversation:
                    reused = [runtime.generate(conversation, prompt, 32),
                              runtime.generate(conversation, "What did I just ask you to list?", 32)]
                cancelled = runtime.independent(engine, prompt, cancel=True)
                after_cancel = runtime.independent(engine, prompt)
            result.update(reloaded=reloaded, reused=reused, cancelled=cancelled, after_cancel=after_cancel)
    return {**result, "engine_seconds": timings, "private_cache_removed": not cache.exists()}


def run_process(library: Path, model: Path, backend: str, mode: str,
                prompt: str, evidence: Path, label: str) -> dict:
    output = evidence / f"w672-{label}.json"
    log = evidence / f"w672-{label}.log"
    if output.exists():
        raise FileExistsError(output)
    command = [sys.executable, str(Path(__file__).resolve()), "--worker", str(library),
               str(model), backend, mode, prompt, str(output)]
    with log.open("xb") as stream:
        subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=True,
                       timeout=300, env={**os.environ, "DYLD_LIBRARY_PATH": str(library.parent)})
    result = json.loads(output.read_text())
    records = log.read_text(errors="replace").splitlines()
    result["placement_log"] = [
        line for line in records if re.search(r"adapter|delegate|backend", line, re.I)
    ]
    result["sampler_log"] = [
        line for line in records
        if any(marker in line for marker in (MANAGED_INPUTS, LOOKAHEAD, "GPU sampler unavailable"))
    ]
    return result


def stream_ok(turn: dict) -> bool:
    return (turn["terminal_count"] == 1 and not turn["stream_errors"]
            and not turn["callback_errors"] and bool(turn["content"])
            and turn["first_content_seconds"] is not None)


def answers_counting_prompt(content: str) -> bool:
    if PROMPT.casefold() in content.casefold():
        return False
    for line in content.splitlines():
        if re.search(r"^\s*(?:1[.,)]\s*(?:\d+\s*)?2[.,)]\s*3|one[, ]+two[, ]+three)\b", line, re.I):
            return True
    return False


def grade(backend: str, family: str, repeated: dict, fresh: list[dict], *,
          require_executor_managed_inputs: bool = False) -> dict:
    independent = repeated["independent"] + [
        repeated["after_marker"], repeated["reloaded"], repeated["after_cancel"],
    ]
    reference_turns = [result["independent"][0] for result in fresh]
    references = {turn["content"] for turn in reference_turns}
    turns = independent + reference_turns
    failures = []
    if len(repeated["independent"]) != 5 or len(fresh) != 2 or not all(map(stream_ok, turns)):
        failures.append("incomplete independent or fresh stream")
    if not all(result["private_cache_removed"] for result in [repeated, *fresh]):
        failures.append("private cache cleanup failed")
    terminal = repeated["cancelled"]
    if (not terminal["cancel_requested"] or terminal["terminal_count"] != 1
            or terminal["callback_errors"]
            or not any("cancel" in error.lower() for error in terminal["stream_errors"])):
        failures.append("cancellation did not reach a cancelled terminal callback and drain")
    if not all(map(stream_ok, repeated["reused"])):
        failures.append("reuse control did not complete")
    if not stream_ok(repeated["marker"]) or repeated["marker"]["content"].strip() != MARKER:
        failures.append("unrelated request did not return the marker")
    if backend == "gpu":
        for process in [repeated, *fresh]:
            placement = "\n".join(process["placement_log"])
            if not (re.search(r"(?im)^(?=.*metal)(?=.*adapter)", placement)
                    and re.search(r"(?im)^(?=.*delegate)(?=.*kernel)", placement)):
                failures.append("Metal adapter and delegate kernels not established")
            if require_executor_managed_inputs:
                sampler_log = "\n".join(process["sampler_log"])
                expected, prohibited = ((MANAGED_INPUTS, LOOKAHEAD) if family == "recurrent"
                                        else (LOOKAHEAD, MANAGED_INPUTS))
                if (expected not in sampler_log or prohibited in sampler_log
                        or "GPU sampler unavailable" in sampler_log):
                    failures.append(f"GPU sampler input handling not established for {family}")
    if any(PROMPT.casefold() in turn["content"].casefold() for turn in turns):
        failures.append("independent request echoed the input")
    outside_fresh = [index for index, item in enumerate(independent, 1)
                     if item["content"] not in references]
    if family == "recurrent":
        if not all(answers_counting_prompt(turn["content"]) for turn in turns):
            failures.append("independent or fresh answer failed counting semantics")
        if len(references) != 1 or outside_fresh:
            failures.append("Qwen3.5 content differs from its fresh reference")
    return {"failures": failures, "fresh_variants": sorted(references),
            "independent_outside_fresh": outside_fresh}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--archive-sha256", required=True)
    parser.add_argument("--library-sha256", required=True)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--attention-model", required=True, type=Path)
    parser.add_argument("--backend", required=True, choices=("cpu", "gpu"))
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--require-executor-managed-inputs", action="store_true")
    args = parser.parse_args()
    if (platform.system(), platform.machine()) != ("Darwin", "arm64"):
        parser.error("this oracle qualifies macOS arm64")
    args.evidence.mkdir(parents=True, exist_ok=False)
    archive = args.archive.resolve()
    models = {"recurrent": args.model.resolve(), "attention": args.attention_model.resolve()}
    bindings = {archive: args.archive_sha256, **{path: MODELS[name] for name, path in models.items()}}
    for path, expected in bindings.items():
        if sha256_file(path) != expected:
            raise RuntimeError(f"SHA-256 mismatch for {path}")
    with tarfile.open(archive, "r:gz") as packaged:
        packaged.extractall(args.evidence, filter="data")
    library = args.evidence.resolve() / "macos/arm64" / LIBRARY
    if sha256_file(library) != args.library_sha256:
        raise RuntimeError(f"SHA-256 mismatch for {library}")
    report = {"host": platform.platform(), "backend": args.backend, "prompt": PROMPT,
              "archive": str(archive), "archive_sha256": args.archive_sha256,
              "library_sha256": args.library_sha256, "models": MODELS, "lanes": {}}
    for family, model in models.items():
        def run(mode: str, label: str, prompt: str = PROMPT) -> dict:
            return run_process(library, model, args.backend, mode, prompt, args.evidence,
                               f"{family}-{label}")

        fresh = [run("fresh", f"fresh-{index}") for index in range(1, 3)]
        repeated = run("repeated", "repeated")
        grade_result = grade(args.backend, family, repeated, fresh,
                             require_executor_managed_inputs=args.require_executor_managed_inputs)
        lane = {"repeated": repeated, "fresh": fresh, **grade_result}
        if family == "attention":
            arithmetic = run("repeated", "arithmetic", ARITHMETIC)
            turns = arithmetic["independent"] + [arithmetic["reloaded"]]
            lane["arithmetic"] = arithmetic
            if not all(stream_ok(turn) and turn["content"].strip() == "3 + 4 = 7" for turn in turns):
                lane["failures"].append("attention-only arithmetic control failed")
            if args.backend == "gpu" and args.require_executor_managed_inputs:
                if not any(LOOKAHEAD in line for line in arithmetic["sampler_log"]):
                    lane["failures"].append("attention-only arithmetic GPU sampler lookahead not established")
        report["lanes"][family] = lane
    (args.evidence / "w672-oracle.json").write_text(json.dumps(report, indent=2) + "\n")
    for family, lane in report["lanes"].items():
        print(f"{family}: {lane['failures'] or 'PASS'}", flush=True)
    return int(any(lane["failures"] for lane in report["lanes"].values()))


if __name__ == "__main__":
    if sys.argv[1:2] == ["--worker"]:
        _, _, library, model, backend, mode, prompt, output = sys.argv
        result = collect(Path(library), Path(model), backend, mode, prompt)
        Path(output).write_text(json.dumps(result, indent=2) + "\n")
    else:
        raise SystemExit(main())
