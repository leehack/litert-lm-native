# Current Upstream Snapshot

As of the first scaffold, the latest upstream release resolved by
`tools/fetch_upstream.py --latest --metadata-only` is:

- Repository: `google-ai-edge/LiteRT-LM`
- Tag: `v0.12.0`
- Published: `2026-05-18T20:53:57Z`
- Release URL: `https://github.com/google-ai-edge/LiteRT-LM/releases/tag/v0.12.0`
- Asset: `CLiteRTLM.xcframework.zip`

Older release `v0.11.0` exposed standalone CLI assets for Android, iOS
simulator, Linux x64, macOS arm64, and Windows x64. The native repo should not
assume that upstream releases always publish the same asset matrix.

The first production implementation should support both modes:

- consume official upstream artifacts when they exist and expose the required
  ABI/API surface
- build or wrap from source when official artifacts are missing for a target
