// Compile the actual patched upstream HF implementation. The C ABI seam
// supplies raw vocabulary strings, exactly as tokenizers_id_to_token does,
// without models.
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

#include "bridge/huggingface_token_bytes.h"
#include "include/tokenizers_c.h"
#include "llguidance.h"
#include "runtime/components/constrained_decoding/llg_constraint_provider.h"
#include "support/tokenizer/huggingface_tokenizer.h"

namespace {
struct Inventory {
  std::vector<std::string> tokens;
};
void Check(bool result, const char* name) {
  if (!result) throw std::runtime_error(name);
}
std::string Hex(const std::string& value) {
  static constexpr char digits[] = "0123456789abcdef";
  std::string result;
  for (unsigned char byte : value) {
    result += digits[byte >> 4];
    result += digits[byte & 15];
  }
  return result;
}
}  // namespace
extern "C" {
void* tokenizers_new_from_str(const char* data, size_t size) {
  const auto config = nlohmann::json::parse(data, data + size);
  auto* inventory = new Inventory;
  const auto& tokens = config.at("test_raw_tokens");
  for (const auto& token : tokens) inventory->tokens.push_back(token);
  return inventory;
}
void tokenizers_free(void* data) { delete static_cast<Inventory*>(data); }
void tokenizers_encode(void*, const char*, size_t, int,
                       TokenizerEncodeResult*) {
  std::abort();
}
void tokenizers_free_encode_results(TokenizerEncodeResult*, size_t) {
  std::abort();
}
void tokenizers_token_to_id(void*, const char*, size_t, int32_t*) {
  std::abort();
}
void tokenizers_decode(void*, const uint32_t*, size_t, int) { std::abort(); }
void tokenizers_get_decode_str(void*, const char**, size_t*) { std::abort(); }
void tokenizers_id_to_token(void* data, uint32_t id, const char** out,
                            size_t* size) {
  const auto& token = static_cast<Inventory*>(data)->tokens.at(id);
  *out = token.data();
  *size = token.size();
}
void tokenizers_get_vocab_size(void* data, size_t* out) {
  *out = static_cast<Inventory*>(data)->tokens.size();
}
}

int main(int argc, char** argv) {
  try {
    using litert::support::HuggingFaceTokenizer;
    nlohmann::json fixture;
    if (argc == 2) {
      std::ifstream input(argv[1]);
      input >> fixture;
    } else {
      fixture = nlohmann::json::parse(
          R"({"config":{"decoder":{"type":"ByteLevel"},"added_tokens":[{"id":3,"content":"Ġ","special":true},{"id":4,"content":"Ġ","special":false}]},"tokens":[{"id":0,"raw":"fÃ©","hex":"66c3a9","special":false},{"id":1,"raw":"Ã","hex":"c3","special":false},{"id":2,"raw":"ĀĊĠ","hex":"000a20","special":false},{"id":3,"raw":"Ġ","hex":"c4a0","special":true},{"id":4,"raw":"Ġ","hex":"20","special":false}]})");
    }
    auto config = fixture["config"];
    config["test_raw_tokens"] = nlohmann::json::array();
    for (const auto& entry : fixture["tokens"])
      config["test_raw_tokens"].push_back(entry["raw"]);
    auto created = HuggingFaceTokenizer::CreateFromJson(config.dump());
    Check(created.ok(), "HF creation");
    auto tokenizer = std::move(*created);
    auto bytes = tokenizer->GetTokenBytes();
    Check(bytes.ok(), "token byte status");
    const auto raw = tokenizer->GetTokens();
    Check(bytes->size() == fixture["tokens"].size(), "all vocabulary IDs");
    for (const auto& entry : fixture["tokens"]) {
      const int id = entry["id"];
      Check(raw.at(id) == entry["raw"], "raw API retained");
      Check(Hex(bytes->at(id)) == entry["hex"], "actual HF token bytes");
      Check(tokenizer->IsSpecialToken(id) == entry["special"],
            "actual HF special ID");
    }
    litert::lm::LlGuidanceConfig llg_config;
    llg_config.eos_id = 0;
    llg_config.special_tokens = {raw.at(0)};
    auto provider =
        litert::lm::LlgConstraintProvider::Create(*tokenizer, llg_config);
    Check(provider.ok(), "actual provider creates");
    Check(captured_llg_tokens.size() == bytes->size(),
          "provider preserves IDs");
    for (size_t id = 0; id < bytes->size(); ++id) {
      const bool special = tokenizer->IsSpecialToken(id) || raw[id] == raw[0];
      const std::string expected =
          special ? std::string(1, '\xFF') + raw[id] : bytes->at(id);
      Check(captured_llg_tokens[id] == expected,
            "actual provider bytes and special prefix");
    }
    config["decoder"] = {{"type", "WordPiece"}};
    auto unsupported = HuggingFaceTokenizer::CreateFromJson(config.dump());
    Check(unsupported.ok(), "ordinary HF tokenizer still creates");
    Check((*unsupported)->GetTokenBytes().status().code() ==
              absl::StatusCode::kUnimplemented,
          "typed unsupported constrained byte status");
    Check((*unsupported)->GetTokens() == raw, "unsupported raw API retained");
    const size_t calls = llg_tokenizer_calls;
    auto refused =
        litert::lm::LlgConstraintProvider::Create(**unsupported, llg_config);
    Check(refused.status().code() == absl::StatusCode::kUnimplemented,
          "provider propagates unsupported status");
    Check(llg_tokenizer_calls == calls,
          "unsupported decoder refused before llguidance");
    std::cout << "PASS: actual patched HF source, " << bytes->size()
              << " IDs, provider byte boundary, special inventory, typed "
                 "refusal, no single-token decode\n";
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
