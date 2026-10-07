// Exact upstream LiteRT iOS registry excerpt for LiteRT-LM v0.18.0.
// Source: google-ai-edge/LiteRT 26895c9fbcc25c43faa8c1a98cd1fd28951602c3
// Apache-2.0; Copyright 2026 Google LLC.
#elif TARGET_OS_IPHONE
#if LITERT_HAS_METAL_SUPPORT
      "libLiteRtMetalAccelerator" SO_EXT,
      // Inside an Apple framework bundle the executable is named after the
      // bundle, so the accelerator ships as
      // LiteRtMetalAccelerator.framework/LiteRtMetalAccelerator.
      "LiteRtMetalAccelerator",
#endif  // LITERT_HAS_METAL_SUPPORT
#if LITERT_HAS_WEBGPU_SUPPORT
      "libLiteRtWebGpuAccelerator" SO_EXT,
#endif  // LITERT_HAS_WEBGPU_SUPPORT
