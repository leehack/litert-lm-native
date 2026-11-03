#ifndef LITERT_LM_BRIDGE_HUGGINGFACE_TOKEN_BYTES_H_
#define LITERT_LM_BRIDGE_HUGGINGFACE_TOKEN_BYTES_H_

#include <array>
#include <cstddef>
#include <string>
#include <unordered_set>

#include "nlohmann/json.hpp"

namespace litert::support {

// ByteLevel's vocabulary alphabet represents bytes, including incomplete UTF-8.
// Keep those bytes before Rust's final from_utf8_lossy step so a grammar can
// recognize tokens which complete a code point started by an earlier token.
class HuggingFaceTokenBytes {
 public:
  explicit HuggingFaceTokenBytes(const std::string& tokenizer_json) {
    const auto config = nlohmann::json::parse(tokenizer_json, nullptr, false);
    if (!config.is_object()) return;
    const auto decoder = config.find("decoder");
    if (decoder != config.end() && decoder->is_object()) {
      const auto type = decoder->find("type");
      supported_ = type != decoder->end() && type->is_string() &&
                   type->get<std::string>() == "ByteLevel";
    }
    const auto added = config.find("added_tokens");
    if (added == config.end() || !added->is_array()) return;
    for (const auto& token : *added) {
      if (!token.is_object()) continue;
      const auto id = token.find("id");
      const auto special = token.find("special");
      if (id != token.end() && id->is_number_integer() &&
          special != token.end() && special->is_boolean() &&
          special->get<bool>()) {
        special_ids_.insert(id->get<int>());
      }
    }
  }

  bool supported() const { return supported_; }
  bool IsSpecialToken(int id) const { return special_ids_.count(id) != 0; }

  std::string TokenBytes(const std::string& token, int id) const {
    if (IsSpecialToken(id)) return token;
    static const std::array<int, 324> inverse = [] {
      std::array<int, 324> result;
      result.fill(-1);
      int extra = 256;
      for (int byte = 0; byte < 256; ++byte) {
        const bool direct = (byte >= 33 && byte <= 126) ||
                            (byte >= 161 && byte <= 172) || byte >= 174;
        result[direct ? byte : extra++] = byte;
      }
      return result;
    }();
    std::string bytes;
    bytes.reserve(token.size());
    for (size_t i = 0; i < token.size();) {
      const unsigned char first = token[i++];
      unsigned int codepoint = first;
      if (first >= 0xC2 && first <= 0xC5 && i < token.size()) {
        const unsigned char second = token[i++];
        if ((second & 0xC0) != 0x80) return token;
        codepoint = ((first & 0x1F) << 6) | (second & 0x3F);
      } else if (first >= 0x80) {
        return token;
      }
      // Match ByteLevel::decode_chain's whole-token fallback for added tokens
      // containing a character outside the byte alphabet.
      if (codepoint >= inverse.size() || inverse[codepoint] < 0) return token;
      bytes.push_back(static_cast<char>(inverse[codepoint]));
    }
    return bytes;
  }

 private:
  bool supported_ = false;
  std::unordered_set<int> special_ids_;
};

}  // namespace litert::support
#endif  // LITERT_LM_BRIDGE_HUGGINGFACE_TOKEN_BYTES_H_
