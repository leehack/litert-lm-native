#include <stdbool.h>
#include <stddef.h>
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
int stream_proxy_callback_abi_version(void);

typedef struct callback_result {
  char *chunk;
  bool is_final;
  char *error;
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

  callback_result_t result = {0};
  stream_proxy_upstream_callback_t proxy_callback = NULL;
  void *proxy_data = stream_proxy_create(
      capture_callback,
      &result,
      &proxy_callback);
  if (proxy_data == NULL || proxy_callback == NULL) {
    return 10;
  }

#if defined(LITERT_LM_STREAM_CHUNK_API)
  const LiteRtLmStreamChunk chunk = {
      .text = "hello",
      .is_final = true,
      .error = "test-error",
  };
  proxy_callback(proxy_data, &chunk);
#else
  proxy_callback(proxy_data, "hello", true, "test-error");
#endif

  int status = validate_result(&result, "hello", true, "test-error");
  stream_proxy_delete(proxy_data);
  return status;
}
