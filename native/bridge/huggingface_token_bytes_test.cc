#include "huggingface_token_bytes.h"

#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {
void Check(bool result, const char* name) {
  if (!result) throw std::runtime_error(name);
}
std::string Hex(const std::string& value) {
  static constexpr char digits[] = "0123456789abcdef";
  std::string out;
  for (unsigned char byte : value) {
    out += digits[byte >> 4];
    out += digits[byte & 15];
  }
  return out;
}
}  // namespace

int main(int argc, char** argv) {
  try {
    using litert::support::HuggingFaceTokenBytes;
    const std::string config =
        R"({"decoder":{"type":"ByteLevel"},"added_tokens":[{"id":2,"content":"Ġ","special":true},{"id":3,"content":"Ġ","special":false}]})";
    const HuggingFaceTokenBytes bytes(config);
    Check(bytes.supported(), "ByteLevel support");
    Check(bytes.TokenBytes("BANANA", 0) == "BANANA", "ASCII");
    Check(Hex(bytes.TokenBytes("fÃ©", 0)) == "66c3a9", "cafe continuation");
    Check(Hex(bytes.TokenBytes("Ã", 0)) == "c3", "partial leading UTF8");
    Check(Hex(bytes.TokenBytes("©", 0)) == "a9", "partial trailing UTF8");
    Check(Hex(bytes.TokenBytes("ðŁ", 0)) == "f09f", "partial emoji");
    Check(Hex(bytes.TokenBytes("ĺĬ", 0)) == "988a", "emoji continuation");
    Check(Hex(bytes.TokenBytes("ĀĊĠ", 0)) == "000a20", "NUL newline space");
    Check(bytes.TokenBytes("Ġ", 2) == "Ġ", "special ID preserves spelling");
    Check(bytes.TokenBytes("Ġ", 3) == " ", "nonspecial added ID decoded");
    Check(bytes.IsSpecialToken(2) && !bytes.IsSpecialToken(3),
          "added inventory");
    Check(bytes.TokenBytes("Ã日本", 3) == "Ã日本", "whole-token fallback");
    Check(!HuggingFaceTokenBytes(R"({"decoder":{"type":"WordPiece"}})")
               .supported(),
          "unsupported decoder");
    Check(
        !HuggingFaceTokenBytes(
             R"({"decoder":{"type":"Sequence","decoders":[{"type":"ByteLevel"}]}})")
             .supported(),
        "unsupported decoder composition");
    Check(!HuggingFaceTokenBytes("{}").supported(), "missing decoder");

    // The original raw vocabulary cannot satisfy this literal JSON byte oracle.
    const std::string expected = "{\"café\":\"日本😊\"}";
    const std::string raw = "{\"cafÃ©\":\"æĹ¥æľ¬ðŁĺĬ\"}";
    Check(raw != expected, "unpatched cause control");
    Check(bytes.TokenBytes(raw, 0) == expected, "literal Unicode JSON bytes");
    if (argc == 2) {
      nlohmann::json fixture;
      std::ifstream input(argv[1]);
      input >> fixture;
      const HuggingFaceTokenBytes actual(fixture["config"].dump());
      Check(actual.supported(), "fixture decoder");
      for (const auto& entry : fixture["tokens"]) {
        const int id = entry["id"];
        const std::string raw_token = entry["raw"];
        Check(Hex(actual.TokenBytes(raw_token, id)) == entry["hex"],
              "vocabulary bytes");
        Check(actual.IsSpecialToken(id) == entry["special"],
              "vocabulary special identity");
      }
      std::cout << "vocabulary IDs verified: " << fixture["tokens"].size()
                << '\n';
    }
    std::cout << "PASS: production ByteLevel adapter, raw cause and Unicode "
                 "byte oracle\n";
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
