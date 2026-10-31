#!/usr/bin/env python3
"""Opt-in real-model check of the stream finish-reason bridge ABI (#78).

Each scenario streams one conversation turn through stream_proxy_* and checks
the reason reported after the final callback. With --abi-only it only checks
that a built runtime reports the finish-reason ABI version its tag requires.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from litert_lm_c_api import CApi
from stream_finish_reason_patch import require_finish_reason_patch_decision

FINISH_REASONS = {
    0: "unknown",
    1: "stop",
    2: "length",
    3: "context_exhausted",
    4: "cancelled",
    5: "error",
}
COUNT_PROMPT = "Count from 1 to 20, separated by commas. Output only the numbers."
STORY_PROMPT = "Write a very long story about a lighthouse keeper."
TURN_TIMEOUT_SECONDS = 600

DartCallback = ctypes.CFUNCTYPE(
    None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool, ctypes.c_void_p
)


@dataclass(frozen=True)
class Scenario:
    name: str
    prompt: str
    max_output_tokens: int
    expected: str
    cancel_after_first_chunk: bool = False


SCENARIOS = (
    Scenario("output budget", COUNT_PROMPT, 3, "length"),
    Scenario("natural end", COUNT_PROMPT, 1024, "stop"),
    Scenario("cancelled", STORY_PROMPT, 4096, "cancelled",
             cancel_after_first_chunk=True),
)


def bind(library_path: Path) -> CApi:
    api = CApi(library_path)
    library = api.library
    signatures = {
        "stream_proxy_finish_reason_abi_version": (ctypes.c_int32, []),
        "stream_proxy_get_finish_reason": (ctypes.c_int32, [ctypes.c_void_p]),
        "stream_proxy_create": (
            ctypes.c_void_p,
            [DartCallback, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)],
        ),
        "stream_proxy_delete": (None, [ctypes.c_void_p]),
        "stream_proxy_free_string": (None, [ctypes.c_void_p]),
        "litert_lm_conversation_send_message_stream": (
            ctypes.c_int,
            [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p,
             ctypes.c_void_p, ctypes.c_void_p],
        ),
    }
    for name, (restype, argtypes) in signatures.items():
        function = getattr(library, name)
        function.restype = restype
        function.argtypes = argtypes
    return api


def message_json(prompt: str) -> bytes:
    return json.dumps({
        "role": "user",
        "content": [{"type": "text", "text": prompt}],
    }).encode("utf-8")


def run_scenario(
    api: CApi, engine: int, scenario: Scenario
) -> dict[str, object]:
    library = api.library
    first_chunk = threading.Event()
    finished = threading.Event()
    chunks: list[str] = []
    errors: list[str] = []

    def take(pointer: int | None) -> str | None:
        if not pointer:
            return None
        value = ctypes.string_at(pointer).decode("utf-8", errors="replace")
        library.stream_proxy_free_string(pointer)
        return value

    def on_chunk(_data, chunk, is_final, error) -> None:
        text = take(chunk)
        message = take(error)
        if text is not None:
            chunks.append(text)
            first_chunk.set()
        if message is not None:
            errors.append(message)
        if is_final:
            finished.set()

    callback = DartCallback(on_chunk)
    config = api.conversation_config_create()
    try:
        conversation = api.conversation_create(engine, config)
    finally:
        library.litert_lm_conversation_config_delete(config)
    upstream_callback = ctypes.c_void_p()
    proxy = library.stream_proxy_create(callback, None,
                                        ctypes.byref(upstream_callback))
    optional_args = api.conversation_optional_args_create(scenario.max_output_tokens)
    try:
        if not proxy or not upstream_callback.value:
            raise RuntimeError("stream_proxy_create failed")
        status = library.litert_lm_conversation_send_message_stream(
            conversation, message_json(scenario.prompt), None, optional_args,
            upstream_callback, proxy)
        if status != 0:
            raise RuntimeError(f"send_message_stream returned {status}")
        if scenario.cancel_after_first_chunk:
            if not first_chunk.wait(TURN_TIMEOUT_SECONDS):
                raise RuntimeError(f"{scenario.name}: no chunk to cancel after")
            api.conversation_cancel_process(conversation)
        if not finished.wait(TURN_TIMEOUT_SECONDS):
            raise RuntimeError(f"{scenario.name}: no final callback")
        reason = library.stream_proxy_get_finish_reason(proxy)
    finally:
        library.litert_lm_conversation_optional_args_delete(optional_args)
        library.litert_lm_conversation_delete(conversation)
        if proxy:
            library.stream_proxy_delete(proxy)
    return {
        "scenario": scenario.name,
        "maxOutputTokens": scenario.max_output_tokens,
        "expected": scenario.expected,
        "finishReason": FINISH_REASONS.get(reason, f"invalid({reason})"),
        "chunks": len(chunks),
        "errors": errors,
    }


def mismatches(results: list[dict[str, object]]) -> list[str]:
    return [
        f"{result['scenario']}: expected {result['expected']}, "
        f"got {result['finishReason']}"
        for result in results
        if result["finishReason"] != result["expected"]
    ]


def expected_abi_version(upstream_tag: str) -> int:
    return 1 if require_finish_reason_patch_decision(upstream_tag) else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--backend", default="cpu")
    parser.add_argument("--abi-only", action="store_true")
    parser.add_argument("--upstream-tag",
                        help="Compatibility tag whose ABI version --abi-only expects.")
    args = parser.parse_args()
    if args.abi_only != bool(args.upstream_tag):
        parser.error("--abi-only and --upstream-tag go together")
    if not args.abi_only and args.model is None:
        parser.error("--model is required unless --abi-only is set")

    try:
        api = bind(args.library.resolve())
        library = api.library
    except AttributeError as error:
        print(f"{error}; this runtime does not report finish reasons",
              file=sys.stderr)
        return 1
    version = library.stream_proxy_finish_reason_abi_version()
    if args.abi_only:
        expected = expected_abi_version(args.upstream_tag)
        print(f"stream_proxy_finish_reason_abi_version() = {version}; "
              f"{args.upstream_tag} expects {expected}")
        return 0 if version == expected else 1
    if version != 1:
        print(f"stream_proxy_finish_reason_abi_version() = {version}; "
              "this runtime does not report finish reasons", file=sys.stderr)
        return 1

    # Windows keeps the XNNPACK weight cache open until the process exits.
    with tempfile.TemporaryDirectory(prefix="litert-lm-finish-reason-",
                                     ignore_cleanup_errors=True) as cache:
        settings = api.engine_settings_create(str(args.model.resolve()), args.backend)
        engine = None
        try:
            api.engine_settings_set_cache_dir(settings, cache)
            engine = api.engine_create(settings)
            results = [run_scenario(api, engine, scenario)
                       for scenario in SCENARIOS]
        finally:
            if engine:
                library.litert_lm_engine_delete(engine)
            library.litert_lm_engine_settings_delete(settings)

    print(json.dumps(results, indent=2))
    failures = mismatches(results)
    for failure in failures:
        print(failure, file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
