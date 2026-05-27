#include <stdbool.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>

#if defined(_WIN32)
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#define STREAM_PROXY_EXPORT __declspec(dllexport)
#else
#include <dlfcn.h>
#define STREAM_PROXY_EXPORT __attribute__((visibility("default")))
#endif

typedef void (*stream_proxy_callback_t)(
    void *callback_data,
    char *chunk,
    bool is_final,
    char *error_message);

typedef struct stream_proxy_context {
  stream_proxy_callback_t dart_callback;
  void *dart_data;
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

STREAM_PROXY_EXPORT void *stream_proxy_load_global(const char *path) {
  if (path == NULL) {
    return NULL;
  }

#if defined(_WIN32)
  return (void *)LoadLibraryA(path);
#else
  return dlopen(path, RTLD_NOW | RTLD_GLOBAL);
#endif
}

STREAM_PROXY_EXPORT void *stream_proxy_create(
    stream_proxy_callback_t dart_callback,
    void *dart_data,
    stream_proxy_callback_t *out_proxy_callback) {
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

STREAM_PROXY_EXPORT void stream_proxy_delete(void *callback_data) {
  free(callback_data);
}

STREAM_PROXY_EXPORT void stream_proxy_free_string(char *value) {
  free(value);
}
