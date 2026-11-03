#include "bridge/android_gpu_safety.h"
#include <cassert>
#include <memory>
#include <string>
#include <thread>

namespace absl {
enum class StatusCode { kInvalidArgument = 3 };
struct Status {
  int code = 0;
  std::string message;
  bool ok() const { return code == 0; }
};
template <typename T> struct StatusOr {
  T value;
  bool ok() const { return true; }
  Status status() const { return {}; }
  T &&operator*() && { return std::move(value); }
};
} // namespace absl
struct Engine {};
struct Settings {
  bool gpu = true;
  bool known = true;
};
struct LiteRtLmEngineSettings {
  std::shared_ptr<Settings> settings;
};
struct LiteRtLmEngine {
  std::unique_ptr<Engine> engine;
};
using LiteRtLmStatusCode = int;
constexpr int kLiteRtLmStatusOk = 0;
thread_local std::string last_error;
thread_local int entered_factory = 0;
namespace litert::lm::c {
int ReturnError(absl::StatusCode code, const char *text) {
  last_error = text;
  return static_cast<int>(code);
}
int ToCStatus(const absl::Status &status) {
  last_error = status.message;
  return status.code;
}
} // namespace litert::lm::c
namespace EngineFactory {
absl::StatusOr<std::unique_ptr<Engine>> CreateDefault(const Settings &) {
  ++entered_factory;
  return {std::make_unique<Engine>()};
}
} // namespace EngineFactory
namespace litert_lm_native {
absl::Status PrepareAndroidGpuSafety(Settings &settings) {
  if (!settings.gpu)
    return {};
  const auto restriction = Qwen3GpuRestriction(
      settings.known ? FixtureIdentity::kQwen3 : FixtureIdentity::kOther,
      {true, {{0x5143, 0x43051401, 2150604839u, 134217728}}});
  return {restriction.empty() ? 0 : 9, restriction};
}
} // namespace litert_lm_native
struct DisabledLog {
  template <typename T> DisabledLog &operator<<(const T &) { return *this; }
};
#define ABSL_LOG(level) DisabledLog()
#define LITERT_LM_C_RETURN_IF_NULL(pointer)                                    \
  if (!(pointer))                                                              \
  return 3
// System headers are already parsed; this selects only the injected C API body.
#define __ANDROID__ 1
// PRODUCTION_ENGINE_CREATE

int main() {
  LiteRtLmEngineSettings settings{std::make_shared<Settings>()};
  auto *output = reinterpret_cast<LiteRtLmEngine *>(1);
  assert(litert_lm_engine_create(&settings, &output) == 9);
  assert(output == nullptr && entered_factory == 0);
  assert(last_error.find("Use CPU") != std::string::npos);
  assert(litert_lm_engine_create(&settings, nullptr) == 3);
  settings.settings->gpu = false;
  assert(litert_lm_engine_create(&settings, &output) == 0);
  assert(output != nullptr && entered_factory == 1);
  delete output;
  settings.settings->gpu = true;
  settings.settings->known = false;
  assert(litert_lm_engine_create(&settings, &output) == 0);
  assert(output != nullptr && entered_factory == 2);
  delete output;
  const auto parent_error = last_error;
  std::thread child([] {
    assert(last_error.empty());
    LiteRtLmEngineSettings settings{std::make_shared<Settings>()};
    LiteRtLmEngine *output = nullptr;
    assert(litert_lm_engine_create(&settings, &output) == 9);
    assert(output == nullptr && entered_factory == 0);
  });
  child.join();
  assert(last_error == parent_error);
}
