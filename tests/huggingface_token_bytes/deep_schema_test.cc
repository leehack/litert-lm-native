// A separate process makes native stack exhaustion an observable test failure.
// This loads only a tokenizer and grammar; no model weights or inference APIs.
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <string>

#include "llguidance.h"
#include "runtime/components/constrained_decoding/llg_constraint_provider.h"
#include "support/tokenizer/huggingface_tokenizer.h"

int main(int argc, char** argv) {
  try {
    if (argc != 4) throw std::runtime_error("tokenizer, depth and not/allof required");
    std::ifstream input(argv[1], std::ios::binary);
    if (!input) throw std::runtime_error("tokenizer unavailable");
    const std::string json{std::istreambuf_iterator<char>(input), {}};
    auto tokenizer = litert::support::HuggingFaceTokenizer::CreateFromJson(json);
    if (!tokenizer.ok()) throw std::runtime_error(tokenizer.status().ToString());
    litert::lm::LlGuidanceConfig config;
    const auto raw = (*tokenizer)->GetTokens();
    for (size_t id = 0; id < raw.size(); ++id)
      if (raw[id] == "<|im_end|>") config.eos_id = id;
    auto provider = litert::lm::LlgConstraintProvider::Create(**tokenizer, config);
    if (!provider.ok()) throw std::runtime_error(provider.status().ToString());
    const size_t depth = std::stoul(argv[2]);
    if (depth < 128 || depth > 200000) throw std::runtime_error("depth out of test range");
    const bool arrays = std::string(argv[3]) == "allof";
    if (!arrays && std::string(argv[3]) != "not") throw std::runtime_error("unknown case");
    std::string schema;
    schema.reserve(depth * 12 + 2);
    for (size_t index = 0; index < depth; ++index)
      schema += arrays ? R"({"allOf":[)" : R"({"not":)";
    schema += "{}";
    for (size_t index = 0; index < depth; ++index) schema += arrays ? "]}" : "}";
    std::cout << "DEEP_SCHEMA_BEGIN depth=" << depth << " kind=" << argv[3]
              << " bytes=" << schema.size() << '\n' << std::flush;
    auto constraint = (*provider)->CreateConstraint(litert::lm::LlGuidanceConstraintArg{
        litert::lm::LlgConstraintType::kJsonSchema, schema});
    std::cout << constraint.status().ToString() << '\n';
    if (constraint.ok() || constraint.status().code() != absl::StatusCode::kInternal ||
        constraint.status().message().find("recursion limit exceeded") == std::string::npos)
      throw std::runtime_error("deep schema must return existing controlled native error");
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
