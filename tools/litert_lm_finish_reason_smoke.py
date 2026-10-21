#!/usr/bin/env python3
"""Opt-in real-model check of the stream finish-reason bridge ABI (#78).

Each scenario streams one conversation turn through stream_proxy_* and checks
the reason reported after the final callback.
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

_DLL_DIRECTORY_HANDLES: list[object] = []

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


def bind(library_path: Path) -> ctypes.CDLL:
    if os.name == "nt":
        _DLL_DIRECTORY_HANDLES.append(
            os.add_dll_directory(str(library_path.parent))
        )
    library = ctypes.CDLL(str(library_path))
    signatures = {
        "stream_proxy_finish_reason_abi_version": (ctypes.c_int32, []),
        "stream_proxy_get_finish_reason": (ctypes.c_int32, [ctypes.c_void_p]),
        "stream_proxy_create": (
            ctypes.c_void_p,
            [DartCallback, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)],
        ),
        "stream_proxy_delete": (None, [ctypes.c_void_p]),
        "stream_proxy_free_string": (None, [ctypes.c_void_p]),
        "litert_lm_engine_settings_create": (
            ctypes.c_void_p,
            [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p],
        ),
        "litert_lm_engine_settings_set_cache_dir": (
            None, [ctypes.c_void_p, ctypes.c_char_p]
        ),
        "litert_lm_engine_settings_delete": (None, [ctypes.c_void_p]),
        "litert_lm_engine_create": (ctypes.c_void_p, [ctypes.c_void_p]),
        "litert_lm_engine_delete": (None, [ctypes.c_void_p]),
        "litert_lm_conversation_config_create": (ctypes.c_void_p, []),
        "litert_lm_conversation_config_delete": (None, [ctypes.c_void_p]),
        "litert_lm_conversation_create": (
            ctypes.c_void_p, [ctypes.c_void_p, ctypes.c_void_p]
        ),
        "litert_lm_conversation_delete": (None, [ctypes.c_void_p]),
        "litert_lm_conversation_cancel_process": (None, [ctypes.c_void_p]),
        "litert_lm_conversation_optional_args_create": (ctypes.c_void_p, []),
        "litert_lm_conversation_optional_args_delete": (None, [ctypes.c_void_p]),
        "litert_lm_conversation_optional_args_set_max_output_tokens": (
            None, [ctypes.c_void_p, ctypes.c_int]
        ),
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
    return library


def message_json(prompt: str) -> bytes:
    return json.dumps({
        "role": "user",
        "content": [{"type": "text", "text": prompt}],
    }).encode("utf-8")


def run_scenario(
    library: ctypes.CDLL, engine: int, scenario: Scenario
) -> dict[str, object]:
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
    config = library.litert_lm_conversation_config_create()
    conversation = library.litert_lm_conversation_create(engine, config)
    library.litert_lm_conversation_config_delete(config)
    if not conversation:
        raise RuntimeError("litert_lm_conversation_create returned null")
    upstream_callback = ctypes.c_void_p()
    proxy = library.stream_proxy_create(callback, None,
                                        ctypes.byref(upstream_callback))
    optional_args = library.litert_lm_conversation_optional_args_create()
    try:
        if not proxy or not upstream_callback.value:
            raise RuntimeError("stream_proxy_create failed")
        library.litert_lm_conversation_optional_args_set_max_output_tokens(
            optional_args, scenario.max_output_tokens)
        status = library.litert_lm_conversation_send_message_stream(
            conversation, message_json(scenario.prompt), None, optional_args,
            upstream_callback, proxy)
        if status != 0:
            raise RuntimeError(f"send_message_stream returned {status}")
        if scenario.cancel_after_first_chunk:
            if not first_chunk.wait(TURN_TIMEOUT_SECONDS):
                raise RuntimeError(f"{scenario.name}: no chunk to cancel after")
            library.litert_lm_conversation_cancel_process(conversation)
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--backend", default="cpu")
    args = parser.parse_args()

    try:
        library = bind(args.library.resolve())
    except AttributeError as error:
        print(f"{error}; this runtime does not report finish reasons",
              file=sys.stderr)
        return 1
    version = library.stream_proxy_finish_reason_abi_version()
    if version != 1:
        print(f"stream_proxy_finish_reason_abi_version() = {version}; "
              "this runtime does not report finish reasons", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="litert-lm-finish-reason-") as cache:
        settings = library.litert_lm_engine_settings_create(
            str(args.model.resolve()).encode(), args.backend.encode(), None, None)
        if not settings:
            raise RuntimeError("litert_lm_engine_settings_create returned null")
        library.litert_lm_engine_settings_set_cache_dir(settings, cache.encode())
        engine = library.litert_lm_engine_create(settings)
        try:
            if not engine:
                raise RuntimeError("litert_lm_engine_create returned null")
            results = [run_scenario(library, engine, scenario)
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
