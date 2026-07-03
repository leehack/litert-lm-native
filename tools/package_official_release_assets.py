#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

from download_utils import download_to_path, fetch_json as fetch_json_with_retries

REPO_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = REPO_ROOT / "dist" / "official"
GITHUB_API = "https://api.github.com/repos/google-ai-edge/LiteRT-LM"
USER_AGENT = "litert-lm-native-package-official-assets"


def request_headers(url: str) -> dict[str, str]:
    headers = {"User-Agent": USER_AGENT}
    if url.startswith("https://api.github.com/"):
        headers["Accept"] = "application/vnd.github+json"
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
            headers["X-GitHub-Api-Version"] = "2022-11-28"
    return headers


def fetch_json(url: str) -> dict:
    return fetch_json_with_retries(url, headers=request_headers(url))


def download(url: str, path: Path) -> None:
    download_to_path(url, path, headers=request_headers(url))


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
