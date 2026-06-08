# Current Upstream Snapshot

As of `2026-06-08`, the latest upstream release resolved by
`tools/fetch_upstream.py --latest --metadata-only` is:

- Repository: `google-ai-edge/LiteRT-LM`
- Tag: `v0.13.1`
- Published: `2026-06-03T20:52:11Z`
- Release URL: `https://github.com/google-ai-edge/LiteRT-LM/releases/tag/v0.13.1`
- Assets:
  - `CLiteRTLM.xcframework.zip`
  - `CLiteRTLM_mac.xcframework.zip`

Older releases have exposed different asset matrices. For example, `v0.11.0`
included standalone CLI assets for Android, iOS simulator, Linux x64, macOS
arm64, and Windows x64, while `v0.13.1` publishes Apple XCFramework archives.
The native repo should not assume that upstream releases always publish the same
asset matrix.

Production packaging should support both modes:

- consume official upstream artifacts when they exist and expose the required
  ABI/API surface
- build or wrap from source when official artifacts are missing for a target
