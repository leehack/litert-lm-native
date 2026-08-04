from __future__ import annotations

import re

BASE_C_API_SYMBOLS = [
    b"litert_lm_engine_settings_create",
    b"litert_lm_engine_create",
    b"litert_lm_conversation_create",
    b"litert_lm_conversation_send_message_stream",
]

V0_14_C_API_SYMBOLS = [
    b"litert_lm_sampler_params_create",
    b"litert_lm_sampler_params_delete",
    b"litert_lm_sampler_params_set_top_k",
    b"litert_lm_sampler_params_set_top_p",
    b"litert_lm_sampler_params_set_temperature",
    b"litert_lm_sampler_params_set_seed",
    b"litert_lm_session_config_set_lora_path",
    b"litert_lm_session_config_set_audio_lora_path",
    b"litert_lm_conversation_config_set_stream_tool_calls",
    b"litert_lm_conversation_optional_args_set_max_output_tokens",
    b"litert_lm_input_data_create",
    b"litert_lm_input_data_delete",
    b"litert_lm_engine_settings_create_from_raw_file_descriptor",
    b"litert_lm_engine_settings_set_num_threads",
    b"litert_lm_engine_settings_set_audio_num_threads",
    b"litert_lm_engine_settings_set_lora_rank",
    b"litert_lm_engine_settings_set_supported_lora_ranks",
    b"litert_lm_engine_settings_set_audio_lora_rank",
    b"litert_lm_engine_settings_set_supported_audio_lora_ranks",
    b"litert_lm_conversation_render_preface_to_string",
]

V0_15_C_API_SYMBOLS = [
    b"litert_lm_stream_chunk_get_text",
    b"litert_lm_stream_chunk_is_final",
    b"litert_lm_stream_chunk_get_error",
]

BRIDGE_SYMBOLS = [
    b"stream_proxy_callback_abi_version",
    b"stream_proxy_load_global",
    b"stream_proxy_create",
    b"stream_proxy_delete",
    b"stream_proxy_free_string",
]


def _version_tuple(tag: str) -> tuple[int, int, int] | None:
    match = re.search(r"v?(\d+)\.(\d+)\.(\d+)", tag)
    if match is None:
        return None
    return tuple(int(part) for part in match.groups())


def is_at_least(tag: str, version: tuple[int, int, int]) -> bool:
    parsed = _version_tuple(tag)
    if parsed is None:
        return False
    return parsed >= version


def uses_stream_chunk_api(upstream_tag: str) -> bool:
    return is_at_least(upstream_tag, (0, 15, 0))


def required_c_api_symbols(upstream_tag: str) -> list[bytes]:
    symbols = list(BASE_C_API_SYMBOLS)
    if is_at_least(upstream_tag, (0, 14, 0)):
        symbols.extend(V0_14_C_API_SYMBOLS)
    if uses_stream_chunk_api(upstream_tag):
        symbols.extend(V0_15_C_API_SYMBOLS)
    return symbols
