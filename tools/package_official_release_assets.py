#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = REPO_ROOT / "dist" / "official"


def run_json(cmd: list[str]) -> dict:
    result = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return json.loads(result.stdout)


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

    release = run_json(
        [
            "gh",
            "release",
            "view",
            args.upstream_tag,
            "--repo",
            "google-ai-edge/LiteRT-LM",
            "--json",
            "assets",
        ]
    )
    assets = release.get("assets", [])
    for asset in assets:
        name = asset["name"]
        print(f"Downloading upstream release asset: {name}")
        subprocess.run(
            [
                "gh",
                "release",
                "download",
                args.upstream_tag,
                "--repo",
                "google-ai-edge/LiteRT-LM",
                "--pattern",
                name,
                "--dir",
                str(target_dir),
                "--clobber",
            ],
            cwd=REPO_ROOT,
            check=True,
        )

    print(f"Downloaded {len(assets)} official release assets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
