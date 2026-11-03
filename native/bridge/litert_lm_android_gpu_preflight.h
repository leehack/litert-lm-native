#ifndef LITERT_LM_NATIVE_ANDROID_GPU_PREFLIGHT_H_
#define LITERT_LM_NATIVE_ANDROID_GPU_PREFLIGHT_H_
#include "absl/status/status.h"
#include "runtime/engine/engine_settings.h"

namespace litert_lm_native {
// Operates on a local settings copy. GPU file assets are pinned to the same
// descriptor inspected here; callers must not modify model contents during use.
absl::Status PrepareAndroidGpuSafety(litert::lm::EngineSettings &settings);
} // namespace litert_lm_native
#endif
