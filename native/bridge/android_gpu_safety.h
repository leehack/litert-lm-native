#ifndef LITERT_LM_NATIVE_ANDROID_GPU_SAFETY_H_
#define LITERT_LM_NATIVE_ANDROID_GPU_SAFETY_H_

#include <cstdint>
#include <string>
#include <vector>

namespace litert_lm_native {
constexpr uint64_t kQwen3FixtureSize = 614236160;
constexpr uint64_t kQwen3ConstantBytes = 155582464;
enum class FixtureIdentity { kOther, kQwen3, kUnreadable };
struct GpuFacts {
  uint32_t vendor;
  uint32_t device;
  uint32_t driver;
  uint64_t storage_limit;
};
struct GpuProbe {
  bool complete = false;
  std::vector<GpuFacts> devices;
};

// Empty means outside the narrow deny policy, not GPU qualification.
std::string Qwen3GpuRestriction(FixtureIdentity identity,
                                const GpuProbe &probe);
FixtureIdentity IdentifyQwen3File(int fd);
FixtureIdentity IdentifyQwen3Bytes(const void *bytes, uint64_t size);
GpuProbe ProbeAndroidVulkanFacts();
} // namespace litert_lm_native
#endif
