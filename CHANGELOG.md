# Changelog

## Unreleased

- Restore sampler-managed lookahead for macOS linear-attention models after the v0.20.0 CPU and Metal comparison passed.
- Drop the iOS dynamic Metal accelerator path workaround for v0.20.0, whose iOS runtimes link Metal acceleration in-process.
