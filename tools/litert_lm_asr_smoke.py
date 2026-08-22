#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import struct
import wave
from pathlib import Path


ABI_VERSION = 1
STATUS_OK = 0
STATUS_CANCELLED = 7
STATUS_NEEDS_MORE_AUDIO = 10
STATUS_END_OF_STREAM = 11
STATUS_WOULD_BLOCK = 12

_DLL_DIRECTORY_HANDLES: list[object] = []


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class AsrConfig(ctypes.Structure):
    _fields_ = [
        ("struct_size", ctypes.c_uint32),
        ("abi_version", ctypes.c_uint32),
        ("model_name", ctypes.c_char_p),
        ("model_path", ctypes.c_char_p),
        ("tokenizer_path", ctypes.c_char_p),
        ("sample_rate_hz", ctypes.c_int32),
        ("num_channels", ctypes.c_int32),
        ("input_milliseconds", ctypes.c_int32),
        ("max_buffered_audio_milliseconds", ctypes.c_int32),
        ("decoder_type", ctypes.c_int),
        ("backend", ctypes.c_int),
        ("text_merger_type", ctypes.c_int),
        ("num_threads", ctypes.c_int32),
        ("overlap_ratio", ctypes.c_float),
        ("has_log_mel_config", ctypes.c_int32),
        ("log_mel_n_fft", ctypes.c_int32),
        ("log_mel_n_mels", ctypes.c_int32),
        ("log_mel_hop_length", ctypes.c_int32),
        ("log_mel_n_frames", ctypes.c_int32),
        ("log_mel_transpose", ctypes.c_int32),
        ("log_mel_preemphasis", ctypes.c_float),
        ("log_mel_norm_type", ctypes.c_int),
        ("decode_start_token_id", ctypes.c_int32),
        ("decode_stop_token_id", ctypes.c_int32),
        ("decode_skip_until_token_id", ctypes.c_int32),
        ("decode_statefully_after", ctypes.c_int32),
        ("vocab_size", ctypes.c_int32),
        ("blank_token_id", ctypes.c_int32),
    ]


class AsrResult(ctypes.Structure):
    _fields_ = [
        ("struct_size", ctypes.c_uint32),
        ("confirmed_text", ctypes.c_void_p),
        ("unconfirmed_text", ctypes.c_void_p),
        ("is_final", ctypes.c_int32),
    ]


def bind(library_path: Path) -> ctypes.CDLL:
    if os.name == "nt":
        _DLL_DIRECTORY_HANDLES.append(
            os.add_dll_directory(str(library_path.parent))
        )
    library = ctypes.CDLL(str(library_path))
    library.litert_lm_asr_abi_version.restype = ctypes.c_uint32
    library.litert_lm_asr_config_size.restype = ctypes.c_size_t
    library.litert_lm_asr_result_size.restype = ctypes.c_size_t
    library.litert_lm_asr_config_init.argtypes = [ctypes.POINTER(AsrConfig)]
    library.litert_lm_asr_config_init_for_model_preset.argtypes = [
        ctypes.POINTER(AsrConfig),
        ctypes.c_int,
    ]
    library.litert_lm_asr_config_init_for_model_preset.restype = ctypes.c_int
    library.litert_lm_asr_result_init.argtypes = [ctypes.POINTER(AsrResult)]
    library.litert_lm_asr_result_release.argtypes = [ctypes.POINTER(AsrResult)]
    library.litert_lm_asr_free_string.argtypes = [ctypes.c_void_p]
    library.litert_lm_asr_engine_create.argtypes = [
        ctypes.POINTER(AsrConfig),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    library.litert_lm_asr_engine_create.restype = ctypes.c_int
    library.litert_lm_asr_engine_delete.argtypes = [ctypes.c_void_p]
    library.litert_lm_asr_session_create.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    library.litert_lm_asr_session_create.restype = ctypes.c_int
    library.litert_lm_asr_session_delete.argtypes = [ctypes.c_void_p]
    library.litert_lm_asr_session_push_audio_f32.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_float),
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    library.litert_lm_asr_session_push_audio_f32.restype = ctypes.c_int
    library.litert_lm_asr_session_finish_audio.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    library.litert_lm_asr_session_finish_audio.restype = ctypes.c_int
    library.litert_lm_asr_session_process_next.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(AsrResult),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    library.litert_lm_asr_session_process_next.restype = ctypes.c_int
    return library


def take_error(library: ctypes.CDLL, error: ctypes.c_void_p) -> str:
    if not error.value:
        return "No error detail was returned."
    message = ctypes.string_at(error.value).decode("utf-8", errors="replace")
    library.litert_lm_asr_free_string(error)
    return message


def check_status(
    library: ctypes.CDLL,
    status: int,
    error: ctypes.c_void_p,
    operation: str,
    *,
    allowed: set[int] | None = None,
) -> None:
    if status == STATUS_OK or (allowed is not None and status in allowed):
        if error.value:
            library.litert_lm_asr_free_string(error)
        return
    raise RuntimeError(f"{operation} failed ({status}): {take_error(library, error)}")


def read_pcm16_mono(path: Path) -> tuple[int, list[float]]:
    with wave.open(str(path), "rb") as audio:
        if audio.getnchannels() != 1 or audio.getsampwidth() != 2:
            raise ValueError("The smoke fixture must be mono PCM16 WAV.")
        sample_rate = audio.getframerate()
        frame_count = audio.getnframes()
        pcm = audio.readframes(frame_count)
    samples = [value / 32768.0 for (value,) in struct.iter_unpack("<h", pcm)]
    return sample_rate, samples


def configure_moonshine(
    library: ctypes.CDLL,
    model_path: Path,
    tokenizer_path: Path,
) -> AsrConfig:
    config = AsrConfig()
    status = library.litert_lm_asr_config_init_for_model_preset(
        ctypes.byref(config), 3
    )
    if status != STATUS_OK:
        raise RuntimeError(f"Could not initialize Moonshine ASR preset: {status}")
    config.model_path = str(model_path).encode()
    config.tokenizer_path = str(tokenizer_path).encode()
    config.backend = 0  # CPU.
    return config


def process_available(
    library: ctypes.CDLL,
    session: ctypes.c_void_p,
    events: list[dict[str, object]],
) -> bool:
    while True:
        result = AsrResult()
        library.litert_lm_asr_result_init(ctypes.byref(result))
        error = ctypes.c_void_p()
        status = library.litert_lm_asr_session_process_next(
            session, ctypes.byref(result), ctypes.byref(error)
        )
        if status == STATUS_NEEDS_MORE_AUDIO:
            return False
        if status == STATUS_END_OF_STREAM:
            return True
        check_status(library, status, error, "process_next")
        confirmed = (
            ctypes.string_at(result.confirmed_text).decode("utf-8")
            if result.confirmed_text
            else ""
        )
        unconfirmed = (
            ctypes.string_at(result.unconfirmed_text).decode("utf-8")
            if result.unconfirmed_text
            else ""
        )
        is_final = bool(result.is_final)
        events.append(
            {
                "confirmed": confirmed,
                "unconfirmed": unconfirmed,
                "isFinal": is_final,
            }
        )
        library.litert_lm_asr_result_release(ctypes.byref(result))
        if is_final:
            return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the exported LiteRT-LM native ASR bridge on a WAV file."
    )
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--expect", help="Case-insensitive transcript substring.")
    parser.add_argument("--evidence-json", type=Path)
    parser.add_argument("--platform")
    parser.add_argument("--arch")
    parser.add_argument("--upstream-commit")
    parser.add_argument("--native-commit")
    args = parser.parse_args()
    if args.evidence_json and not all(
        (args.platform, args.arch, args.upstream_commit, args.native_commit)
    ):
        parser.error(
            "--evidence-json requires --platform, --arch, --upstream-commit, "
            "and --native-commit"
        )

    library = bind(args.library.resolve())
    if library.litert_lm_asr_abi_version() != ABI_VERSION:
        raise RuntimeError("Loaded runtime does not expose ASR bridge ABI version 1.")
    if library.litert_lm_asr_config_size() != ctypes.sizeof(AsrConfig):
        raise RuntimeError("ASR config layout does not match the loaded runtime.")
    if library.litert_lm_asr_result_size() != ctypes.sizeof(AsrResult):
        raise RuntimeError("ASR result layout does not match the loaded runtime.")

    sample_rate, samples = read_pcm16_mono(args.audio)
    if sample_rate != 16000:
        raise ValueError(f"Expected 16000 Hz fixture, got {sample_rate} Hz.")

    config = configure_moonshine(library, args.model, args.tokenizer)
    engine = ctypes.c_void_p()
    error = ctypes.c_void_p()
    status = library.litert_lm_asr_engine_create(
        ctypes.byref(config), ctypes.byref(engine), ctypes.byref(error)
    )
    check_status(library, status, error, "engine_create")

    session = ctypes.c_void_p()
    events: list[dict[str, object]] = []
    try:
        status = library.litert_lm_asr_session_create(
            engine, ctypes.byref(session), ctypes.byref(error)
        )
        check_status(library, status, error, "session_create")
        # The public contract permits releasing the engine wrapper once a
        # session retains its model resources. Exercise that lifetime ordering
        # before any inference so cleanup regressions fail this smoke.
        library.litert_lm_asr_engine_delete(engine)
        engine = ctypes.c_void_p()

        chunk_samples = sample_rate // 10
        offset = 0
        while offset < len(samples):
            chunk = samples[offset : offset + chunk_samples]
            native_chunk = (ctypes.c_float * len(chunk))(*chunk)
            accepted = ctypes.c_size_t()
            error = ctypes.c_void_p()
            status = library.litert_lm_asr_session_push_audio_f32(
                session,
                native_chunk,
                len(chunk),
                ctypes.byref(accepted),
                ctypes.byref(error),
            )
            check_status(
                library,
                status,
                error,
                "push_audio_f32",
                allowed={STATUS_WOULD_BLOCK},
            )
            offset += accepted.value
            process_available(library, session, events)

        error = ctypes.c_void_p()
        status = library.litert_lm_asr_session_finish_audio(
            session, ctypes.byref(error)
        )
        check_status(library, status, error, "finish_audio")
        if not process_available(library, session, events):
            raise RuntimeError("Finished ASR stream still requested more audio.")
    finally:
        if session.value:
            library.litert_lm_asr_session_delete(session)
        if engine.value:
            library.litert_lm_asr_engine_delete(engine)

    transcript = " ".join(
        str(event["confirmed"]).strip()
        for event in events
        if str(event["confirmed"]).strip()
    ).strip()
    if args.expect and args.expect.casefold() not in transcript.casefold():
        raise RuntimeError(
            f"Expected transcript to contain {args.expect!r}, got {transcript!r}."
        )
    result = {
        "abiVersion": ABI_VERSION,
        "sampleRateHz": sample_rate,
        "sampleCount": len(samples),
        "events": events,
        "transcript": transcript,
    }
    print("RESULT litert_lm_asr " + json.dumps(result, sort_keys=True))
    if args.evidence_json:
        evidence = {
            "id": "litert_lm_asr_moonshine",
            "result": "pass",
            "platform": args.platform,
            "arch": args.arch,
            "backend": "cpu",
            "upstreamCommit": args.upstream_commit,
            "nativeCommit": args.native_commit,
            "abiVersion": ABI_VERSION,
            "library": {
                "fileName": args.library.name,
                "sha256": sha256_file(args.library),
            },
            "model": {
                "fileName": args.model.name,
                "sha256": sha256_file(args.model),
            },
            "tokenizer": {
                "fileName": args.tokenizer.name,
                "sha256": sha256_file(args.tokenizer),
            },
            "fixture": {
                "fileName": args.audio.name,
                "sha256": sha256_file(args.audio),
                "sampleRateHz": sample_rate,
                "sampleCount": len(samples),
            },
            "expect": args.expect,
            "transcript": transcript,
        }
        args.evidence_json.parent.mkdir(parents=True, exist_ok=True)
        args.evidence_json.write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote release evidence {args.evidence_json}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
