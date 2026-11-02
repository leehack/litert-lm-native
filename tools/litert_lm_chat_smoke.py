#!/usr/bin/env python3
"""Real-model chat check of a candidate runtime through the public C API."""
from __future__ import annotations

import argparse
import ctypes
import json
import sys
import tempfile
from pathlib import Path

from litert_lm_c_api import CApi

PROMPT = "What is 2+2? Answer only with the number."
_SAMPLER_TOP_P = 2


def response_text(raw: str) -> str:
    return "".join(
        part.get("text", "")
        for part in json.loads(raw).get("content", [])
        if isinstance(part, dict)
    )


def answer_after_thinking(text: str) -> str:
    return text.rsplit("</think>", 1)[-1].strip()


def generate(api: CApi, engine: int, prompt: str, max_output_tokens: int) -> str:
    library = api.library
    send = library.litert_lm_conversation_send_message
    send.restype = ctypes.c_int
    send.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p,
                     ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    get_string = library.litert_lm_json_response_get_string
    get_string.restype = ctypes.c_int
    get_string.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_char_p)]
    library.litert_lm_json_response_delete.restype = None
    library.litert_lm_json_response_delete.argtypes = [ctypes.c_void_p]

    sampler = api.sampler_params_create(_SAMPLER_TOP_P, top_k=1, top_p=0.95)
    config = api.conversation_config_create(sampler)
    library.litert_lm_sampler_params_delete(sampler)
    try:
        conversation = api.conversation_create(engine, config)
    finally:
        library.litert_lm_conversation_config_delete(config)
    optional_args = api.conversation_optional_args_create(max_output_tokens)
    response = ctypes.c_void_p()
    try:
        message = json.dumps(
            {"role": "user", "content": [{"type": "text", "text": prompt}]})
        status = send(conversation, message.encode(), None, optional_args,
                      ctypes.byref(response))
        api._check(status, "litert_lm_conversation_send_message")
        raw = ctypes.c_char_p()
        api._check(get_string(response, ctypes.byref(raw)),
                   "litert_lm_json_response_get_string")
        return response_text(raw.value.decode("utf-8", errors="replace"))
    finally:
        if response.value:
            library.litert_lm_json_response_delete(response)
        library.litert_lm_conversation_optional_args_delete(optional_args)
        library.litert_lm_conversation_delete(conversation)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--backend", default="cpu")
    parser.add_argument("--prompt", default=PROMPT)
    parser.add_argument("--expect", default="4")
    parser.add_argument("--max-output-tokens", type=int, default=1024)
    args = parser.parse_args()

    api = CApi(args.library.resolve())
    library = api.library
    print(f"C API version {api.api_version()}", flush=True)
    with tempfile.TemporaryDirectory(prefix="litert-lm-chat-",
                                     ignore_cleanup_errors=True) as cache:
        settings = api.engine_settings_create(str(args.model.resolve()), args.backend)
        engine = None
        try:
            api.engine_settings_set_cache_dir(settings, cache)
            engine = api.engine_create(settings)
            text = generate(api, engine, args.prompt, args.max_output_tokens)
        finally:
            if engine:
                library.litert_lm_engine_delete(engine)
            library.litert_lm_engine_settings_delete(settings)
    answer = answer_after_thinking(text)
    print(json.dumps({"answer": answer}), flush=True)
    if args.expect not in answer:
        print(f"Expected {args.expect!r} in {answer!r}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
