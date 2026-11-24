#!/usr/bin/env python3
"""Check the owner text-LoRA probe and the real CPU session rejection."""
from __future__ import annotations

import argparse
import ctypes
import sys
import tempfile
from pathlib import Path

from litert_lm_c_api import CApi

SESSION_REJECTION = (
    "litert_lm_engine_create_session failed (3): "
    "INVALID_ARGUMENT: Lora is not supported."
)


def probe(library) -> int:
    try:
        version = library.litert_lm_native_text_lora_abi_version
        supports = library.litert_lm_native_supports_text_lora
    except AttributeError as error:
        raise RuntimeError(f"runtime lacks text LoRA probe export: {error}") from error
    for function in (version, supports):
        function.restype = ctypes.c_int32
        function.argtypes = []
    abi = version()
    if abi != 1:
        raise RuntimeError(f"text LoRA probe ABI = {abi}; expected 1")
    return supports()


def verify_refusal(api: CApi, engine: int, adapter: Path, supports: int) -> None:
    library = api.library
    config = api.session_config_create()
    try:
        control = api.engine_create_session(engine, config)
        library.litert_lm_session_delete(control)

        api.session_config_set_lora_path(config, adapter)
        print("litert_lm_session_config_set_lora_path() = 0", flush=True)
        try:
            session = api.engine_create_session(engine, config)
        except RuntimeError as error:
            if str(error) != SESSION_REJECTION:
                raise
            print(error, flush=True)
        else:
            library.litert_lm_session_delete(session)
            raise RuntimeError("text LoRA session unexpectedly created")
        if supports != 0:
            raise RuntimeError(f"text LoRA support probe = {supports}; "
                               f"expected 0 after session rejection")
    finally:
        library.litert_lm_session_config_delete(config)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--model", type=Path)
    mode.add_argument("--abi-only", action="store_true")
    args = parser.parse_args()

    try:
        api = CApi(args.library.resolve())
        supports = probe(api.library)
        print(f"text LoRA probe ABI = 1; supports = {supports}", flush=True)
        if args.abi_only:
            if supports != 0:
                raise RuntimeError(f"text LoRA support probe = {supports}; expected 0")
            return 0

        # Windows keeps the XNNPACK weight cache open until process exit.
        with tempfile.TemporaryDirectory(prefix="litert-lm-text-lora-",
                                         ignore_cleanup_errors=True) as directory:
            adapter = Path(directory) / "adapter.tflite"
            adapter.touch()
            settings = api.engine_settings_create(str(args.model.resolve()), "cpu")
            try:
                api.engine_settings_set_num_threads(settings, 2)
                api.engine_settings_set_cache_dir(settings, directory)
                engine = api.engine_create(settings)
                try:
                    verify_refusal(api, engine, adapter, supports)
                finally:
                    api.library.litert_lm_engine_delete(engine)
            finally:
                api.library.litert_lm_engine_settings_delete(settings)
    except (AttributeError, OSError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
