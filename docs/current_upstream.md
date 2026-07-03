# Current Upstream Snapshot

As of `2026-07-03`, the latest upstream release resolved by
`tools/fetch_upstream.py --latest --metadata-only` is:

- Repository: `google-ai-edge/LiteRT-LM`
- Tag: `v0.14.0`
- Published: `2026-07-02T18:12:47Z`
- Release URL: `https://github.com/google-ai-edge/LiteRT-LM/releases/tag/v0.14.0`
- Assets:
  - `litert_lm_main.macos_arm64`

Older releases have exposed different asset matrices. For example, `v0.11.0`
included standalone CLI assets for Android, iOS simulator, Linux x64, macOS
arm64, and Windows x64, while `v0.13.1` published Apple XCFramework archives.
Upstream `v0.14.0` no longer publishes `CLiteRTLM.xcframework.zip` or
`CLiteRTLM_mac.xcframework.zip`, so the native release workflow source-builds
Apple runtimes for that tag. The native repo should not assume that upstream
releases always publish the same asset matrix.

Production packaging should support both modes:

- consume official upstream artifacts when they exist and expose the required
  ABI/API surface
- build or wrap from source when official artifacts are missing for a target
