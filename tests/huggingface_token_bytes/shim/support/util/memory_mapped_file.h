// File loading is outside these in-memory tokenizer controls.
#pragma once
#include <memory>

#include "absl/status/statusor.h"
#include "absl/strings/string_view.h"
namespace litert::support {
class MemoryMappedFile {
 public:
  static absl::StatusOr<std::unique_ptr<MemoryMappedFile>> Create(
      absl::string_view) {
    return absl::UnimplementedError(
        "file loading unused by model-free control");
  }
  size_t length() const { return 0; }
  const char* data() const { return nullptr; }
};
}  // namespace litert::support
