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
    b"stream_proxy_finish_reason_abi_version",
    b"stream_proxy_get_finish_reason",
    b"stream_proxy_allocation_failure_abi_version",
    b"stream_proxy_has_allocation_failure",
    b"litert_lm_native_in_process_litert_abi_version",
]

V0_16_ASR_BRIDGE_SYMBOLS = [
    b"litert_lm_asr_abi_version",
    b"litert_lm_asr_config_size",
    b"litert_lm_asr_result_size",
    b"litert_lm_asr_config_init",
    b"litert_lm_asr_config_init_for_model_preset",
    b"litert_lm_asr_result_init",
    b"litert_lm_asr_result_release",
    b"litert_lm_asr_free_string",
    b"litert_lm_asr_engine_create",
    b"litert_lm_asr_engine_delete",
    b"litert_lm_asr_session_create",
    b"litert_lm_asr_session_delete",
    b"litert_lm_asr_session_push_audio_f32",
    b"litert_lm_asr_session_finish_audio",
    b"litert_lm_asr_session_process_next",
    b"litert_lm_asr_session_reset",
    b"litert_lm_asr_session_cancel",
]

ANDROID_OPENCL_SAMPLER_SYMBOLS = [
    "LiteRtTopKOpenClSampler_Create",
    "LiteRtTopKOpenClSampler_Destroy",
    "LiteRtTopKOpenClSampler_SampleToIdAndScoreBuffer",
    "LiteRtTopKOpenClSampler_UpdateConfig",
    "LiteRtTopKOpenClSampler_CanHandleInput",
    "LiteRtTopKOpenClSampler_HandlesInput",
    "LiteRtTopKOpenClSampler_SetInferenceFuncAndInputTensors",
]

APPLE_METAL_SAMPLER_SYMBOLS = [
    "LiteRtTopKMetalSampler_Create",
    "LiteRtTopKMetalSampler_Destroy",
    "LiteRtTopKMetalSampler_SampleToIdAndScoreBuffer",
    "LiteRtTopKMetalSampler_UpdateConfig",
    "LiteRtTopKMetalSampler_CanHandleInput",
    "LiteRtTopKMetalSampler_HandlesInput",
    "LiteRtTopKMetalSampler_SetInferenceFuncAndInputTensors",
]

APPLE_METAL_ACCELERATOR_SYMBOLS = [
    "LiteRtAcceleratorImpl",
]

APPLE_METAL_ACCELERATOR_LIBRARY = "libLiteRtMetalAccelerator.dylib"
APPLE_LITERT_LIBRARY = "libLiteRt.dylib"
APPLE_WEBGPU_ACCELERATOR_LIBRARY = "libLiteRtWebGpuAccelerator.dylib"

# LiteRT registers a statically linked GPU accelerator before it searches for a
# shared one (gpu_registry.cc), so these classes make the prebuilt Metal
# accelerator unreachable.
APPLE_STATIC_GPU_ACCELERATOR_SYMBOLS = {
    "ios": b"_ZN19GpuMetalAccelerator14CreateDelegate",
    "macos": b"_ZN20GpuWebGpuAccelerator14CreateDelegate",
}


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


def stream_proxy_callback_abi_version(upstream_tag: str) -> int:
    """Callback mode reported by the bridge for this compatibility baseline."""
    return 2 if is_at_least(upstream_tag, (0, 15, 0)) else 1


def uses_stream_chunk_api(upstream_tag: str) -> bool:
    return stream_proxy_callback_abi_version(upstream_tag) == 2


def has_asr_bridge(upstream_tag: str) -> bool:
    return is_at_least(upstream_tag, (0, 16, 0))


def has_omni_asr_engine(upstream_tag: str) -> bool:
    return is_at_least(upstream_tag, (0, 19, 0))


def uses_c_api_v1(upstream_tag: str) -> bool:
    return is_at_least(upstream_tag, (0, 19, 0))


def in_process_litert_abi_version(upstream_tag: str) -> int:
    """Value of litert_lm_native_in_process_litert_abi_version() for this baseline.

    From v0.19 every platform compiles LiteRT into the runtime (#111), and the
    build verifies it. Earlier desktop runtimes load upstream's prebuilt
    libLiteRt, and earlier mobile linkage was never verified, so they report 0.
    """
    return 1 if is_at_least(upstream_tag, (0, 19, 0)) else 0


def has_prebuilt_topk_samplers(upstream_tag: str) -> bool:
    """v0.19 links TopK samplers from source and ships no prebuilt sampler."""
    return not is_at_least(upstream_tag, (0, 19, 0))


def has_prebuilt_apple_metal_accelerator(upstream_tag: str) -> bool:
    """v0.19 Apple runtimes link their GPU accelerator and never open the prebuilt one."""
    return not is_at_least(upstream_tag, (0, 19, 0))


def has_prebuilt_apple_litert_companions(upstream_tag: str) -> bool:
    """v0.19 LiteRtLm embeds LiteRT, so Apple never opens libLiteRt or the WebGPU accelerator."""
    return not is_at_least(upstream_tag, (0, 19, 0))


def required_bridge_symbols(upstream_tag: str) -> list[bytes]:
    symbols = list(BRIDGE_SYMBOLS)
    if has_asr_bridge(upstream_tag):
        symbols.extend(V0_16_ASR_BRIDGE_SYMBOLS)
    return symbols


def required_c_api_symbols(upstream_tag: str) -> list[bytes]:
    symbols = list(BASE_C_API_SYMBOLS)
    if is_at_least(upstream_tag, (0, 14, 0)):
        symbols.extend(V0_14_C_API_SYMBOLS)
    if uses_stream_chunk_api(upstream_tag):
        symbols.extend(V0_15_C_API_SYMBOLS)
    if uses_c_api_v1(upstream_tag):
        symbols.append(b"litert_lm_get_api_version")
    return symbols
