# Current Upstream Snapshot

As of `2026-08-14`, the latest upstream release resolved by
`tools/fetch_upstream.py --latest --metadata-only` is:

- Repository: `google-ai-edge/LiteRT-LM`
- Tag: `v0.16.0`
- Published: `2026-08-11T18:25:33Z`
- Release URL: `https://github.com/google-ai-edge/LiteRT-LM/releases/tag/v0.16.0`
- Assets:
  - `CLiteRTLM.xcframework.zip`
    - Size: `87,659,348` bytes
  - `CLiteRTLM_mac.xcframework.zip`
    - Size: `46,379,992` bytes
  - `litert_lm_c_api-0.1.0.zip`
    - Size: `161,599,098` bytes
  - `litert_lm_main.macos_arm64`
    - Size: `16,034,224` bytes

LiteRT-LM 0.16 source includes `omni/asr` and `omni/tts`, but the released
`c/engine.h` and official C binaries expose neither engine. Native ASR support
therefore requires a source-built runtime plus the versioned bridge described
in [`asr_bridge.md`](asr_bridge.md). TTS remains unwrapped until its public
model-component factory is consumable.

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
