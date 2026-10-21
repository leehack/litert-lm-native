#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

// LiteRtLmBridge hosts downstream FFI bridge helpers. The stream_proxy_* exports
// preserve the legacy four-field callback ABI used by downstream FFI clients.
// LiteRT-LM 0.15 changed its upstream callback to an opaque stream chunk, so
// runtime builds and wrappers for 0.15+ define LITERT_LM_STREAM_CHUNK_API and
// translate that chunk back to the stable downstream callback here.
#if defined(_WIN32)
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#define LITERT_LM_BRIDGE_EXPORT __declspec(dllexport)
#else
#include <dlfcn.h>
#define LITERT_LM_BRIDGE_EXPORT __attribute__((visibility("default")))
#endif

LITERT_LM_BRIDGE_EXPORT int32_t stream_proxy_callback_abi_version(void) {
#if defined(LITERT_LM_STREAM_CHUNK_API)
  return 2;
#else
  return 1;
#endif
}

#if defined(LITERT_LM_FINISH_REASON_API) && !defined(LITERT_LM_STREAM_CHUNK_API)
#error "LITERT_LM_FINISH_REASON_API requires LITERT_LM_STREAM_CHUNK_API"
#endif

// Finish-reason wire values returned by stream_proxy_get_finish_reason.
enum {
  STREAM_PROXY_FINISH_REASON_UNKNOWN = 0,
  STREAM_PROXY_FINISH_REASON_STOP = 1,
  STREAM_PROXY_FINISH_REASON_LENGTH = 2,
  STREAM_PROXY_FINISH_REASON_CONTEXT_EXHAUSTED = 3,
  STREAM_PROXY_FINISH_REASON_CANCELLED = 4,
  STREAM_PROXY_FINISH_REASON_ERROR = 5,
};

// 0 means this runtime never reports a finish reason; consumers must not
// infer one. 1 means a conversation stream's final callback carries one.
LITERT_LM_BRIDGE_EXPORT int32_t stream_proxy_finish_reason_abi_version(void) {
#if defined(LITERT_LM_FINISH_REASON_API)
  return 1;
#else
  return 0;
#endif
}

typedef void (*stream_proxy_dart_callback_t)(
    void *callback_data,
    char *chunk,
    bool is_final,
    char *error_message);

#if defined(LITERT_LM_STREAM_CHUNK_API)
typedef struct LiteRtLmStreamChunk LiteRtLmStreamChunk;

extern const char *litert_lm_stream_chunk_get_text(
    const LiteRtLmStreamChunk *chunk);
extern bool litert_lm_stream_chunk_is_final(
    const LiteRtLmStreamChunk *chunk);
extern const char *litert_lm_stream_chunk_get_error(
    const LiteRtLmStreamChunk *chunk);
#if defined(LITERT_LM_FINISH_REASON_API)
// Defined in the runtime by stream_finish_reason.patch.
extern int litert_lm_native_stream_chunk_get_finish_reason(
    const LiteRtLmStreamChunk *chunk);
#endif

typedef void (*stream_proxy_upstream_callback_t)(
    void *callback_data,
    const LiteRtLmStreamChunk *chunk);
#else
typedef stream_proxy_dart_callback_t stream_proxy_upstream_callback_t;
#endif

typedef struct stream_proxy_context {
  stream_proxy_dart_callback_t dart_callback;
  void *dart_data;
  int32_t finish_reason;
} stream_proxy_context_t;

static char *stream_proxy_copy_string(const char *value) {
  if (value == NULL) {
    return NULL;
  }

  size_t length = strlen(value) + 1;
  char *copy = (char *)malloc(length);
  if (copy == NULL) {
    return NULL;
  }
  memcpy(copy, value, length);
  return copy;
}

#if defined(LITERT_LM_STREAM_CHUNK_API)
static void stream_proxy_forward(
    void *callback_data,
    const LiteRtLmStreamChunk *stream_chunk) {
  stream_proxy_context_t *context =
      (stream_proxy_context_t *)callback_data;
  if (context == NULL || context->dart_callback == NULL) {
    return;
  }

  const char *chunk = NULL;
  const char *error_message = NULL;
  bool is_final = false;
  if (stream_chunk != NULL) {
    chunk = litert_lm_stream_chunk_get_text(stream_chunk);
    error_message = litert_lm_stream_chunk_get_error(stream_chunk);
    is_final = litert_lm_stream_chunk_is_final(stream_chunk);
  }
#if defined(LITERT_LM_FINISH_REASON_API)
  // Stored before the final callback so a consumer reading it after that
  // callback (or after a message posted from it) observes the value.
  if (is_final) {
    int reason = litert_lm_native_stream_chunk_get_finish_reason(stream_chunk);
    context->finish_reason =
        reason >= STREAM_PROXY_FINISH_REASON_UNKNOWN &&
                reason <= STREAM_PROXY_FINISH_REASON_ERROR
            ? reason
            : STREAM_PROXY_FINISH_REASON_UNKNOWN;
  }
#endif

  char *chunk_copy = stream_proxy_copy_string(chunk);
  char *error_copy = stream_proxy_copy_string(error_message);
  context->dart_callback(
      context->dart_data,
      chunk_copy,
      is_final,
      error_copy);
}
#else
static void stream_proxy_forward(
    void *callback_data,
    char *chunk,
    bool is_final,
    char *error_message) {
  stream_proxy_context_t *context =
      (stream_proxy_context_t *)callback_data;
  if (context == NULL || context->dart_callback == NULL) {
    return;
  }

  char *chunk_copy = stream_proxy_copy_string(chunk);
  char *error_copy = stream_proxy_copy_string(error_message);
  context->dart_callback(
      context->dart_data,
      chunk_copy,
      is_final,
      error_copy);
}
#endif

LITERT_LM_BRIDGE_EXPORT void *stream_proxy_load_global(const char *path) {
  if (path == NULL) {
    return NULL;
  }

#if defined(_WIN32)
  return (void *)LoadLibraryA(path);
#else
  return dlopen(path, RTLD_NOW | RTLD_GLOBAL);
#endif
}

LITERT_LM_BRIDGE_EXPORT void *stream_proxy_create(
    stream_proxy_dart_callback_t dart_callback,
    void *dart_data,
    stream_proxy_upstream_callback_t *out_proxy_callback) {
  if (dart_callback == NULL || out_proxy_callback == NULL) {
    return NULL;
  }

  stream_proxy_context_t *context =
      (stream_proxy_context_t *)calloc(1, sizeof(stream_proxy_context_t));
  if (context == NULL) {
    return NULL;
  }

  context->dart_callback = dart_callback;
  context->dart_data = dart_data;
  *out_proxy_callback = stream_proxy_forward;
  return context;
}

// Returns the finish reason recorded by the latest final callback on this
// proxy. A fresh proxy, a NULL context or ABI version 0 returns UNKNOWN; a
// reused proxy keeps the previous turn's value until the next final callback.
// A turn whose final callback races another message sent on the same
// conversation may report UNKNOWN.
LITERT_LM_BRIDGE_EXPORT int32_t stream_proxy_get_finish_reason(
    const void *callback_data) {
  if (callback_data == NULL) {
    return STREAM_PROXY_FINISH_REASON_UNKNOWN;
  }
  return ((const stream_proxy_context_t *)callback_data)->finish_reason;
}

LITERT_LM_BRIDGE_EXPORT void stream_proxy_delete(void *callback_data) {
  free(callback_data);
}

LITERT_LM_BRIDGE_EXPORT void stream_proxy_free_string(char *value) {
  free(value);
}
