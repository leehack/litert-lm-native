#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
from dataclasses import dataclass
from pathlib import Path

from download_utils import download_to_path

USER_AGENT = "litert-lm-native-asr-smoke/1"


@dataclass(frozen=True)
class Asset:
    filename: str
    url: str
    sha256: str


ASSETS = (
    Asset(
        filename="moonshine_tiny_5s_i8.tflite",
        url=(
            "https://huggingface.co/litert-community/moonshine-tiny/resolve/"
            "beb49ee5028b4fb21eb989bcbd2db30a433373db/"
            "moonshine_tiny_5s_i8.tflite"
        ),
        sha256="97abdeea122d579229091659c24c59d988c6419d453a200f6471241a53b9a9b9",
    ),
    Asset(
        filename="moonshine_tokenizer.json",
        url=(
            "https://huggingface.co/UsefulSensors/moonshine-tiny/resolve/"
            "390624ed33d594443aa4aa221f5b9f283b545b5a/tokenizer.json"
        ),
        sha256="6579793438bc4fbafffacf699169ff53e3769c5a0a0f5e71cdee8853e8130deb",
    ),
    Asset(
        filename="jfk.wav",
        url=(
            "https://raw.githubusercontent.com/ggml-org/whisper.cpp/"
            "592feef04a1802b18cbeffd0fd0eb5d02570c2ec/samples/jfk.wav"
        ),
        sha256="59dfb9a4acb36fe2a2affc14bacbee2920ff435cb13cc314a08c13f66ba7860e",
    ),
    Asset(
        filename="whisper_tiny_30s_i8.litertlm",
        url=(
            "https://huggingface.co/litert-community/whisper-tiny/resolve/"
            "d0662bbcb13106e6f740632b9ff961c8e22f7a13/"
            "whisper_tiny_30s_i8.litertlm"
        ),
        sha256="92f194600d98e1d94b1ff6f636d109c0f4ac66f3f6a1803f7a665e93daf78012",
    ),
    Asset(
        filename="whisper_tokenizer.json",
        url=(
            "https://huggingface.co/openai/whisper-tiny/resolve/"
            "169d4a4341b33bc18d8881c4b69c2e104e1cc0af/tokenizer.json"
        ),
        sha256="27fc476bfe7f17299480be2273fc0608e4d5a99aba2ab5dec5374b4482d1a566",
    ),
)


@dataclass(frozen=True)
class DerivedAsset:
    filename: str
    source: str
    offset: int
    original: bytes
    replacement: bytes
    sha256: str


# Malformed variants of the pinned Whisper container for routing negatives.
DERIVED_ASSETS = (
    # Hides the encoder-decoder section's model_type item, so the loader keys
    # it as a legacy LLM section while AsrMetadata still declares Whisper.
    DerivedAsset(
        filename="whisper_tiny_30s_i8_missing_asr_model.litertlm",
        source="whisper_tiny_30s_i8.litertlm",
        offset=176,
        original=b"model_type",
        replacement=b"model_typx",
        sha256="e924824c6cf9d0900cbe192d73eee552b9198fdcf94b1a10d550c622ef30c360",
    ),
    # Declares Qwen3-ASR in AsrMetadata, which must keep the LLM route.
    DerivedAsset(
        filename="whisper_tiny_30s_i8_qwen3_metadata.litertlm",
        source="whisper_tiny_30s_i8.litertlm",
        offset=16384,
        original=bytes.fromhex("0a020a00"),
        replacement=bytes.fromhex("0a022200"),
        sha256="9b1f38b80cbf4e81f0f6198fcb38df66bb4d64ed7eeaeef8b82e028b32c1e7c4",
    ),
    # Declares Parakeet over an encoder-decoder section, which selects TDT.
    DerivedAsset(
        filename="a1b2c3d4_parakeet_tdt.litertlm",
        source="whisper_tiny_30s_i8.litertlm",
        offset=16384,
        original=bytes.fromhex("0a020a00"),
        replacement=bytes.fromhex("0a021200"),
        sha256="375d833ef72808a28b6a6bf97ba73f49736e377183170bb845b2596ae696b082",
    ),
    # Renames that section to the audio encoder, which selects CTC.
    DerivedAsset(
        filename="a1b2c3d4_parakeet_ctc.litertlm",
        source="a1b2c3d4_parakeet_tdt.litertlm",
        offset=144,
        original=b"\x17\0\0\0tf_lite_encoder_decoder",
        replacement=b"\x15\0\0\0tf_lite_audio_encoder\0\0",
        sha256="18390a7cab945aabd6daa39d6560eda0f1f804dc536c771e55f4c2010677cf9c",
    ),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_asset(asset: Asset, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / asset.filename
    if destination.is_file() and sha256(destination) == asset.sha256:
        print(f"Verified cached {destination}", flush=True)
        return destination

    download_to_path(
        asset.url,
        destination,
        headers={"User-Agent": USER_AGENT},
        label=asset.filename,
        attempts=3,
        timeout_seconds=30,
        deadline_seconds=300,
        expected_sha256=asset.sha256,
    )
    print(f"Downloaded and verified {destination}", flush=True)
    return destination


def derive_asset(asset: DerivedAsset, output_dir: Path) -> Path:
    destination = output_dir / asset.filename
    if destination.is_file() and sha256(destination) == asset.sha256:
        print(f"Verified cached {destination}", flush=True)
        return destination
    data = bytearray((output_dir / asset.source).read_bytes())
    end = asset.offset + len(asset.original)
    if bytes(data[asset.offset:end]) != asset.original:
        raise RuntimeError(f"{asset.source} does not match the {asset.filename} recipe")
    data[asset.offset:end] = asset.replacement
    partial = destination.with_name(destination.name + ".part")
    partial.write_bytes(data)
    if sha256(partial) != asset.sha256:
        partial.unlink()
        raise RuntimeError(f"Checksum mismatch for derived {asset.filename}")
    partial.replace(destination)
    print(f"Derived and verified {destination}", flush=True)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch immutable real-model assets for the LiteRT-LM ASR smoke."
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    for asset in ASSETS:
        fetch_asset(asset, args.output_dir)
    for derived in DERIVED_ASSETS:
        derive_asset(derived, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
