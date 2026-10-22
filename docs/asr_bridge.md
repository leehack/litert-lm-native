# Native ASR Bridge

LiteRT-LM `v0.16.0` contains a stateful C++ ASR engine and session pipeline,
but its released `c/engine.h` and official C runtime binaries do not expose
that pipeline. `litert-lm-native` therefore owns a narrow, versioned C bridge
for ASR beginning with bridge ABI version 1.

The bridge is compiled only for LiteRT-LM `v0.16.0` or newer. Release tooling
uses source-built Apple runtimes for those tags because wrapping the official
Apple C binaries cannot add C++ objects that are absent from those binaries.

## ABI version 1

The public declaration is
[`native/bridge/litert_lm_asr_bridge.h`](../native/bridge/litert_lm_asr_bridge.h).
Consumers must probe `litert_lm_asr_abi_version()` before binding the remaining
symbols and compare `litert_lm_asr_config_size()` and
`litert_lm_asr_result_size()` with their FFI layouts before allocating either
structure.

ABI version 1 provides:

- explicit model, tokenizer, decoder, merger, preprocessor, and backend config
- released metadata presets for Parakeet TDT/CTC, Moonshine Tiny, Whisper Tiny,
  and Qwen3-ASR 0.6B so downstream bindings do not duplicate token IDs or
  log-mel parameters
- bounded mono float-PCM input with partial-accept backpressure
- overlapping fixed-size inference windows
- confirmed and revisable unconfirmed transcript text
- finish, final flush, reset, and between-window cancellation
- owned result/error strings with matching release functions

It deliberately does not claim:

- encoded-audio decoding or resampling at the bridge boundary
- timestamps, confidence, language identification, or diarization
- interruption of a LiteRT inference call already in flight
- browser support

The downstream client owns input conversion to the configured sample rate and
model/tokenizer download integrity. ABI version 1 accepts mono PCM only.

`model_path` may name a `.tflite` model or a `.litertlm` container. A container
whose AsrMetadata declares Whisper, Moonshine or Parakeet loads its ASR TFLite
section and its embedded tokenizer, and the container's model type overrides
`decoder_type`. Containers that declare Qwen3-ASR, or carry only LLM metadata,
use the LLM route. `tokenizer_path` stays required by ABI version 1 validation
but is not read for containers. A container that declares a speech model
without an ASR section fails at engine creation with `NOT_FOUND`. v0.18.0 and v0.18.1
carry this routing as a backport
([#77](https://github.com/leehack/litert-lm-native/issues/77),
[audit](upstream_patch_audit.md)).

## Flow control

`litert_lm_asr_session_push_audio_f32` reports the number of samples accepted.
`LITERT_LM_ASR_STATUS_WOULD_BLOCK` means the bounded queue could not accept the
entire input; process a window and retry the unaccepted suffix.

`litert_lm_asr_session_process_next` runs no more than one inference window and
returns `LITERT_LM_ASR_STATUS_NEEDS_MORE_AUDIO` when a complete window is not
yet buffered. After `finish_audio`, a partial final window is zero padded and a
final result flushes remaining unconfirmed text. Later calls return
`LITERT_LM_ASR_STATUS_END_OF_STREAM`.

`cancel` may run concurrently with `process_next`, but upstream LiteRT-LM
`v0.16.0` has no in-flight inference interrupt. Cancellation is observed before
or after the active window. Callers must wait for `process_next` to return
before deleting the session.

## Validation

The bridge has three validation layers:

1. C11 header/ABI initialization coverage.
2. C++ push-source coverage for overlap, partial flush, bounded backpressure,
   cancellation, and reset.
3. An opt-in exported-dylib smoke:

```bash
python3 tools/litert_lm_asr_smoke.py \
  --library /path/to/libLiteRtLm.dylib \
  --model /path/to/moonshine_tiny_5s_i8.tflite \
  --tokenizer /path/to/tokenizer.json \
  --audio /path/to/mono-16khz-pcm16.wav \
  --expect country
```

The smoke reads WAV only as test-fixture input, converts it to float PCM in the
runner, pushes 100 ms fragments through the exported ABI, and asserts a known
transcript substring. `tools/fetch_litert_lm_asr_smoke_assets.py` downloads the
Moonshine model, tokenizer, and WAV from immutable revisions and verifies their
SHA-256 digests. The manually dispatched native release workflow can run the
real-model smoke on compatible host targets by setting `run_asr_smoke=true`.
PR qualification also runs the pinned Whisper tiny `.litertlm` container
(`--preset whisper-tiny`) and two derived malformed containers that must fail at
engine creation (`--expect-engine-error`).
Large remote models stay out of default CI.

For v0.18.0 untimed-word overlap merging, see the
[scoped patch and model-free qualification](asr_untimed_overlap.md).
The default overlap remains 0.4. Timed words and single-window input retain
upstream behavior. The patch's JFK replay reproduces the reported boundary
failure with constructed words; release qualification still needs real-model
JFK exact-transcript validation against the packaged library.

## TTS boundary

LiteRT-LM `v0.16.0` also contains TTS stages and synchronous/asynchronous
session interfaces, but its public `TtsEngine::Create` does not yet assemble
model-specific Qwen3-TTS or Kokoro components and no TTS C ABI is published.
Keep a future TTS bridge separate from this ASR ABI so the ASR release does not
inherit the less mature TTS factory contract.
