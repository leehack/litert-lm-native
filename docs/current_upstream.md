# Current Upstream Snapshot

As of `2026-09-09`, upstream `v0.17.0` resolves to commit
`945edf38faa78b4ead9d09ec5b07f266ee2029c1` and was published at
`2026-09-08T20:56:42Z`:

- Release: https://github.com/google-ai-edge/LiteRT-LM/releases/tag/v0.17.0
- `CLiteRTLM.xcframework.zip`: 121,798,772 bytes; GitHub SHA-256
  `c94fc12aa0403cb47208e419cc3bfe258214ea17035f7a63c16de536869f2186`.
- `CLiteRTLM_mac.xcframework.zip`: 47,006,925 bytes; GitHub SHA-256
  `83efd536485c9d58fcd7fb7d4556ddb16ca46bb775b0449d08d9825c6836c1a4`.

These are upstream asset identities, not evidence of a qualified bridge-enabled
native release. The read-only PR qualification workflow now targets this exact
commit. All nine runtime builds, aggregate packaging, required exports, and
Linux x64 / Windows x64 / macOS arm64 real-model ASR evidence must pass before
calling the candidate qualified. Downstream consumers remain on
`v0.16.0-native.2`; this qualification does not publish artifacts or update pins.

The `c/engine.h` and `c/conversation.h` changes from v0.16.0 are additive:
the unspecified sampler enum value, maximum vision-token setting, and Metal
residency setting do not alter existing declarations. New embedding,
capabilities, and experimental headers do not imply downstream public support.
The existing stream callback and ASR bridge export requirements remain intact.
Upstream moved ASR reset behavior into its stage base class; the bridge's
existing override retains the same idle/run synchronization and output clearing.
Actual compilation and real-model reset checks remain qualification gates.

The prior `v0.16.1` metadata-only release resolved to the same commit as
`v0.16.0` (`924e79c91542761242244e4f1651851f822e4cbb`) and omitted the two
Apple XCFramework assets. That packaging limitation does not apply to the
new v0.17.0 release inventory.

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
