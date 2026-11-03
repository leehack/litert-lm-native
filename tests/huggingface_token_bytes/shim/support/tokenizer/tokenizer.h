// Model-free seam: omit only LiteRT tensor helpers unused by the HF tokenizer.
#pragma once
#include <string>
#include <vector>

#include "absl/status/statusor.h"
#include "absl/strings/string_view.h"
#include "absl/types/span.h"
namespace litert::support {
enum class TokenizerType { kUnspecified, kSentencePiece, kHuggingFace };
class Tokenizer {
 public:
  virtual ~Tokenizer() = default;
  virtual TokenizerType GetTokenizerType() const = 0;
  virtual absl::StatusOr<std::vector<int>> TextToTokenIds(
      absl::string_view) = 0;
  virtual absl::StatusOr<int> TokenToId(absl::string_view) = 0;
  virtual absl::StatusOr<std::string> TokenIdsToText(absl::Span<const int>,
                                                     bool) = 0;
  absl::StatusOr<std::string> TokenIdsToText(absl::Span<const int> ids) {
    return TokenIdsToText(ids, false);
  }
  virtual std::vector<std::string> GetTokens() const = 0;
  virtual absl::StatusOr<std::vector<std::string>> GetTokenBytes() const {
    return GetTokens();
  }
  virtual bool IsSpecialToken(int) const { return false; }
  virtual int GetVocabSize() const = 0;
};
}  // namespace litert::support
