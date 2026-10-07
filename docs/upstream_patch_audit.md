# LiteRT-LM v0.18.0 carried-fix audit

Audited LiteRT-LM `b2f686e2ed4718fb84ec398a61dd59ca0f0aff27`, which pins
LiteRT `26895c9fbcc25c43faa8c1a98cd1fd28951602c3`. Source inspection is
not device or GPU qualification. PR qualification exercises the packaged CPU
paths; affected GPU devices remain separate release-adoption evidence.

| Carried fix | v0.18 decision | Evidence and limit |
| --- | --- | --- |
| GPU environment teardown ordering | Skip for v0.18; retain for supported older inputs | Upstream `GpuEnvironment::Initialize` records options before `InitializeOpenCl`. Existing commit-based selection skips the patch; every Android binary must still pass the disassembly gate. |
| SentencePiece BPE single-NUL compatibility | Keep | WORKSPACE retains SentencePiece 0.2.2 SHA-256 `92381f713e094a15a1ccff1ac4a5315a4c4b82a99ac1332d6ac53c9dc8e1bcf1`, whose unpatched NORMAL NUL rejection breaks the untouched Qwen tokenizer. Sanitizer qualification covers the patched accepted case and malformed variants. |
| iOS Metal accelerator framework path | Keep pending unpatched packaged-device proof | Upstream adds the bare `LiteRtMetalAccelerator` fallback, but the registry still joins it to the runtime directory and loads that path. It does not construct our nested `@executable_path/Frameworks/LiteRtMetalAccelerator.framework/LiteRtMetalAccelerator` path. Preserve the upstream fallback while applying the explicit bundle path. Bazel 7.6.1 patch application passed against both exact old and new source files. |
| iOS Metal sampler framework path | Keep | Upstream `sampler_factory.cc` still requests `libLiteRtTopKMetalSampler.dylib`; our iOS bundle ships `LiteRtTopKMetalSampler.framework/LiteRtTopKMetalSampler`. |
| iOS FST provider disable define | Keep | The upstream gate and provider dependency remain; disabling it preserves our provider-free closure policy. Binary provider/minimum-OS checks remain mandatory; this is not proof of execution on iOS 16.4. |
| zlib download URL workaround | No additional rewrite for v0.18 | Upstream WORKSPACE already supplies the accepted mirror list; the helper preserves it. Retain the older-source URL fallback. |
| Android Dawn rollback | Device qualification outstanding | v0.18 ships changed binaries: arm64 LFS SHA-256 `657b2beb6456d50d7f6c86b315d5c2e97ad5a3870b134bcfcc2aa682ef467977`, x64 `ffc5ad473840f98b7f50fae1189b1e6c67a0a78e324253326adfb56706769b59`. The version-specific override table does not apply the older rollback to v0.18. This does not establish that Pixel Mali GPU regressions are fixed. Retain older-version overrides and qualify stock v0.18 on the affected device before adoption; do not transplant an older binary without ABI and device evidence. |
| v0.15 OpenCL sampler override | Inactive for v0.18 | Already restricted to v0.15.0; retain historical build support. |

Primary sources:

- [v0.18 WORKSPACE](https://github.com/google-ai-edge/LiteRT-LM/blob/b2f686e2ed4718fb84ec398a61dd59ca0f0aff27/WORKSPACE)
- [LiteRT GPU environment](https://github.com/google-ai-edge/LiteRT/blob/26895c9fbcc25c43faa8c1a98cd1fd28951602c3/litert/runtime/gpu_environment.cc)
- [LiteRT GPU registry](https://github.com/google-ai-edge/LiteRT/blob/26895c9fbcc25c43faa8c1a98cd1fd28951602c3/litert/runtime/accelerators/gpu_registry.cc)
- [Sampler factory](https://github.com/google-ai-edge/LiteRT-LM/blob/b2f686e2ed4718fb84ec398a61dd59ca0f0aff27/runtime/components/sampler_factory.cc)
- [Android GPU qualification](android_gpu_qualification.md)
