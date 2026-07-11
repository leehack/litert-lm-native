# Current Upstream Snapshot

As of `2026-07-11`, the latest upstream release resolved by
`tools/fetch_upstream.py --latest --metadata-only` is:

- Repository: `google-ai-edge/LiteRT-LM`
- Tag: `v0.14.0`
- Published: `2026-07-02T18:12:47Z`
- Release URL: `https://github.com/google-ai-edge/LiteRT-LM/releases/tag/v0.14.0`
- Assets:
  - `litert_lm_main.macos_arm64`
  - `CLiteRTLM.xcframework.zip`
    - SHA-256: `dddac2f6713ed65eaf01c18e115d9fec22184adf575cc7856a21387e8ba937e1`
  - `CLiteRTLM_mac.xcframework.zip`
    - SHA-256: `450615483509aaa6d34b321fdc6862e41a224b674468ab10aff64ebe113d21b7`

Older releases have exposed different asset matrices. For example, `v0.11.0`
included standalone CLI assets for Android, iOS simulator, Linux x64, macOS
arm64, and Windows x64, while `v0.13.1` published Apple XCFramework archives.
Upstream added the iOS and macOS XCFramework archives to the existing `v0.14.0`
release on `2026-07-10`. The native release workflow must use those official
archives for this tag. In particular, the consolidated iOS XCFramework
statically includes the Metal accelerator and sampler modules that LiteRT-LM's
iOS GPU path expects. The native repo should not assume that upstream releases
always publish an immutable or identical asset matrix.

Production packaging should support both modes:

- consume official upstream artifacts when they exist and expose the required
  ABI/API surface
- build or wrap from source when official artifacts are missing for a target
