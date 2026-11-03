// Test C ABI: raw token inventory only. Any decode attempt fails the control.
#pragma once
#include <cstddef>
#include <cstdint>
struct TokenizerEncodeResult {
  uint32_t* token_ids;
  size_t len;
};
extern "C" {
void* tokenizers_new_from_str(const char*, size_t);
void tokenizers_free(void*);
void tokenizers_encode(void*, const char*, size_t, int, TokenizerEncodeResult*);
void tokenizers_free_encode_results(TokenizerEncodeResult*, size_t);
void tokenizers_token_to_id(void*, const char*, size_t, int32_t*);
void tokenizers_decode(void*, const uint32_t*, size_t, int);
void tokenizers_get_decode_str(void*, const char**, size_t*);
void tokenizers_id_to_token(void*, uint32_t, const char**, size_t*);
void tokenizers_get_vocab_size(void*, size_t*);
}
