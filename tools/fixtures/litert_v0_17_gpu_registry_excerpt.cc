// Exact upstream LiteRT iOS registry excerpt for LiteRT-LM v0.17.0.
// Source: google-ai-edge/LiteRT 9fe5be45564c868408e6514c8aabb83e211a0911
// Apache-2.0; Copyright 2026 Google LLC.
#elif TARGET_OS_IPHONE
#if LITERT_HAS_METAL_SUPPORT
      "libLiteRtMetalAccelerator" SO_EXT,
#endif  // LITERT_HAS_METAL_SUPPORT
#if LITERT_HAS_WEBGPU_SUPPORT
      "libLiteRtWebGpuAccelerator" SO_EXT,
#endif  // LITERT_HAS_WEBGPU_SUPPORT
