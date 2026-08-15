#include "bridge/litert_lm_asr_bridge.h"

#include <cmath>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <memory>
#include <mutex>
#include <new>
#include <string>
#include <utility>

#include "absl/status/status.h"
#include "absl/status/statusor.h"
#include "bridge/litert_lm_asr_audio_source.h"
#include "omni/asr/asr_engine.h"
#include "omni/asr/asr_session.h"
#include "omni/asr/log_mel_spectrogram_processor.h"
#include "omni/asr/text_merger.h"

namespace {

using UpstreamAsrConfig = ::litert::omni::asr::AsrEngineConfig;
using UpstreamAsrEngine = ::litert::omni::asr::AsrEngine;
using UpstreamAsrSession = ::litert::omni::asr::AsrSession;
using UpstreamMergeResult = ::litert::omni::asr::TextMerger::MergeResult;

char *CopyString(const std::string &value) {
  char *copy = static_cast<char *>(std::malloc(value.size() + 1));
  if (copy == nullptr) {
    return nullptr;
  }
  std::memcpy(copy, value.c_str(), value.size() + 1);
  return copy;
}

void SetError(char **out_error_message, const std::string &message) {
  if (out_error_message == nullptr) {
    return;
  }
  *out_error_message = CopyString(message);
}

void ClearError(char **out_error_message) {
  if (out_error_message != nullptr) {
    *out_error_message = nullptr;
  }
}

LitertLmAsrStatus MapStatus(const absl::Status &status) {
  if (status.ok()) {
    return LITERT_LM_ASR_STATUS_OK;
  }
  switch (status.code()) {
  case absl::StatusCode::kInvalidArgument:
    return LITERT_LM_ASR_STATUS_INVALID_ARGUMENT;
  case absl::StatusCode::kFailedPrecondition:
    return LITERT_LM_ASR_STATUS_FAILED_PRECONDITION;
  case absl::StatusCode::kNotFound:
    return LITERT_LM_ASR_STATUS_NOT_FOUND;
  case absl::StatusCode::kAlreadyExists:
    return LITERT_LM_ASR_STATUS_ALREADY_EXISTS;
  case absl::StatusCode::kOutOfRange:
    return LITERT_LM_ASR_STATUS_OUT_OF_RANGE;
  case absl::StatusCode::kUnavailable:
    return LITERT_LM_ASR_STATUS_UNAVAILABLE;
  case absl::StatusCode::kCancelled:
    return LITERT_LM_ASR_STATUS_CANCELLED;
  case absl::StatusCode::kResourceExhausted:
    return LITERT_LM_ASR_STATUS_RESOURCE_EXHAUSTED;
  default:
    return LITERT_LM_ASR_STATUS_INTERNAL;
  }
}

LitertLmAsrStatus ReturnStatus(const absl::Status &status,
                               char **out_error_message) {
  ClearError(out_error_message);
  if (!status.ok()) {
    SetError(out_error_message, std::string(status.message()));
  }
  return MapStatus(status);
}

LitertLmAsrStatus ReturnInternalException(const char *operation,
                                          const std::exception *error,
                                          char **out_error_message) {
  std::string message = std::string(operation) + " failed";
  if (error != nullptr) {
    message += ": ";
    message += error->what();
  }
  SetError(out_error_message, message);
  return LITERT_LM_ASR_STATUS_INTERNAL;
}

absl::Status ValidateConfig(const LitertLmAsrConfig *config) {
  if (config == nullptr) {
    return absl::InvalidArgumentError("ASR config is required.");
  }
  if (config->struct_size < sizeof(LitertLmAsrConfig)) {
    return absl::InvalidArgumentError(
        "ASR config struct_size is smaller than ABI version 1 requires.");
  }
  if (config->abi_version != LITERT_LM_ASR_ABI_VERSION) {
    return absl::FailedPreconditionError("Unsupported ASR bridge ABI version.");
  }
  if (config->model_path == nullptr || config->model_path[0] == '\0') {
    return absl::InvalidArgumentError("ASR model_path is required.");
  }
  if (config->tokenizer_path == nullptr || config->tokenizer_path[0] == '\0') {
    return absl::InvalidArgumentError("ASR tokenizer_path is required.");
  }
  if (config->sample_rate_hz <= 0 || config->input_milliseconds <= 0) {
    return absl::InvalidArgumentError(
        "ASR sample_rate_hz and input_milliseconds must be positive.");
  }
  if (config->num_channels != 1) {
    return absl::InvalidArgumentError(
        "ASR bridge ABI version 1 accepts mono PCM only.");
  }
  if (config->max_buffered_audio_milliseconds < config->input_milliseconds) {
    return absl::InvalidArgumentError(
        "ASR max_buffered_audio_milliseconds must fit one input window.");
  }
  if (!std::isfinite(config->overlap_ratio) || config->overlap_ratio < 0.0f ||
      config->overlap_ratio >= 1.0f) {
    return absl::InvalidArgumentError(
        "ASR overlap_ratio must be finite and in the range [0, 1).");
  }
  const int64_t window_samples = static_cast<int64_t>(config->sample_rate_hz) *
                                 config->input_milliseconds / 1000;
  const int64_t overlap_samples = static_cast<int64_t>(std::llround(
      window_samples * static_cast<double>(config->overlap_ratio)));
  if (window_samples <= 0 || overlap_samples >= window_samples) {
    return absl::InvalidArgumentError(
        "ASR input window must contain samples beyond its overlap.");
  }
  if (config->num_threads <= 0) {
    return absl::InvalidArgumentError("ASR num_threads must be positive.");
  }
  return absl::OkStatus();
}

absl::StatusOr<UpstreamAsrConfig>
ToUpstreamConfig(const LitertLmAsrConfig &config) {
  UpstreamAsrConfig upstream;
  upstream.model_name = config.model_name == nullptr ? "" : config.model_name;
  upstream.model_path = config.model_path;
  upstream.tokenizer_path = config.tokenizer_path;
  upstream.sample_rate_hz = config.sample_rate_hz;
  upstream.input_milliseconds = config.input_milliseconds;
  upstream.num_threads = config.num_threads;
  upstream.overlap_ratio = config.overlap_ratio;
  upstream.decode_start_token_id = config.decode_start_token_id;
  upstream.decode_stop_token_id = config.decode_stop_token_id;
  upstream.decode_skip_until_token_id = config.decode_skip_until_token_id;
  upstream.decode_statefully_after = config.decode_statefully_after;
  upstream.vocab_size = config.vocab_size;
  upstream.blank_token_id = config.blank_token_id;

  switch (config.decoder_type) {
  case LITERT_LM_ASR_DECODER_CTC:
    upstream.decoder_type = UpstreamAsrConfig::DecoderType::kCtc;
    break;
  case LITERT_LM_ASR_DECODER_TDT:
    upstream.decoder_type = UpstreamAsrConfig::DecoderType::kTdt;
    break;
  case LITERT_LM_ASR_DECODER_STATELESS:
    upstream.decoder_type = UpstreamAsrConfig::DecoderType::kStateless;
    break;
  default:
    return absl::InvalidArgumentError("Unsupported ASR decoder_type.");
  }
  switch (config.backend) {
  case LITERT_LM_ASR_BACKEND_CPU:
    upstream.backend = UpstreamAsrConfig::Backend::kCpu;
    break;
  case LITERT_LM_ASR_BACKEND_GPU:
    upstream.backend = UpstreamAsrConfig::Backend::kGpu;
    break;
  case LITERT_LM_ASR_BACKEND_NPU:
    upstream.backend = UpstreamAsrConfig::Backend::kNpu;
    break;
  default:
    return absl::InvalidArgumentError("Unsupported ASR backend.");
  }
  switch (config.text_merger_type) {
  case LITERT_LM_ASR_TEXT_MERGER_LEVENSHTEIN:
    upstream.text_merger_type = UpstreamAsrConfig::TextMergerType::kLevenshtein;
    break;
  case LITERT_LM_ASR_TEXT_MERGER_TIMESTAMP:
    upstream.text_merger_type = UpstreamAsrConfig::TextMergerType::kTimestamp;
    break;
  default:
    return absl::InvalidArgumentError("Unsupported ASR text_merger_type.");
  }

  upstream.has_log_mel_config = config.has_log_mel_config != 0;
  if (upstream.has_log_mel_config) {
    auto &log_mel = upstream.log_mel_config;
    log_mel.n_fft = config.log_mel_n_fft;
    log_mel.n_mels = config.log_mel_n_mels;
    log_mel.hop_length = config.log_mel_hop_length;
    log_mel.n_frames = config.log_mel_n_frames;
    log_mel.transpose = config.log_mel_transpose != 0;
    log_mel.preemphasis = config.log_mel_preemphasis;
    switch (config.log_mel_norm_type) {
    case LITERT_LM_ASR_LOG_MEL_NORM_STANDARD:
      log_mel.norm_type =
          ::litert::omni::asr::LogMelSpectrogramProcessor::NormType::kStandard;
      break;
    case LITERT_LM_ASR_LOG_MEL_NORM_WHISPER:
      log_mel.norm_type =
          ::litert::omni::asr::LogMelSpectrogramProcessor::NormType::kWhisper;
      break;
    default:
      return absl::InvalidArgumentError("Unsupported ASR log_mel_norm_type.");
    }
  }
  return upstream;
}

absl::Status PopulateResult(const UpstreamMergeResult &source, bool is_final,
                            LitertLmAsrResult *destination) {
  if (destination == nullptr ||
      destination->struct_size < sizeof(LitertLmAsrResult)) {
    return absl::InvalidArgumentError(
        "ASR result must be initialized for ABI version 1.");
  }
  litert_lm_asr_result_release(destination);
  destination->confirmed_text = CopyString(source.confirmed_text);
  destination->unconfirmed_text = CopyString(source.unconfirmed_text);
  if (destination->confirmed_text == nullptr ||
      destination->unconfirmed_text == nullptr) {
    litert_lm_asr_result_release(destination);
    return absl::ResourceExhaustedError(
        "Could not allocate ASR result strings.");
  }
  destination->is_final = is_final ? 1 : 0;
  return absl::OkStatus();
}

} // namespace

struct LitertLmAsrEngine {
  std::shared_ptr<UpstreamAsrEngine> engine;
  LitertLmAsrConfig config;
};

struct LitertLmAsrSession {
  // Members are destroyed in reverse declaration order. Keep the engine
  // declared before the session so the upstream session releases tensor
  // buffers while its environment is still alive.
  std::shared_ptr<UpstreamAsrEngine> engine_keepalive;
  std::unique_ptr<UpstreamAsrSession> session;
  litert_lm_native::PushAudioSource *audio_source = nullptr;
  std::mutex process_mutex;
  bool final_result_returned = false;
};

extern "C" {

uint32_t litert_lm_asr_abi_version(void) { return LITERT_LM_ASR_ABI_VERSION; }

size_t litert_lm_asr_config_size(void) { return sizeof(LitertLmAsrConfig); }

size_t litert_lm_asr_result_size(void) { return sizeof(LitertLmAsrResult); }

void litert_lm_asr_config_init(LitertLmAsrConfig *config) {
  if (config == nullptr) {
    return;
  }
  std::memset(config, 0, sizeof(*config));
  config->struct_size = sizeof(*config);
  config->abi_version = LITERT_LM_ASR_ABI_VERSION;
  config->sample_rate_hz = 16000;
  config->num_channels = 1;
  config->input_milliseconds = 5000;
  config->max_buffered_audio_milliseconds = 30000;
  config->decoder_type = LITERT_LM_ASR_DECODER_TDT;
  config->backend = LITERT_LM_ASR_BACKEND_CPU;
  config->text_merger_type = LITERT_LM_ASR_TEXT_MERGER_TIMESTAMP;
  config->num_threads = 4;
  config->overlap_ratio = 0.4f;
  config->log_mel_n_fft = 512;
  config->log_mel_n_mels = 80;
  config->log_mel_hop_length = 160;
  config->decode_start_token_id = -1;
  config->decode_stop_token_id = -1;
  config->decode_skip_until_token_id = -1;
  config->decode_statefully_after = 4;
}

LitertLmAsrStatus
litert_lm_asr_config_init_for_model_preset(LitertLmAsrConfig *config,
                                           LitertLmAsrModelPreset preset) {
  if (config == nullptr) {
    return LITERT_LM_ASR_STATUS_INVALID_ARGUMENT;
  }
  litert_lm_asr_config_init(config);
  switch (preset) {
  case LITERT_LM_ASR_MODEL_PRESET_PARAKEET_TDT_0_6B_V3:
    config->model_name = "parakeet-tdt-0.6b-v3";
    config->decoder_type = LITERT_LM_ASR_DECODER_TDT;
    config->has_log_mel_config = 1;
    config->log_mel_n_fft = 512;
    config->log_mel_n_mels = 128;
    config->log_mel_n_frames = 500;
    config->log_mel_preemphasis = 0.97f;
    config->decode_start_token_id = 8192;
    return LITERT_LM_ASR_STATUS_OK;
  case LITERT_LM_ASR_MODEL_PRESET_PARAKEET_CTC_0_6B:
    config->model_name = "parakeet-ctc-0.6b";
    config->decoder_type = LITERT_LM_ASR_DECODER_CTC;
    config->has_log_mel_config = 1;
    config->log_mel_n_fft = 512;
    config->log_mel_n_frames = 500;
    config->log_mel_transpose = 1;
    config->log_mel_preemphasis = 0.97f;
    return LITERT_LM_ASR_STATUS_OK;
  case LITERT_LM_ASR_MODEL_PRESET_MOONSHINE_TINY:
    config->model_name = "moonshine-tiny";
    config->decoder_type = LITERT_LM_ASR_DECODER_STATELESS;
    config->has_log_mel_config = 0;
    config->decode_start_token_id = 1;
    config->decode_stop_token_id = 2;
    return LITERT_LM_ASR_STATUS_OK;
  case LITERT_LM_ASR_MODEL_PRESET_WHISPER_TINY:
    config->model_name = "whisper-tiny";
    config->input_milliseconds = 30000;
    config->decoder_type = LITERT_LM_ASR_DECODER_STATELESS;
    config->has_log_mel_config = 1;
    config->log_mel_n_fft = 400;
    config->log_mel_n_frames = 3000;
    config->log_mel_norm_type = LITERT_LM_ASR_LOG_MEL_NORM_WHISPER;
    config->decode_start_token_id = 50258;
    config->decode_stop_token_id = 50257;
    return LITERT_LM_ASR_STATUS_OK;
  case LITERT_LM_ASR_MODEL_PRESET_QWEN3_ASR_0_6B:
    config->model_name = "qwen3-asr-0.6b";
    config->decoder_type = LITERT_LM_ASR_DECODER_STATELESS;
    config->has_log_mel_config = 1;
    config->log_mel_n_fft = 400;
    config->log_mel_n_mels = 128;
    config->log_mel_n_frames = 500;
    config->log_mel_norm_type = LITERT_LM_ASR_LOG_MEL_NORM_WHISPER;
    config->decode_start_token_id = 198;
    config->decode_stop_token_id = 151645;
    config->decode_skip_until_token_id = 151704;
    return LITERT_LM_ASR_STATUS_OK;
  default:
    return LITERT_LM_ASR_STATUS_INVALID_ARGUMENT;
  }
}

void litert_lm_asr_result_init(LitertLmAsrResult *result) {
  if (result == nullptr) {
    return;
  }
  std::memset(result, 0, sizeof(*result));
  result->struct_size = sizeof(*result);
}

void litert_lm_asr_result_release(LitertLmAsrResult *result) {
  if (result == nullptr) {
    return;
  }
  std::free(result->confirmed_text);
  std::free(result->unconfirmed_text);
  result->confirmed_text = nullptr;
  result->unconfirmed_text = nullptr;
  result->is_final = 0;
}

void litert_lm_asr_free_string(char *value) { std::free(value); }

LitertLmAsrStatus litert_lm_asr_engine_create(const LitertLmAsrConfig *config,
                                              LitertLmAsrEngine **out_engine,
                                              char **out_error_message) {
  ClearError(out_error_message);
  if (out_engine == nullptr) {
    return ReturnStatus(absl::InvalidArgumentError("out_engine is required."),
                        out_error_message);
  }
  *out_engine = nullptr;
  absl::Status validation = ValidateConfig(config);
  if (!validation.ok()) {
    return ReturnStatus(validation, out_error_message);
  }
  try {
    auto upstream_config = ToUpstreamConfig(*config);
    if (!upstream_config.ok()) {
      return ReturnStatus(upstream_config.status(), out_error_message);
    }
    auto upstream_engine =
        UpstreamAsrEngine::Create(*std::move(upstream_config));
    if (!upstream_engine.ok()) {
      return ReturnStatus(upstream_engine.status(), out_error_message);
    }
    auto engine = std::make_unique<LitertLmAsrEngine>();
    engine->engine = std::move(upstream_engine).value();
    engine->config = *config;
    engine->config.model_name = nullptr;
    engine->config.model_path = nullptr;
    engine->config.tokenizer_path = nullptr;
    *out_engine = engine.release();
    return LITERT_LM_ASR_STATUS_OK;
  } catch (const std::exception &error) {
    return ReturnInternalException("ASR engine creation", &error,
                                   out_error_message);
  } catch (...) {
    return ReturnInternalException("ASR engine creation", nullptr,
                                   out_error_message);
  }
}

void litert_lm_asr_engine_delete(LitertLmAsrEngine *engine) { delete engine; }

LitertLmAsrStatus litert_lm_asr_session_create(LitertLmAsrEngine *engine,
                                               LitertLmAsrSession **out_session,
                                               char **out_error_message) {
  ClearError(out_error_message);
  if (engine == nullptr || out_session == nullptr) {
    return ReturnStatus(
        absl::InvalidArgumentError("engine and out_session are required."),
        out_error_message);
  }
  *out_session = nullptr;
  try {
    auto audio_source = std::make_unique<litert_lm_native::PushAudioSource>(
        engine->config.sample_rate_hz, engine->config.num_channels,
        engine->config.input_milliseconds, engine->config.overlap_ratio,
        engine->config.max_buffered_audio_milliseconds);
    auto *raw_audio_source = audio_source.get();
    auto upstream_session =
        engine->engine->CreateSession(std::move(audio_source));
    if (!upstream_session.ok()) {
      return ReturnStatus(upstream_session.status(), out_error_message);
    }
    auto session = std::make_unique<LitertLmAsrSession>();
    session->session = std::move(upstream_session).value();
    session->engine_keepalive = engine->engine;
    session->audio_source = raw_audio_source;
    *out_session = session.release();
    return LITERT_LM_ASR_STATUS_OK;
  } catch (const std::exception &error) {
    return ReturnInternalException("ASR session creation", &error,
                                   out_error_message);
  } catch (...) {
    return ReturnInternalException("ASR session creation", nullptr,
                                   out_error_message);
  }
}

void litert_lm_asr_session_delete(LitertLmAsrSession *session) {
  delete session;
}

LitertLmAsrStatus litert_lm_asr_session_push_audio_f32(
    LitertLmAsrSession *session, const float *samples, size_t sample_count,
    size_t *out_accepted_samples, char **out_error_message) {
  ClearError(out_error_message);
  if (out_accepted_samples != nullptr) {
    *out_accepted_samples = 0;
  }
  if (session == nullptr || out_accepted_samples == nullptr ||
      (sample_count > 0 && samples == nullptr)) {
    return ReturnStatus(absl::InvalidArgumentError(
                            "session, samples, and out_accepted_samples are "
                            "required."),
                        out_error_message);
  }
  if (session->audio_source->IsCancelled()) {
    return ReturnStatus(absl::CancelledError("ASR session was cancelled."),
                        out_error_message);
  }
  if (session->audio_source->IsFinished()) {
    return ReturnStatus(absl::FailedPreconditionError(
                            "ASR audio input has already been finished."),
                        out_error_message);
  }
  const size_t accepted = session->audio_source->Push(samples, sample_count);
  *out_accepted_samples = accepted;
  if (accepted < sample_count) {
    SetError(out_error_message,
             "ASR input queue is full or no longer accepts audio.");
    return LITERT_LM_ASR_STATUS_WOULD_BLOCK;
  }
  return LITERT_LM_ASR_STATUS_OK;
}

LitertLmAsrStatus
litert_lm_asr_session_finish_audio(LitertLmAsrSession *session,
                                   char **out_error_message) {
  if (session == nullptr) {
    return ReturnStatus(absl::InvalidArgumentError("session is required."),
                        out_error_message);
  }
  return ReturnStatus(session->audio_source->Finish(), out_error_message);
}

LitertLmAsrStatus
litert_lm_asr_session_process_next(LitertLmAsrSession *session,
                                   LitertLmAsrResult *out_result,
                                   char **out_error_message) {
  ClearError(out_error_message);
  if (session == nullptr || out_result == nullptr ||
      out_result->struct_size < sizeof(LitertLmAsrResult)) {
    return ReturnStatus(
        absl::InvalidArgumentError(
            "session and an initialized out_result are required."),
        out_error_message);
  }

  std::lock_guard<std::mutex> lock(session->process_mutex);
  if (session->audio_source->IsCancelled()) {
    return ReturnStatus(absl::CancelledError("ASR session was cancelled."),
                        out_error_message);
  }
  if (session->final_result_returned) {
    return LITERT_LM_ASR_STATUS_END_OF_STREAM;
  }

  try {
    if (!session->audio_source->CanProcess()) {
      if (!session->audio_source->IsFinishedAndDrained()) {
        return LITERT_LM_ASR_STATUS_NEEDS_MORE_AUDIO;
      }
      auto flush_result = session->session->Flush();
      UpstreamMergeResult final_result;
      if (flush_result.ok()) {
        final_result = *std::move(flush_result);
      } else if (!absl::IsNotFound(flush_result.status())) {
        return ReturnStatus(flush_result.status(), out_error_message);
      }
      absl::Status populate = PopulateResult(final_result, true, out_result);
      if (!populate.ok()) {
        return ReturnStatus(populate, out_error_message);
      }
      session->final_result_returned = true;
      return LITERT_LM_ASR_STATUS_OK;
    }

    auto result = session->session->ProcessNextChunk();
    if (!result.ok()) {
      if (absl::IsNotFound(result.status())) {
        return LITERT_LM_ASR_STATUS_NEEDS_MORE_AUDIO;
      }
      return ReturnStatus(result.status(), out_error_message);
    }
    if (session->audio_source->IsCancelled()) {
      return ReturnStatus(absl::CancelledError("ASR session was cancelled."),
                          out_error_message);
    }
    absl::Status populate = PopulateResult(*result, false, out_result);
    return ReturnStatus(populate, out_error_message);
  } catch (const std::exception &error) {
    return ReturnInternalException("ASR inference", &error, out_error_message);
  } catch (...) {
    return ReturnInternalException("ASR inference", nullptr, out_error_message);
  }
}

LitertLmAsrStatus litert_lm_asr_session_reset(LitertLmAsrSession *session,
                                              char **out_error_message) {
  ClearError(out_error_message);
  if (session == nullptr) {
    return ReturnStatus(absl::InvalidArgumentError("session is required."),
                        out_error_message);
  }
  std::lock_guard<std::mutex> lock(session->process_mutex);
  try {
    session->session->Reset();
    session->final_result_returned = false;
    return LITERT_LM_ASR_STATUS_OK;
  } catch (const std::exception &error) {
    return ReturnInternalException("ASR session reset", &error,
                                   out_error_message);
  } catch (...) {
    return ReturnInternalException("ASR session reset", nullptr,
                                   out_error_message);
  }
}

LitertLmAsrStatus litert_lm_asr_session_cancel(LitertLmAsrSession *session) {
  if (session == nullptr) {
    return LITERT_LM_ASR_STATUS_INVALID_ARGUMENT;
  }
  session->audio_source->Cancel();
  return LITERT_LM_ASR_STATUS_OK;
}

} // extern "C"
