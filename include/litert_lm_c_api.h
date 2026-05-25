#ifndef LITERT_LM_NATIVE_LITERT_LM_C_API_H_
#define LITERT_LM_NATIVE_LITERT_LM_C_API_H_

#include <stddef.h>
#include <stdint.h>

#ifdef _WIN32
#ifdef LITERT_LM_NATIVE_BUILDING_LIBRARY
#define LITERT_LM_API __declspec(dllexport)
#else
#define LITERT_LM_API __declspec(dllimport)
#endif
#else
#define LITERT_LM_API __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

typedef struct litert_lm_engine litert_lm_engine;
typedef struct litert_lm_conversation litert_lm_conversation;

typedef enum litert_lm_status {
  LITERT_LM_STATUS_OK = 0,
  LITERT_LM_STATUS_INVALID_ARGUMENT = 1,
  LITERT_LM_STATUS_UNSUPPORTED = 2,
  LITERT_LM_STATUS_INTERNAL_ERROR = 3,
  LITERT_LM_STATUS_CANCELLED = 4,
} litert_lm_status;

typedef enum litert_lm_backend {
  LITERT_LM_BACKEND_AUTO = 0,
  LITERT_LM_BACKEND_CPU = 1,
  LITERT_LM_BACKEND_GPU = 2,
  LITERT_LM_BACKEND_NPU = 3,
} litert_lm_backend;

typedef struct litert_lm_engine_options {
  const char* model_path;
  const char* cache_dir;
  litert_lm_backend backend;
  int32_t max_tokens;
  int32_t output_tokens;
  int32_t prefill_tokens;
  int32_t enable_benchmark;
  int32_t enable_speculative_decoding;
} litert_lm_engine_options;

typedef struct litert_lm_sampler_options {
  float temperature;
  int32_t top_k;
  float top_p;
  int32_t seed;
} litert_lm_sampler_options;

typedef struct litert_lm_benchmark_metrics {
  int32_t input_tokens;
  int32_t output_tokens;
  double time_to_first_token_seconds;
  double init_seconds;
  double prefill_tokens_per_second;
  double decode_tokens_per_second;
} litert_lm_benchmark_metrics;

typedef void (*litert_lm_stream_callback)(
    void* user_data,
    const char* utf8_chunk,
    int32_t is_final,
    const char* error_message);

LITERT_LM_API const char* litert_lm_native_version(void);

LITERT_LM_API litert_lm_status litert_lm_engine_create(
    const litert_lm_engine_options* options,
    litert_lm_engine** out_engine,
    char** out_error);

LITERT_LM_API void litert_lm_engine_destroy(litert_lm_engine* engine);

LITERT_LM_API litert_lm_status litert_lm_conversation_create(
    litert_lm_engine* engine,
    const litert_lm_sampler_options* sampler_options,
    litert_lm_conversation** out_conversation,
    char** out_error);

LITERT_LM_API void litert_lm_conversation_destroy(
    litert_lm_conversation* conversation);

LITERT_LM_API litert_lm_status litert_lm_conversation_generate_stream(
    litert_lm_conversation* conversation,
    const char* user_message_json,
    litert_lm_stream_callback callback,
    void* user_data,
    char** out_error);

LITERT_LM_API void litert_lm_conversation_cancel(
    litert_lm_conversation* conversation);

LITERT_LM_API litert_lm_status litert_lm_conversation_get_benchmark_metrics(
    litert_lm_conversation* conversation,
    litert_lm_benchmark_metrics* out_metrics,
    char** out_error);

LITERT_LM_API void litert_lm_string_free(char* value);

#ifdef __cplusplus
}
#endif

#endif  // LITERT_LM_NATIVE_LITERT_LM_C_API_H_
