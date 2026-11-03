// Model-free: actual patched HF/provider sources and packaged llguidance/tokenizers.
// Only the unused C++ Constraint wrapper is replaced to expose its C handle.
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <string>
#include <vector>

#include "llguidance.h"
#include "nlohmann/json.hpp"
#include "runtime/components/constrained_decoding/llg_constraint.h"
#include "runtime/components/constrained_decoding/llg_constraint_provider.h"
#include "support/tokenizer/huggingface_tokenizer.h"

namespace {
void Check(bool value, const std::string& message) {
  if (!value) throw std::runtime_error(message);
}
std::string Read(const char* path) {
  std::ifstream input(path, std::ios::binary);
  Check(input.good(), "input file unavailable");
  return {std::istreambuf_iterator<char>(input), {}};
}
LlgMaskResult Mask(::LlgConstraint* constraint) {
  LlgMaskResult result{};
  Check(llg_compute_mask(constraint, &result) == 0, "mask error");
  return result;
}
bool Allowed(const LlgMaskResult& mask, size_t id) {
  return mask.sample_mask && ((mask.sample_mask[id / 32] >> (id % 32)) & 1);
}
void Commit(::LlgConstraint* constraint, uint32_t id) {
  LlgCommitResult result{};
  Check(llg_commit_token(constraint, id, &result) == 0, "commit error");
  Check(result.n_tokens == 1 && result.tokens[0] == id,
        "non-fast-forward commit must preserve selected ID");
}
bool Replay(::LlgConstraint* constraint, const std::vector<std::string>& bytes,
            const std::string& text, bool complete) {
  size_t pos = 0;
  while (pos < text.size()) {
    const auto mask = Mask(constraint);
    size_t longest = 0;
    uint32_t chosen = 0;
    for (size_t id = 0; id < bytes.size(); ++id) {
      if (Allowed(mask, id) && bytes[id].size() > longest &&
          text.compare(pos, bytes[id].size(), bytes[id]) == 0) {
        longest = bytes[id].size();
        chosen = id;
      }
    }
    if (!longest) return false;
    Commit(constraint, chosen);
    pos += longest;
  }
  return !complete || Mask(constraint).is_stop;
}
}  // namespace

int main(int argc, char** argv) {
  try {
    Check(argc == 4, "expected tokenizer JSON, unchanged schema, retained output");
    const auto tokenizer_json = Read(argv[1]);
    auto created = litert::support::HuggingFaceTokenizer::CreateFromJson(tokenizer_json);
    Check(created.ok(), "actual HF tokenizer creation");
    auto tokenizer = std::move(*created);
    auto token_bytes = tokenizer->GetTokenBytes();
    Check(token_bytes.ok(), "actual HF vocabulary bytes");
    const auto raw = tokenizer->GetTokens();
    uint32_t eos = 0, space = 0, null_id = 0, true_id = 0, false_id = 0;
    for (size_t id = 0; id < raw.size(); ++id) {
      if (raw[id] == "<|im_end|>") eos = id;
      if (token_bytes->at(id) == " ") space = id;
      if (token_bytes->at(id) == "null") null_id = id;
      if (token_bytes->at(id) == "true") true_id = id;
      if (token_bytes->at(id) == "false") false_id = id;
      if (tokenizer->IsSpecialToken(id))
        token_bytes->at(id) = std::string(1, '\xff') + raw[id];
    }
    Check(eos && space && null_id && true_id && false_id, "supported vocabulary controls");
    litert::lm::LlGuidanceConfig config;
    config.eos_id = eos;
    auto provider = litert::lm::LlgConstraintProvider::Create(*tokenizer, config);
    Check(provider.ok(), "actual provider creation");
    auto New = [&](const std::string& schema) {
      auto wrapper = (*provider)->CreateConstraint(litert::lm::LlGuidanceConstraintArg{
          litert::lm::LlgConstraintType::kJsonSchema, schema});
      Check(wrapper.ok(), "actual provider grammar creation");
      auto* result = litert::lm::captured_created_constraint;
      Check(result && !llg_get_error(result), "captured actual llguidance handle");
      return result;
    };
    const auto schema = Read(argv[2]);
    const auto observed = Read(argv[3]);
    const auto offset = observed.find("\"empty\":");
    Check(offset != std::string::npos, "retained missing-null prefix");
    const auto prefix = observed.substr(0, offset + 8);
    auto* bounded = New(schema);
    Check(Replay(bounded, *token_bytes, prefix, false), "fixed Unicode prefix");
    for (int index = 0; index < 8; ++index) {
      const auto mask = Mask(bounded);
      Check(Allowed(mask, space) && Allowed(mask, null_id),
            "whitespace and progress coexist before limit");
      Commit(bounded, space);
    }
    const auto capped = Mask(bounded);
    Check(!Allowed(capped, space) && Allowed(capped, null_id),
          "ninth whitespace disallowed while null remains allowed");
    Check(!Allowed(capped, true_id) && !Allowed(capped, false_id) &&
              !Allowed(capped, eos), "required null type and completion enforced");
    Check(Replay(bounded, *token_bytes, "null}", true), "typed Unicode completion");
    llg_free_constraint(bounded);
    auto* rejected = New(schema);
    Check(!Replay(rejected, *token_bytes, observed + "null}", true),
          "retained whitespace loop is blocked by default");
    llg_free_constraint(rejected);
    auto explicit_schema = nlohmann::ordered_json::parse(schema);
    explicit_schema["x-guidance"] = {{"whitespace_flexible", true}};
    auto* unbounded = New(explicit_schema.dump());
    Check(Replay(unbounded, *token_bytes, observed + "null}", true),
          "explicit unbounded caller setting retained");
    llg_free_constraint(unbounded);
    const std::string literal = "日本" + std::string(20, ' ') + "😊";
    const auto literal_schema = nlohmann::ordered_json{{"type", "string"}, {"const", literal}};
    auto* strings = New(literal_schema.dump());
    Check(Replay(strings, *token_bytes, nlohmann::json(literal).dump(), true),
          "literal Unicode and long string whitespace preserved");
    llg_free_constraint(strings);
    std::cout << "PASS: actual provider, HF tokenizer and packaged llguidance; bound8, "
                 "progress, strict null, observed-loop rejection, explicit override, "
                 "literal Unicode/string whitespace; no weights loaded\n";
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
