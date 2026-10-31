"""ctypes access to the LiteRT-LM C API across its two calling conventions.

C API 1.0 (LiteRT-LM v0.19) returns a status code and writes results through
trailing out parameters. Older runtimes return results directly. Tools call the
wrappers here so one tool can qualify both, for example when comparing a
candidate against a published baseline.
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path

_DLL_DIRECTORY_HANDLES: list[object] = []
_VOID_P = ctypes.c_void_p
_STR = ctypes.c_char_p


class CApi:
    def __init__(self, library_path: Path) -> None:
        if os.name == "nt":
            _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(str(library_path.parent)))
        self.library = ctypes.CDLL(str(library_path))
        self.is_v1 = hasattr(self.library, "litert_lm_get_api_version")
        self._bind_lifetimes()

    def _bind(self, name: str, restype, argtypes) -> None:
        function = getattr(self.library, name)
        function.restype = restype
        function.argtypes = argtypes

    def _bind_lifetimes(self) -> None:
        for name in (
            "litert_lm_engine_settings_delete",
            "litert_lm_engine_delete",
            "litert_lm_session_config_delete",
            "litert_lm_session_delete",
            "litert_lm_conversation_config_delete",
            "litert_lm_conversation_delete",
            "litert_lm_conversation_optional_args_delete",
            "litert_lm_sampler_params_delete",
        ):
            self._bind(name, None, [_VOID_P])
        status = ctypes.c_int if self.is_v1 else None
        self._setter_restype = status
        for name, value_type in (
            ("litert_lm_set_min_log_level", None),
            ("litert_lm_engine_settings_set_num_threads", ctypes.c_int),
            ("litert_lm_engine_settings_set_cache_dir", _STR),
            ("litert_lm_conversation_optional_args_set_max_output_tokens", ctypes.c_int),
            ("litert_lm_sampler_params_set_top_k", ctypes.c_int),
            ("litert_lm_sampler_params_set_top_p", ctypes.c_float),
            ("litert_lm_sampler_params_set_temperature", ctypes.c_float),
            ("litert_lm_sampler_params_set_seed", ctypes.c_int),
        ):
            args = [ctypes.c_int] if value_type is None else [_VOID_P, value_type]
            self._bind(name, status, args)
        self._bind("litert_lm_session_config_set_sampler_params", status, [_VOID_P, _VOID_P])
        self._bind("litert_lm_conversation_config_set_session_config", status, [_VOID_P, _VOID_P])
        if self.is_v1:
            self._bind("litert_lm_get_api_version", ctypes.c_int,
                       [ctypes.POINTER(ctypes.c_int)] * 3)
            self._bind("litert_lm_get_last_error_message", _STR, [])

    def _check(self, status: int | None, name: str) -> None:
        if self.is_v1 and status:
            message = self.library.litert_lm_get_last_error_message()
            detail = message.decode("utf-8", errors="replace") if message else ""
            raise RuntimeError(f"{name} failed ({status}): {detail}")

    def _create(self, name: str, *args, arg_types: list | None = None) -> int:
        """Calls a function that returns a new handle."""
        function = getattr(self.library, name)
        types = arg_types if arg_types is not None else [_VOID_P] * len(args)
        if self.is_v1:
            function.restype = ctypes.c_int
            function.argtypes = [*types, ctypes.POINTER(_VOID_P)]
            handle = _VOID_P()
            self._check(function(*args, ctypes.byref(handle)), name)
            result = handle.value
        else:
            function.restype = _VOID_P
            function.argtypes = types
            result = function(*args)
        if not result:
            raise RuntimeError(f"{name} returned null")
        return result

    def api_version(self) -> tuple[int, int, int]:
        if not self.is_v1:
            return (0, 0, 0)
        parts = [ctypes.c_int() for _ in range(3)]
        self._check(self.library.litert_lm_get_api_version(
            *[ctypes.byref(part) for part in parts]), "litert_lm_get_api_version")
        return tuple(part.value for part in parts)

    def set_min_log_level(self, level: int) -> None:
        self._check(self.library.litert_lm_set_min_log_level(level),
                    "litert_lm_set_min_log_level")

    def engine_settings_create(self, model: str, backend: str,
                               vision_backend: str | None = None,
                               audio_backend: str | None = None) -> int:
        encode = lambda value: None if value is None else value.encode()
        return self._create(
            "litert_lm_engine_settings_create", model.encode(), backend.encode(),
            encode(vision_backend), encode(audio_backend),
            arg_types=[_STR, _STR, _STR, _STR])

    def engine_settings_set_num_threads(self, settings: int, threads: int) -> None:
        self._check(self.library.litert_lm_engine_settings_set_num_threads(settings, threads),
                    "litert_lm_engine_settings_set_num_threads")

    def engine_settings_set_cache_dir(self, settings: int, cache_dir: str) -> None:
        self._check(self.library.litert_lm_engine_settings_set_cache_dir(
            settings, cache_dir.encode()), "litert_lm_engine_settings_set_cache_dir")

    def engine_create(self, settings: int) -> int:
        return self._create("litert_lm_engine_create", settings)

    def session_config_create(self) -> int:
        return self._create("litert_lm_session_config_create")

    def engine_create_session(self, engine: int, config: int | None) -> int:
        return self._create("litert_lm_engine_create_session", engine, config)

    def sampler_params_create(self, sampler_type: int, *, top_k: int = 1,
                              top_p: float = 1.0, temperature: float = 0.0,
                              seed: int = 1) -> int:
        params = self._create("litert_lm_sampler_params_create", sampler_type,
                              arg_types=[ctypes.c_int])
        for name, value in (("top_k", top_k), ("top_p", top_p),
                            ("temperature", temperature), ("seed", seed)):
            full_name = f"litert_lm_sampler_params_set_{name}"
            self._check(getattr(self.library, full_name)(params, value), full_name)
        return params

    def conversation_config_create(self, sampler_params: int | None = None) -> int:
        config = self._create("litert_lm_conversation_config_create")
        if sampler_params:
            session_config = self.session_config_create()
            try:
                self._check(self.library.litert_lm_session_config_set_sampler_params(
                    session_config, sampler_params),
                    "litert_lm_session_config_set_sampler_params")
                self._check(self.library.litert_lm_conversation_config_set_session_config(
                    config, session_config),
                    "litert_lm_conversation_config_set_session_config")
            finally:
                self.library.litert_lm_session_config_delete(session_config)
        return config

    def conversation_create(self, engine: int, config: int) -> int:
        return self._create("litert_lm_conversation_create", engine, config)

    def conversation_optional_args_create(self, max_output_tokens: int | None = None) -> int:
        args = self._create("litert_lm_conversation_optional_args_create")
        if max_output_tokens is not None:
            self._check(
                self.library.litert_lm_conversation_optional_args_set_max_output_tokens(
                    args, max_output_tokens),
                "litert_lm_conversation_optional_args_set_max_output_tokens")
        return args

    def conversation_cancel_process(self, conversation: int) -> None:
        function = self.library.litert_lm_conversation_cancel_process
        function.restype = ctypes.c_int if self.is_v1 else None
        function.argtypes = [_VOID_P]
        self._check(function(conversation), "litert_lm_conversation_cancel_process")
