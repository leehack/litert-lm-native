#ifndef LITERT_LM_NATIVE_BRIDGE_LITERT_LM_ASR_OMNI_ENGINE_H_
#define LITERT_LM_NATIVE_BRIDGE_LITERT_LM_ASR_OMNI_ENGINE_H_

#include <memory>

#include "absl/status/statusor.h"
#include "bridge/litert_lm_asr_bridge.h"
#include "omni/omni_session.h"

namespace litert_lm_native {

// Maps a validated ABI version 1 config onto upstream's ASR session factories.
// `.litertlm` containers use the Omni registry; other paths are plain TFLite
// models with a separate tokenizer, which the registry does not accept.
absl::StatusOr<std::unique_ptr<::litert::omni::OmniSessionFactory>>
CreateAsrSessionFactory(const LitertLmAsrConfig &config);

} // namespace litert_lm_native

#endif // LITERT_LM_NATIVE_BRIDGE_LITERT_LM_ASR_OMNI_ENGINE_H_
