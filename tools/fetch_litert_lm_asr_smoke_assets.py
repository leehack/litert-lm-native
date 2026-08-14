#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import shutil
import urllib.request
from dataclasses import dataclass
from pathlib import Path


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

    partial = destination.with_suffix(destination.suffix + ".part")
    partial.unlink(missing_ok=True)
    request = urllib.request.Request(asset.url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request) as response, partial.open("wb") as output:
        shutil.copyfileobj(response, output)
    actual = sha256(partial)
    if actual != asset.sha256:
        partial.unlink(missing_ok=True)
        raise RuntimeError(
            f"Checksum mismatch for {asset.filename}: expected {asset.sha256}, "
            f"got {actual}."
        )
    partial.replace(destination)
    print(f"Downloaded and verified {destination}", flush=True)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch immutable real-model assets for the LiteRT-LM ASR smoke."
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    for asset in ASSETS:
        fetch_asset(asset, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
