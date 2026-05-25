#include "litert_lm_c_api.h"

#include <cstring>

namespace {

char* dup_string(const char* value) {
  if (value == nullptr) {
    return nullptr;
  }
  const size_t length = std::strlen(value);
  char* copy = new char[length + 1];
  std::memcpy(copy, value, length + 1);
  return copy;
}

litert_lm_status unsupported(char** out_error) {
  if (out_error != nullptr) {
    *out_error = dup_string(
        "litert-lm-native C shim is scaffolded but not linked to upstream "
        "LiteRT-LM yet");
  }
  return LITERT_LM_STATUS_UNSUPPORTED;
}

}  // namespace

extern "C" {

const char* litert_lm_native_version(void) { return "0.1.0-dev"; }

litert_lm_status litert_lm_engine_create(
    const litert_lm_engine_options* options,
    litert_lm_engine** out_engine,
    char** out_error) {
  if (options == nullptr || options->model_path == nullptr ||
      out_engine == nullptr) {
    if (out_error != nullptr) {
      *out_error = dup_string("model_path and out_engine are required");
    }
    return LITERT_LM_STATUS_INVALID_ARGUMENT;
  }
  *out_engine = nullptr;
  return unsupported(out_error);
}

void litert_lm_engine_destroy(litert_lm_engine* engine) { (void)engine; }

litert_lm_status litert_lm_conversation_create(
    litert_lm_engine* engine,
    const litert_lm_sampler_options* sampler_options,
    litert_lm_conversation** out_conversation,
    char** out_error) {
  (void)sampler_options;
  if (engine == nullptr || out_conversation == nullptr) {
    if (out_error != nullptr) {
      *out_error = dup_string("engine and out_conversation are required");
    }
    return LITERT_LM_STATUS_INVALID_ARGUMENT;
  }
  *out_conversation = nullptr;
  return unsupported(out_error);
}

void litert_lm_conversation_destroy(litert_lm_conversation* conversation) {
  (void)conversation;
}

litert_lm_status litert_lm_conversation_generate_stream(
    litert_lm_conversation* conversation,
    const char* user_message_json,
    litert_lm_stream_callback callback,
    void* user_data,
    char** out_error) {
  (void)user_message_json;
  (void)callback;
  (void)user_data;
  if (conversation == nullptr) {
    if (out_error != nullptr) {
      *out_error = dup_string("conversation is required");
    }
    return LITERT_LM_STATUS_INVALID_ARGUMENT;
  }
  return unsupported(out_error);
}

void litert_lm_conversation_cancel(litert_lm_conversation* conversation) {
  (void)conversation;
}

litert_lm_status litert_lm_conversation_get_benchmark_metrics(
    litert_lm_conversation* conversation,
    litert_lm_benchmark_metrics* out_metrics,
    char** out_error) {
  if (conversation == nullptr || out_metrics == nullptr) {
    if (out_error != nullptr) {
      *out_error = dup_string("conversation and out_metrics are required");
    }
    return LITERT_LM_STATUS_INVALID_ARGUMENT;
  }
  return unsupported(out_error);
}

void litert_lm_string_free(char* value) { delete[] value; }

}  // extern "C"
