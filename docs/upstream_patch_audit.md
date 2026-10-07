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
| Android Dawn rollback | Keep for v0.18 | Stock v0.18 loses the Vulkan device during Qwen inference on Pixel 9 Pro (API 35, Mali-G715). A controlled APK changing only arm64 Dawn to the checksum-pinned historical binary restores raw GPU inference. Extend the existing override to v0.18; this does not fix the separate Galaxy S24 allocation limit or qualify Android x64 hardware. See the linked device qualification record. |
| v0.15 OpenCL sampler override | Inactive for v0.18 | Already restricted to v0.15.0; retain historical build support. |

Primary sources:

- [v0.18 WORKSPACE](https://github.com/google-ai-edge/LiteRT-LM/blob/b2f686e2ed4718fb84ec398a61dd59ca0f0aff27/WORKSPACE)
- [LiteRT GPU environment](https://github.com/google-ai-edge/LiteRT/blob/26895c9fbcc25c43faa8c1a98cd1fd28951602c3/litert/runtime/gpu_environment.cc)
- [LiteRT GPU registry](https://github.com/google-ai-edge/LiteRT/blob/26895c9fbcc25c43faa8c1a98cd1fd28951602c3/litert/runtime/accelerators/gpu_registry.cc)
- [Sampler factory](https://github.com/google-ai-edge/LiteRT-LM/blob/b2f686e2ed4718fb84ec398a61dd59ca0f0aff27/runtime/components/sampler_factory.cc)
- [Android GPU qualification](android_gpu_qualification.md)
