#ifndef LITERT_LM_BRIDGE_H_
#define LITERT_LM_BRIDGE_H_

#include <stdint.h>

#if defined(_WIN32)
#define LITERT_LM_BRIDGE_EXPORT __declspec(dllexport)
#else
#define LITERT_LM_BRIDGE_EXPORT __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

// Version 1 exposes a sticky, allocation-free copy-failure status independently
// of the callback ABI and native finish reason. Missing/unknown versions cannot
// establish lossless callback delivery.
LITERT_LM_BRIDGE_EXPORT int32_t stream_proxy_allocation_failure_abi_version(void);

// Returns 1 if any non-NULL text/error failed to copy, otherwise 0. Set before
// forwarding the affected callback; never reset, including on a clean final.
// NULL returns 1 (fail closed). A non-NULL argument must be a live proxy from
// stream_proxy_create. Read after the actual final callback and callback drain,
// before stream_proxy_delete; deletion must not race a read or callback.
// Strings delivered by callbacks retain stream_proxy_free_string ownership.
LITERT_LM_BRIDGE_EXPORT int32_t stream_proxy_has_allocation_failure(
    const void *callback_data);

#ifdef __cplusplus
}
#endif

#endif  // LITERT_LM_BRIDGE_H_
