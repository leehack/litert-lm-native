#include "bridge/android_gpu_safety.h"

#include <algorithm>
#include <array>
#include <cstdio>
#include <cstring>
#include <limits>
#include <string>

#if defined(__ANDROID__) || defined(LITERT_LM_GPU_SAFETY_TEST)
#include <cerrno>
#include <openssl/sha.h>
#include <sys/stat.h>
#include <unistd.h>
#endif
#if defined(__ANDROID__)
#include <dlfcn.h>
#include <vulkan/vulkan.h>
#endif

namespace litert_lm_native {
namespace {
constexpr char kFixtureSha[] =
    "555579ff2f4fd13379abe69c1c3ab5200f7338bc92471557f1d6614a6e5ab0b4";

#if defined(__ANDROID__) || defined(LITERT_LM_GPU_SAFETY_TEST)
FixtureIdentity Identity(const unsigned char *digest) {
  char hex[65];
  for (size_t i = 0; i < 32; ++i) {
    std::snprintf(hex + i * 2, 3, "%02x", digest[i]);
  }
  return std::strcmp(hex, kFixtureSha) == 0 ? FixtureIdentity::kQwen3
                                            : FixtureIdentity::kOther;
}
#endif
} // namespace

std::string Qwen3GpuRestriction(FixtureIdentity identity,
                                const GpuProbe &probe) {
  if (identity == FixtureIdentity::kOther)
    return {};
  if (identity == FixtureIdentity::kUnreadable) {
    return "Android GPU safety preflight cannot read a stable model identity; "
           "engine initialization was not attempted. Retry with a readable "
           "immutable model or use CPU.";
  }
  const std::string remedy =
      " Exact Qwen3-0.6B fixture SHA256 "
      "555579ff2f4fd13379abe69c1c3ab5200f7338bc92471557f1d6614a6e5ab0b4 "
      "has a 155582464-byte constant. Requested GPU can enter an unsafe "
      "WebGPU fallback; the opaque accelerator's selected adapter and OpenCL "
      "route cannot be established here. Use CPU. See LiteRT-LM#3866/#3867 "
      "and litert-lm-native#51; this is a conservative restriction, not a "
      "new candidate-device reproduction.";
  if (!probe.complete || probe.devices.size() != 1) {
    return "Android GPU safety cannot be established for this known fixture: "
           "Vulkan facts unavailable or adapter selection ambiguous." +
           remedy;
  }
  const auto &gpu = probe.devices.front();
  if (gpu.vendor == 0 || gpu.device == 0 || gpu.driver == 0 ||
      gpu.storage_limit == 0) {
    return "Android GPU safety cannot be established for this known fixture: "
           "Vulkan identity or storage-limit facts are incomplete." +
           remedy;
  }
  if (gpu.vendor != 0x5143 || gpu.device != 0x43051401 ||
      gpu.driver != 2150604839u)
    return {};
  return "Android GPU safety restriction: observed Vulkan device vendor=" +
         std::to_string(gpu.vendor) + " device=" + std::to_string(gpu.device) +
         " driver=" + std::to_string(gpu.driver) +
         " maxStorageBufferRange=" + std::to_string(gpu.storage_limit) +
         ". This tuple matches the historical unsafe Adreno 750 driver." +
         remedy;
}

FixtureIdentity IdentifyQwen3File(int fd) {
#if defined(__ANDROID__) || defined(LITERT_LM_GPU_SAFETY_TEST)
  struct stat before{}, after{};
  if (fstat(fd, &before) != 0 || !S_ISREG(before.st_mode)) {
    return FixtureIdentity::kUnreadable;
  }
  if (before.st_size != static_cast<off_t>(kQwen3FixtureSize)) {
    return FixtureIdentity::kOther;
  }
  SHA256_CTX state;
  SHA256_Init(&state);
  std::array<unsigned char, 65536> bytes;
  uint64_t offset = 0;
  while (offset < kQwen3FixtureSize) {
    const size_t count = static_cast<size_t>(
        std::min<uint64_t>(bytes.size(), kQwen3FixtureSize - offset));
    ssize_t received;
    do {
      received = pread(fd, bytes.data(), count, static_cast<off_t>(offset));
    } while (received < 0 && errno == EINTR);
    if (received <= 0)
      return FixtureIdentity::kUnreadable;
    SHA256_Update(&state, bytes.data(), static_cast<size_t>(received));
    offset += static_cast<uint64_t>(received);
  }
  if (fstat(fd, &after) != 0 || before.st_size != after.st_size ||
      before.st_mtime != after.st_mtime || before.st_ctime != after.st_ctime ||
      before.st_ino != after.st_ino || before.st_dev != after.st_dev) {
    return FixtureIdentity::kUnreadable;
  }
#if defined(__APPLE__)
  if (before.st_mtimespec.tv_nsec != after.st_mtimespec.tv_nsec ||
      before.st_ctimespec.tv_nsec != after.st_ctimespec.tv_nsec) {
#else
  if (before.st_mtim.tv_nsec != after.st_mtim.tv_nsec ||
      before.st_ctim.tv_nsec != after.st_ctim.tv_nsec) {
#endif
    return FixtureIdentity::kUnreadable;
  }
  unsigned char digest[SHA256_DIGEST_LENGTH];
  SHA256_Final(digest, &state);
  return Identity(digest);
#else
  (void)fd;
  return FixtureIdentity::kOther;
#endif
}

FixtureIdentity IdentifyQwen3Bytes(const void *bytes, uint64_t size) {
#if defined(__ANDROID__) || defined(LITERT_LM_GPU_SAFETY_TEST)
  if (size != kQwen3FixtureSize)
    return FixtureIdentity::kOther;
  if (!bytes || size > std::numeric_limits<size_t>::max()) {
    return FixtureIdentity::kUnreadable;
  }
  unsigned char digest[SHA256_DIGEST_LENGTH];
  SHA256(static_cast<const unsigned char *>(bytes), static_cast<size_t>(size),
         digest);
  return Identity(digest);
#else
  (void)bytes;
  (void)size;
  return FixtureIdentity::kOther;
#endif
}

GpuProbe ProbeAndroidVulkanFacts() {
  GpuProbe result;
#if defined(__ANDROID__)
  void *library = dlopen("libvulkan.so", RTLD_NOW | RTLD_LOCAL);
  if (!library)
    return result;
  const auto create = reinterpret_cast<PFN_vkCreateInstance>(
      dlsym(library, "vkCreateInstance"));
  const auto destroy = reinterpret_cast<PFN_vkDestroyInstance>(
      dlsym(library, "vkDestroyInstance"));
  const auto enumerate = reinterpret_cast<PFN_vkEnumeratePhysicalDevices>(
      dlsym(library, "vkEnumeratePhysicalDevices"));
  const auto properties = reinterpret_cast<PFN_vkGetPhysicalDeviceProperties>(
      dlsym(library, "vkGetPhysicalDeviceProperties"));
  if (create && destroy && enumerate && properties) {
    VkInstanceCreateInfo info{};
    info.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO;
    VkInstance instance = VK_NULL_HANDLE;
    if (create(&info, nullptr, &instance) == VK_SUCCESS) {
      uint32_t count = 0;
      if (enumerate(instance, &count, nullptr) == VK_SUCCESS && count > 0 &&
          count <= 8) {
        std::array<VkPhysicalDevice, 8> devices{};
        if (enumerate(instance, &count, devices.data()) == VK_SUCCESS &&
            count <= devices.size()) {
          for (uint32_t i = 0; i < count; ++i) {
            VkPhysicalDeviceProperties props{};
            properties(devices[i], &props);
            result.devices.push_back({props.vendorID, props.deviceID,
                                      props.driverVersion,
                                      props.limits.maxStorageBufferRange});
          }
          result.complete = true;
        }
      }
      destroy(instance, nullptr);
    }
  }
  dlclose(library);
#endif
  return result;
}
} // namespace litert_lm_native
