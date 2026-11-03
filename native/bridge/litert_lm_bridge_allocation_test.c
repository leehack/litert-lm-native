#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

static unsigned fail_mask;
static unsigned copy_calls;
static void *copies[2];
static unsigned outstanding;
static void *proxy;

static void *controlled_malloc(size_t size) {
  unsigned index = copy_calls++;
  assert(index < 2);
  if ((fail_mask & (1u << index)) != 0) return NULL;
  void *result = malloc(size);
  assert(result != NULL);
  copies[index] = result;
  ++outstanding;
  return result;
}

static void controlled_free(void *pointer) {
  if (pointer == NULL) return;
  if (pointer == proxy) {
    proxy = NULL;
  } else {
    unsigned index = pointer == copies[0] ? 0 : 1;
    assert(pointer == copies[index]);
    copies[index] = NULL;
    assert(outstanding > 0);
    --outstanding;
  }
  free(pointer);
}

#define malloc controlled_malloc
#define free controlled_free
#include "litert_lm_bridge.c"
#undef malloc
#undef free

#if defined(LITERT_LM_STREAM_CHUNK_API)
struct LiteRtLmStreamChunk {
  const char *text;
  const char *error;
  bool final;
  int reason;
};
#if defined(LITERT_LM_C_API_V1)
int litert_lm_stream_chunk_get_text(const LiteRtLmStreamChunk *c, const char **out) {
  *out = c->text;
  return 0;
}
int litert_lm_stream_chunk_get_error(const LiteRtLmStreamChunk *c, const char **out) {
  *out = c->error;
  return 0;
}
int litert_lm_stream_chunk_is_final(const LiteRtLmStreamChunk *c, bool *out) {
  *out = c->final;
  return 0;
}
#else
const char *litert_lm_stream_chunk_get_text(const LiteRtLmStreamChunk *c) {
  return c->text;
}
const char *litert_lm_stream_chunk_get_error(const LiteRtLmStreamChunk *c) {
  return c->error;
}
bool litert_lm_stream_chunk_is_final(const LiteRtLmStreamChunk *c) {
  return c->final;
}
#endif
#if defined(LITERT_LM_FINISH_REASON_API)
int litert_lm_native_stream_chunk_get_finish_reason(const LiteRtLmStreamChunk *c) {
  return c->reason;
}
#endif
#endif

static unsigned callbacks;
static unsigned finals;
static bool expected_final;
static int expected_failure;
static const char *expected_text;
static const char *expected_error;
static int expected_reason;

static void capture(void *data, char *text, bool final, char *error) {
  assert(data == &callbacks);
  ++callbacks;
  finals += final;
  assert(final == expected_final);
  assert(stream_proxy_has_allocation_failure(proxy) == expected_failure);
  assert(stream_proxy_get_finish_reason(proxy) == expected_reason);
  assert((text == NULL) == (expected_text == NULL));
  assert((error == NULL) == (expected_error == NULL));
  if (text != NULL) {
    assert(text != expected_text);
    assert(strcmp(text, expected_text) == 0);
  }
  if (error != NULL) {
    assert(error != expected_error);
    assert(strcmp(error, expected_error) == 0);
  }
  stream_proxy_free_string(text);
  stream_proxy_free_string(error);
  assert(outstanding == 0);
}

static void deliver(stream_proxy_upstream_callback_t callback,
                    const char *text, const char *error, bool final) {
  copy_calls = 0;
#if defined(LITERT_LM_FINISH_REASON_API)
  expected_reason = final ? 1 : 0;
#else
  expected_reason = 0;
#endif
  expected_final = final;
#if defined(LITERT_LM_STREAM_CHUNK_API)
  const LiteRtLmStreamChunk chunk = {text, error, final, 1};
  callback(proxy, &chunk);
#else
  callback(proxy, (char *)text, final, (char *)error);
#endif
}

int main(void) {
  assert(stream_proxy_allocation_failure_abi_version() == 1);
  assert(stream_proxy_has_allocation_failure(NULL) == 1);
#if defined(LITERT_LM_STREAM_CHUNK_API)
  assert(stream_proxy_callback_abi_version() == 2);
#else
  assert(stream_proxy_callback_abi_version() == 1);
#endif
  for (unsigned mask = 0; mask < 4; ++mask) {
    for (unsigned final = 0; final < 2; ++final) {
      stream_proxy_upstream_callback_t callback = NULL;
      proxy = stream_proxy_create(capture, &callbacks, &callback);
      assert(proxy != NULL && callback != NULL);
      assert(stream_proxy_has_allocation_failure(proxy) == 0);
      callbacks = finals = 0;
      fail_mask = mask;
      expected_failure = mask != 0;
      expected_text = (mask & 1) ? NULL : "payload";
      expected_error = (mask & 2) ? NULL : "native failure";
      deliver(callback, "payload", "native failure", final != 0);
      assert(copy_calls == 2);
      assert(callbacks == 1 && finals == final);
      assert(stream_proxy_has_allocation_failure(proxy) == expected_failure);
      fail_mask = 3;
      expected_text = expected_error = NULL;
      deliver(callback, NULL, NULL, true);
      assert(copy_calls == 0);
      assert(callbacks == 2 && finals == final + 1);
      assert(stream_proxy_has_allocation_failure(proxy) == expected_failure);
      assert(outstanding == 0);
      stream_proxy_delete(proxy);
      assert(proxy == NULL);
    }
  }
  return 0;
}
