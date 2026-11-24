# Changelog

## Unreleased

- Export a versioned text LoRA capability probe so consumers can refuse unsupported adapters before creating a session.

- Restore sampler-managed lookahead for macOS linear-attention models after the v0.20.0 CPU and Metal comparison passed.
- Drop the iOS dynamic Metal accelerator path workaround for v0.20.0, whose iOS runtimes link Metal acceleration in-process.
- Use the recorded native release refs to reproduce builds before LiteRT-LM v0.20.0.
- Avoid an ext4 writeback stall when deleting a Linux CPU engine that created a new XNNPACK weight cache.
