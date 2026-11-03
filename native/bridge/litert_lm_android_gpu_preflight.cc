#include "bridge/litert_lm_android_gpu_preflight.h"

#include <utility>

#include "absl/status/status_macros.h"
#include "bridge/android_gpu_safety.h"
#include "runtime/util/memory_mapped_file.h"

namespace litert_lm_native {
absl::Status PrepareAndroidGpuSafety(litert::lm::EngineSettings &settings) {
#if defined(__ANDROID__)
  auto &executor = settings.GetMutableMainExecutorSettings();
  if (executor.GetBackend() != litert::lm::Backend::GPU) {
    return absl::OkStatus();
  }
  const auto &assets = executor.GetModelAssets();
  auto identity = FixtureIdentity::kUnreadable;
  if (assets.HasMemoryMappedFile()) {
    ABSL_ASSIGN_OR_RETURN(auto mapped, assets.GetMemoryMappedFile());
    identity = IdentifyQwen3Bytes(mapped->data(), mapped->length());
  } else if (assets.HasDataStream()) {
    return absl::FailedPreconditionError(
        "Android GPU safety preflight cannot inspect a DataStream asset. "
        "Use a stable file descriptor, mapped asset, or CPU.");
  } else {
    auto file = assets.GetOrCreateScopedFile();
    if (!file.ok()) {
      return absl::FailedPreconditionError(
          "Android GPU safety preflight cannot open model assets; "
          "engine initialization was not attempted.");
    }
    identity = IdentifyQwen3File((*file)->file());
    auto path = assets.GetPath();
    ABSL_ASSIGN_OR_RETURN(auto pinned,
                          litert::lm::ModelAssets::Create(
                              *file, path.ok() ? *path : absl::string_view()));
    pinned.SetFakeWeightsMode(assets.fake_weights_mode());
    executor.SetModelAssets(std::move(pinned));
  }
  const auto probe = identity == FixtureIdentity::kQwen3
                         ? ProbeAndroidVulkanFacts()
                         : GpuProbe{};
  const auto restriction = Qwen3GpuRestriction(identity, probe);
  if (!restriction.empty())
    return absl::FailedPreconditionError(restriction);
#else
  (void)settings;
#endif
  return absl::OkStatus();
}
} // namespace litert_lm_native
