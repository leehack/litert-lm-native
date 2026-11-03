// Capture the byte-exact tokenizer-init boundary of production provider code.
// This seam does not emulate llguidance grammar execution.
#pragma once
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>
struct LlgTokenizer {};
struct LlgConstraint {};
struct LlgConstraintInit {};
struct LlgTokenizerInit {
  uint32_t vocab_size;
  uint32_t tok_eos;
  const uint32_t* token_lens;
  const uint8_t* token_bytes;
  bool tokenize_assumes_string;
  size_t (*tokenize_fn)(const void*, const uint8_t*, size_t, uint32_t*, size_t);
  const void* tokenize_user_data;
};
inline std::vector<std::string> captured_llg_tokens;
inline size_t llg_tokenizer_calls = 0;
inline bool captured_tokenize_assumes_string = false;
inline LlgTokenizer* llg_new_tokenizer(const LlgTokenizerInit* init, char*,
                                       size_t) {
  ++llg_tokenizer_calls;
  captured_tokenize_assumes_string = init->tokenize_assumes_string;
  captured_llg_tokens.clear();
  const auto* data = init->token_bytes;
  for (uint32_t id = 0; id < init->vocab_size; ++id) {
    captured_llg_tokens.emplace_back(reinterpret_cast<const char*>(data),
                                     init->token_lens[id]);
    data += init->token_lens[id];
  }
  return new LlgTokenizer;
}
inline void llg_free_tokenizer(LlgTokenizer* tokenizer) { delete tokenizer; }
inline LlgConstraint* llg_new_constraint_regex(LlgConstraintInit*,
                                               const char*) {
  return nullptr;
}
inline LlgConstraint* llg_new_constraint_json(LlgConstraintInit*, const char*) {
  return nullptr;
}
inline LlgConstraint* llg_new_constraint_lark(LlgConstraintInit*, const char*) {
  return nullptr;
}
inline LlgConstraint* llg_new_constraint(LlgConstraintInit*, const char*) {
  return nullptr;
}
inline void llg_constraint_init_set_defaults(LlgConstraintInit*,
                                             LlgTokenizer*) {}
inline const char* llg_get_error(LlgConstraint*) { return nullptr; }
inline void llg_free_constraint(LlgConstraint*) {}
