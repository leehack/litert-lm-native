#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = REPO_ROOT / "dist" / "official"
GITHUB_API = "https://api.github.com/repos/google-ai-edge/LiteRT-LM"


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "litert-lm-native-package-official-assets",
        },
    )
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def download(url: str, path: Path) -> None:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "litert-lm-native-package-official-assets"},
    )
    with urllib.request.urlopen(request) as response, path.open("wb") as file:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            file.write(chunk)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download official upstream release assets into dist/official."
    )
    parser.add_argument("--upstream-tag", required=True)
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()

    target_dir = DIST_DIR / args.upstream_tag
    if args.clean and target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    release = fetch_json(f"{GITHUB_API}/releases/tags/{args.upstream_tag}")
    assets = release.get("assets", [])
    for asset in assets:
        name = asset["name"]
        print(f"Downloading upstream release asset: {name}", flush=True)
        download(asset["browser_download_url"], target_dir / name)

    print(f"Downloaded {len(assets)} official release assets", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
