#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

typedef void (*stream_proxy_dart_callback_t)(
    void *callback_data,
    char *chunk,
    bool is_final,
    char *error_message);

#if defined(LITERT_LM_STREAM_CHUNK_API)
typedef struct LiteRtLmStreamChunk {
  const char *text;
  bool is_final;
  const char *error;
  int finish_reason;
} LiteRtLmStreamChunk;

const char *litert_lm_stream_chunk_get_text(
    const LiteRtLmStreamChunk *chunk) {
  return chunk == NULL ? NULL : chunk->text;
}

bool litert_lm_stream_chunk_is_final(const LiteRtLmStreamChunk *chunk) {
  return chunk != NULL && chunk->is_final;
}

const char *litert_lm_stream_chunk_get_error(
    const LiteRtLmStreamChunk *chunk) {
  return chunk == NULL ? NULL : chunk->error;
}

#if defined(LITERT_LM_FINISH_REASON_API)
int litert_lm_native_stream_chunk_get_finish_reason(
    const LiteRtLmStreamChunk *chunk) {
  return chunk == NULL ? 0 : chunk->finish_reason;
}
#endif

typedef void (*stream_proxy_upstream_callback_t)(
    void *callback_data,
    const LiteRtLmStreamChunk *chunk);
#else
typedef stream_proxy_dart_callback_t stream_proxy_upstream_callback_t;
#endif

void *stream_proxy_create(
    stream_proxy_dart_callback_t dart_callback,
    void *dart_data,
    stream_proxy_upstream_callback_t *out_proxy_callback);
void stream_proxy_delete(void *callback_data);
void stream_proxy_free_string(char *value);
int32_t stream_proxy_callback_abi_version(void);
int32_t stream_proxy_finish_reason_abi_version(void);
int32_t stream_proxy_get_finish_reason(const void *callback_data);

typedef struct callback_result {
  char *chunk;
  bool is_final;
  char *error;
  const void *proxy_data;
  int32_t finish_reason_in_callback;
} callback_result_t;

static void capture_callback(
    void *callback_data,
    char *chunk,
    bool is_final,
    char *error_message) {
  callback_result_t *result = (callback_result_t *)callback_data;
  result->chunk = chunk;
  result->is_final = is_final;
  result->error = error_message;
  result->finish_reason_in_callback =
      stream_proxy_get_finish_reason(result->proxy_data);
}

static int validate_result(
    callback_result_t *result,
    const char *chunk,
    bool is_final,
    const char *error) {
  if (result->is_final != is_final) {
    return 1;
  }
  if ((result->chunk == NULL) != (chunk == NULL)) {
    return 2;
  }
  if (chunk != NULL && strcmp(result->chunk, chunk) != 0) {
    return 3;
  }
  if ((result->error == NULL) != (error == NULL)) {
    return 4;
  }
  if (error != NULL && strcmp(result->error, error) != 0) {
    return 5;
  }
  stream_proxy_free_string(result->chunk);
  stream_proxy_free_string(result->error);
  return 0;
}

static void *create_proxy(
    callback_result_t *result,
    stream_proxy_upstream_callback_t *proxy_callback) {
  memset(result, 0, sizeof(*result));
  *proxy_callback = NULL;
  void *proxy_data = stream_proxy_create(
      capture_callback,
      result,
      proxy_callback);
  result->proxy_data = proxy_data;
  return proxy_data;
}

#if defined(LITERT_LM_STREAM_CHUNK_API)
// Streams a text chunk and then a final chunk, both carrying `wire_reason`.
// Returns the reported finish reason, which must already be visible inside
// the final callback, or a negative failure code.
static int32_t final_finish_reason(int wire_reason, bool is_error) {
  callback_result_t result;
  stream_proxy_upstream_callback_t proxy_callback;
  void *proxy_data = create_proxy(&result, &proxy_callback);
  if (proxy_data == NULL || proxy_callback == NULL) {
    return -100;
  }

  const LiteRtLmStreamChunk text = {
      .text = "partial",
      .is_final = false,
      .error = NULL,
      .finish_reason = wire_reason,
  };
  proxy_callback(proxy_data, &text);
  int32_t before_final = stream_proxy_get_finish_reason(proxy_data);
  int status = validate_result(&result, "partial", false, NULL);

  const char *error = is_error ? "CANCELLED: Task cancelled" : NULL;
  const LiteRtLmStreamChunk final = {
      .text = NULL,
      .is_final = true,
      .error = error,
      .finish_reason = wire_reason,
  };
  proxy_callback(proxy_data, &final);
  int32_t after_final = stream_proxy_get_finish_reason(proxy_data);
  if (status == 0) {
    status = validate_result(&result, NULL, true, error);
  }
  int32_t in_callback = result.finish_reason_in_callback;
  stream_proxy_delete(proxy_data);

  if (status != 0) {
    return -200 - status;
  }
  if (before_final != 0) {
    return -300;
  }
  if (in_callback != after_final) {
    return -400;
  }
  return after_final;
}
#endif

static int check_finish_reasons(void) {
  if (stream_proxy_get_finish_reason(NULL) != 0) {
    return 20;
  }
#if defined(LITERT_LM_FINISH_REASON_API)
  if (stream_proxy_finish_reason_abi_version() != 1) {
    return 21;
  }
  static const struct {
    int wire_reason;
    bool is_error;
    int32_t expected;
  } cases[] = {
      {0, false, 0},   // Unknown: no decode was reported.
      {1, false, 1},   // Stop token.
      {2, false, 2},   // Output-token budget.
      {3, false, 3},   // Context window.
      {4, true, 4},    // Cancelled.
      {5, true, 5},    // Error.
      {6, false, 0},   // Unknown future value.
      {-1, false, 0},  // Corrupt value.
  };
  for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i) {
    if (final_finish_reason(cases[i].wire_reason, cases[i].is_error) !=
        cases[i].expected) {
      return 30 + (int)i;
    }
  }
#else
  if (stream_proxy_finish_reason_abi_version() != 0) {
    return 22;
  }
#if defined(LITERT_LM_STREAM_CHUNK_API)
  // Without the runtime patch a chunk value must not leak through.
  if (final_finish_reason(2, false) != 0) {
    return 23;
  }
#endif
#endif
  return 0;
}

int main(void) {
#if defined(LITERT_LM_STREAM_CHUNK_API)
  if (stream_proxy_callback_abi_version() != 2) {
    return 9;
  }
#else
  if (stream_proxy_callback_abi_version() != 1) {
    return 9;
  }
#endif

  callback_result_t result;
  stream_proxy_upstream_callback_t proxy_callback;
  void *proxy_data = create_proxy(&result, &proxy_callback);
  if (proxy_data == NULL || proxy_callback == NULL) {
    return 10;
  }

#if defined(LITERT_LM_STREAM_CHUNK_API)
  const LiteRtLmStreamChunk chunk = {
      .text = "hello",
      .is_final = true,
      .error = "test-error",
      .finish_reason = 0,
  };
  proxy_callback(proxy_data, &chunk);
#else
  proxy_callback(proxy_data, "hello", true, "test-error");
#endif

  int status = validate_result(&result, "hello", true, "test-error");
  if (status == 0 && stream_proxy_get_finish_reason(proxy_data) != 0) {
    status = 11;
  }
  stream_proxy_delete(proxy_data);
  if (status != 0) {
    return status;
  }
  return check_finish_reasons();
}
