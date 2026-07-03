#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from download_utils import download_to_path, fetch_json as fetch_json_with_retries

REPO_ROOT = Path(__file__).resolve().parents[1]
DOWNLOADS_DIR = REPO_ROOT / "downloads"
GITHUB_API = "https://api.github.com/repos/google-ai-edge/LiteRT-LM"
USER_AGENT = "litert-lm-native-fetch"


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, path: Path) -> None:
    download_to_path(url, path, headers=request_headers(url))


def release_url(args: argparse.Namespace) -> str:
    if args.latest:
        return f"{GITHUB_API}/releases/latest"
    return f"{GITHUB_API}/releases/tags/{args.tag}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch google-ai-edge/LiteRT-LM release metadata/assets."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--latest", action="store_true")
    group.add_argument("--tag")
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="Print release metadata without downloading assets.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DOWNLOADS_DIR,
        help="Directory for downloaded release assets.",
    )
    args = parser.parse_args()

    release = fetch_json(release_url(args))
    assets = release.get("assets", [])
    summary = {
        "tag": release["tag_name"],
        "publishedAt": release.get("published_at"),
        "htmlUrl": release.get("html_url"),
        "assets": [
            {
                "name": asset["name"],
                "size": asset["size"],
                "downloadUrl": asset["browser_download_url"],
            }
            for asset in assets
        ],
    }

    print(json.dumps(summary, indent=2, sort_keys=True))
    if args.metadata_only:
        return 0

    target_dir = args.output / release["tag_name"]
    for asset in assets:
        target = target_dir / asset["name"]
        print(f"Downloading {asset['name']} -> {target}", file=sys.stderr)
        download(asset["browser_download_url"], target)
        print(f"{sha256_file(target)}  {target}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
