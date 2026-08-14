#include "bridge/litert_lm_asr_bridge.h"

#include <stddef.h>
#include <stdint.h>

int main(void) {
  LitertLmAsrConfig config;
  litert_lm_asr_config_init(&config);
  if (litert_lm_asr_abi_version() != LITERT_LM_ASR_ABI_VERSION ||
      litert_lm_asr_config_size() != sizeof(LitertLmAsrConfig) ||
      litert_lm_asr_result_size() != sizeof(LitertLmAsrResult) ||
      config.struct_size != sizeof(LitertLmAsrConfig) ||
      config.abi_version != LITERT_LM_ASR_ABI_VERSION ||
      config.sample_rate_hz != 16000 || config.num_channels != 1) {
    return 1;
  }
  if (litert_lm_asr_config_init_for_model_preset(
          &config, LITERT_LM_ASR_MODEL_PRESET_MOONSHINE_TINY) !=
          LITERT_LM_ASR_STATUS_OK ||
      config.decoder_type != LITERT_LM_ASR_DECODER_STATELESS ||
      config.decode_start_token_id != 1 || config.decode_stop_token_id != 2) {
    return 3;
  }
  if (litert_lm_asr_config_init_for_model_preset(
          &config, LITERT_LM_ASR_MODEL_PRESET_PARAKEET_TDT_0_6B_V3) !=
          LITERT_LM_ASR_STATUS_OK ||
      config.decoder_type != LITERT_LM_ASR_DECODER_TDT ||
      config.log_mel_n_mels != 128 || config.decode_start_token_id != 8192) {
    return 4;
  }
  if (litert_lm_asr_config_init_for_model_preset(
          &config, LITERT_LM_ASR_MODEL_PRESET_PARAKEET_CTC_0_6B) !=
          LITERT_LM_ASR_STATUS_OK ||
      config.decoder_type != LITERT_LM_ASR_DECODER_CTC ||
      config.log_mel_transpose != 1) {
    return 5;
  }
  if (litert_lm_asr_config_init_for_model_preset(
          &config, LITERT_LM_ASR_MODEL_PRESET_WHISPER_TINY) !=
          LITERT_LM_ASR_STATUS_OK ||
      config.input_milliseconds != 30000 ||
      config.log_mel_norm_type != LITERT_LM_ASR_LOG_MEL_NORM_WHISPER ||
      config.decode_stop_token_id != 50257) {
    return 6;
  }
  if (litert_lm_asr_config_init_for_model_preset(
          &config, LITERT_LM_ASR_MODEL_PRESET_QWEN3_ASR_0_6B) !=
          LITERT_LM_ASR_STATUS_OK ||
      config.log_mel_n_mels != 128 ||
      config.decode_skip_until_token_id != 151704) {
    return 7;
  }
  if (litert_lm_asr_config_init_for_model_preset(&config,
                                                 (LitertLmAsrModelPreset)999) !=
      LITERT_LM_ASR_STATUS_INVALID_ARGUMENT) {
    return 8;
  }

  LitertLmAsrResult result;
  litert_lm_asr_result_init(&result);
  if (result.struct_size != sizeof(LitertLmAsrResult) ||
      result.confirmed_text != NULL || result.unconfirmed_text != NULL ||
      result.is_final != 0) {
    return 2;
  }
  litert_lm_asr_result_release(&result);
  return 0;
}
