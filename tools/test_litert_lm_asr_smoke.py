from __future__ import annotations

import ctypes
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import litert_lm_asr_smoke as smoke
from fetch_litert_lm_asr_smoke_assets import ASSETS
from litert_lm_asr_smoke import pinned_asset_sources


class FakeAsrLibrary:
    """Stands in for the exported ABI around engine creation only."""

    def __init__(self, status: int, message: bytes | None) -> None:
        self.status = status
        self.message = (
            ctypes.create_string_buffer(message) if message is not None else None
        )
        self.deleted_engines = 0
        self.freed_strings = 0

    def litert_lm_asr_abi_version(self) -> int:
        return smoke.ABI_VERSION

    def litert_lm_asr_config_size(self) -> int:
        return ctypes.sizeof(smoke.AsrConfig)

    def litert_lm_asr_result_size(self) -> int:
        return ctypes.sizeof(smoke.AsrResult)

    def litert_lm_asr_config_init_for_model_preset(self, config, preset) -> int:
        return smoke.STATUS_OK

    def litert_lm_asr_engine_create(self, config, engine, error) -> int:
        if self.status == smoke.STATUS_OK:
            engine._obj.value = 1
        elif self.message is not None:
            error._obj.value = ctypes.addressof(self.message)
        return self.status

    def litert_lm_asr_engine_delete(self, engine) -> None:
        self.deleted_engines += 1

    def litert_lm_asr_free_string(self, value) -> None:
        self.freed_strings += 1

    def __getattr__(self, name: str):
        raise AssertionError(f"unexpected ABI call {name}")


class LiteRtLmAsrSmokeTest(unittest.TestCase):
    def test_release_evidence_requires_exact_pinned_asset_names(self) -> None:
        sources = pinned_asset_sources(
            Path(ASSETS[0].filename),
            Path(ASSETS[1].filename),
            Path(ASSETS[2].filename),
        )
        self.assertEqual(sources["model"], ASSETS[0].url)
        self.assertEqual(sources["tokenizer"], ASSETS[1].url)
        self.assertEqual(sources["fixture"], ASSETS[2].url)

        with self.assertRaisesRegex(
            ValueError,
            r"checksum-pinned ASR assets; unsupported input\(s\): model=renamed.tflite",
        ):
            pinned_asset_sources(
                Path("renamed.tflite"),
                Path(ASSETS[1].filename),
                Path(ASSETS[2].filename),
            )


class ExpectEngineErrorTest(unittest.TestCase):
    def run_smoke(self, library: FakeAsrLibrary, expected: str) -> int:
        argv = [
            "litert_lm_asr_smoke.py", "--library", "lib", "--preset", "whisper-tiny",
            "--model", "model.litertlm", "--tokenizer", "tokenizer.json",
            "--audio", "jfk.wav", "--expect-engine-error", expected,
        ]
        with (patch.object(sys, "argv", argv),
              patch.object(smoke, "bind", return_value=library),
              patch.object(smoke, "read_pcm16_mono", return_value=(16000, [0.0]))):
            return smoke.main()

    def test_passes_when_engine_creation_fails_with_expected_message(self) -> None:
        library = FakeAsrLibrary(3, b"tf_lite_audio_encoder not found in the model.")
        self.assertEqual(self.run_smoke(library, "tf_lite_audio_encoder not found"), 0)
        self.assertEqual(library.freed_strings, 1)

    def test_enum_override_accepts_only_config_enums(self) -> None:
        self.assertEqual(smoke.enum_override("backend=99"), ("backend", 99))
        with self.assertRaises(smoke.argparse.ArgumentTypeError):
            smoke.enum_override("model_path=99")

    def test_fails_when_engine_creation_succeeds(self) -> None:
        library = FakeAsrLibrary(smoke.STATUS_OK, None)
        with self.assertRaisesRegex(RuntimeError, "engine_create succeeded"):
            self.run_smoke(library, "tf_lite_audio_encoder not found")
        self.assertEqual(library.deleted_engines, 1)

    def test_fails_when_error_message_differs(self) -> None:
        library = FakeAsrLibrary(3, b"tf_lite_prefill_decode not found in the model.")
        with self.assertRaisesRegex(RuntimeError, r"failed \(3\) without 'tf_lite_audio_encoder"):
            self.run_smoke(library, "tf_lite_audio_encoder not found")

    def test_rejects_transcript_and_evidence_expectations(self) -> None:
        for extra in (["--expect", "country"], ["--evidence-json", "out.json"]):
            with self.subTest(extra=extra), patch.object(sys, "argv", [
                "litert_lm_asr_smoke.py", "--library", "lib", "--model", "m",
                "--tokenizer", "t", "--audio", "a", "--expect-engine-error", "x", *extra,
            ]), patch("sys.stderr"):
                with self.assertRaises(SystemExit):
                    smoke.main()


if __name__ == "__main__":
    unittest.main()
