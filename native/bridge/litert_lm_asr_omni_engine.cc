#include "bridge/litert_lm_asr_omni_engine.h"

#include <cstdint>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#include "absl/status/status.h"
#include "absl/status/statusor.h"
#include "absl/status/status_macros.h"
#include "absl/strings/match.h"
#include "absl/strings/str_cat.h"
#include "absl/strings/string_view.h"
#include "litert/cc/litert_common.h"
#include "litert/cc/litert_compiled_model.h"
#include "litert/cc/litert_environment.h"
#include "litert/cc/litert_macros.h"
#include "litert/cc/litert_options.h"
#include "litert/cc/options/litert_cpu_options.h"
#include "litert/cc/options/litert_gpu_options.h"
#include "litert/cc/options/litert_qualcomm_options.h"
#include "omni/base/litert_runner.h"
#include "omni/base/model_cache.h"
#include "omni/base/model_utils.h"
#include "omni/multi_staged_session.h"
#include "omni/omni_engine.h"
#include "omni/omni_registry.h"
#include "omni/speech2text/asr_session.h"
#include "omni/speech2text/audio_source.h"
#include "omni/speech2text/ctc_decoder.h"
#include "omni/speech2text/stateless_decoder.h"
#include "omni/speech2text/tdt_decoder.h"
#include "runtime/components/model_resources_litert_lm.h"
#include "runtime/proto/speech2text_metadata.pb.h"
#include "runtime/proto/speech2text_model_type.pb.h"
#include "runtime/proto/speech2text_session_config.pb.h"
#include "runtime/util/litert_lm_loader.h"
#include "runtime/util/scoped_file.h"

namespace litert_lm_native {
namespace {

using ::litert::omni::OmniEngine;
using ::litert::omni::OmniSessionFactory;
using ::litert::omni::asr::AsrSessionFactory;
using ::litert::omni::asr::AudioSource;
using Metadata = ::litert::lm::proto::Speech2TextMetadata;
using LogMelProto = ::litert::lm::proto::LogMelSpectrogramConfig;
using SessionConfig = ::litert::lm::proto::Speech2TextSessionConfig;

OmniEngine::Settings ToSettings(const LitertLmAsrConfig &config) {
  OmniEngine::Settings settings;
  switch (config.backend) {
  case LITERT_LM_ASR_BACKEND_GPU:
    settings.backend = OmniEngine::Settings::Backend::kGpu;
    // ABI version 1 GPU sessions have always run at FP32.
    settings.force_fp32_on_gpu = true;
    break;
  case LITERT_LM_ASR_BACKEND_NPU:
    settings.backend = OmniEngine::Settings::Backend::kNpu;
    break;
  default:
    settings.backend = OmniEngine::Settings::Backend::kCpu;
    break;
  }
  // The ABI has no cache directory, and the default writes next to the model,
  // which can be a read-only or shared location.
  settings.cache_dir = std::string(::litert::omni::kNoCacheDir);
  settings.num_threads = config.num_threads;
  settings.model_path = config.model_path;
  settings.tokenizer_path = config.tokenizer_path;
  return settings;
}

SessionConfig ToSessionConfig(const LitertLmAsrConfig &config) {
  SessionConfig session_config;
  session_config.set_overlap_ratio(config.overlap_ratio);
  session_config.set_text_merger_type(
      config.text_merger_type == LITERT_LM_ASR_TEXT_MERGER_LEVENSHTEIN
          ? SessionConfig::TEXT_MERGER_TYPE_LEVENSHTEIN
          : SessionConfig::TEXT_MERGER_TYPE_TIMESTAMP);
  return session_config;
}

// Caller values override container metadata in the registry's merge. Fields
// the ABI leaves at zero stay unset so container and family defaults apply.
Metadata ToMetadata(const LitertLmAsrConfig &config) {
  Metadata metadata;
  metadata.set_sample_rate_hz(config.sample_rate_hz);
  metadata.set_input_milliseconds(config.input_milliseconds);
  if (config.decode_start_token_id >= 0) {
    metadata.add_decode_start_token_ids(config.decode_start_token_id);
  }
  if (config.decode_stop_token_id >= 0) {
    metadata.set_decode_stop_token_id(config.decode_stop_token_id);
  }
  if (config.decode_skip_until_token_id >= 0) {
    metadata.set_decode_skip_until_token_id(config.decode_skip_until_token_id);
  }
  metadata.set_decode_statefully_after(config.decode_statefully_after);
  if (config.vocab_size > 0) {
    metadata.set_vocab_size(config.vocab_size);
  }
  if (config.blank_token_id > 0) {
    metadata.set_blank_token_id(config.blank_token_id);
  }
  if (config.has_log_mel_config != 0) {
    LogMelProto *log_mel = metadata.mutable_log_mel_spectrogram_config();
    log_mel->set_n_fft(config.log_mel_n_fft);
    log_mel->set_n_mels(config.log_mel_n_mels);
    log_mel->set_hop_length(config.log_mel_hop_length);
    if (config.log_mel_n_frames > 0) {
      log_mel->set_n_frames(config.log_mel_n_frames);
    }
    if (config.log_mel_transpose != 0) {
      log_mel->set_transpose(true);
    }
    if (config.log_mel_preemphasis > 0.0f) {
      log_mel->set_preemphasis(config.log_mel_preemphasis);
    }
    if (config.log_mel_norm_type == LITERT_LM_ASR_LOG_MEL_NORM_WHISPER) {
      log_mel->set_norm_type(LogMelProto::NORM_TYPE_WHISPER);
    }
  }
  return metadata;
}

// The registry routes by name, so reject a container built for another family
// instead of decoding it with the wrong session.
absl::Status CheckContainerFamily(absl::string_view model_name,
                                  const std::string &model_path) {
  ABSL_ASSIGN_OR_RETURN(auto file, ::litert::lm::ScopedFile::Open(model_path));
  ABSL_ASSIGN_OR_RETURN(auto loader,
                        ::litert::lm::LitertLmLoader::Create(std::move(file)));
  ABSL_ASSIGN_OR_RETURN(auto resources, ::litert::lm::ModelResourcesLitertLm::Create(
                                            std::move(loader)));
  auto metadata = resources->GetSpeech2TextMetadata();
  if (!metadata.ok() || *metadata == nullptr ||
      !(*metadata)->has_asr_model_type()) {
    return absl::OkStatus();
  }
  const auto &type = (*metadata)->asr_model_type();
  absl::string_view family;
  if (type.has_whisper()) {
    family = "whisper";
  } else if (type.has_parakeet()) {
    family = "parakeet";
  } else if (type.has_moonshine()) {
    family = "moonshine";
  } else if (type.has_qwen3_asr()) {
    family = "qwen3-asr";
  } else {
    return absl::OkStatus();
  }
  if (!absl::StrContains(model_name, family)) {
    return absl::InvalidArgumentError(
        absl::StrCat("ASR container metadata declares ", family,
                     " but the config selects ", model_name, "."));
  }
  return absl::OkStatus();
}

absl::StatusOr<std::string> ContainerModelName(const LitertLmAsrConfig &config) {
  if (config.model_name != nullptr && config.model_name[0] != '\0') {
    return std::string(config.model_name);
  }
  return ::litert::omni::OmniRegistry::Get().FindModelNameForPath(
      config.model_path);
}

// A plain TFLite model plus tokenizer file. Upstream's registered factories
// require a container, but ABI version 1 and published model sets accept this.
class FileAsrSessionFactory final : public AsrSessionFactory {
public:
  FileAsrSessionFactory(
      const OmniEngine::Settings &settings, const SessionConfig &session_config,
      const Metadata &metadata, ::litert::Environment environment,
      std::unique_ptr<::litert::support::Tokenizer> tokenizer,
      std::unique_ptr<::litert::CompiledModel> compiled_model,
      LitertLmAsrDecoderType decoder_type)
      : AsrSessionFactory(settings, &session_config, &metadata,
                          std::move(environment), /*model_resources=*/nullptr,
                          std::move(tokenizer)),
        compiled_model_(std::move(compiled_model)), decoder_type_(decoder_type) {}

protected:
  absl::StatusOr<std::unique_ptr<::litert::omni::MultiStagedSession>>
  CreateWithAudioSource(std::unique_ptr<AudioSource> audio_source) override {
    auto encoder =
        std::make_unique<::litert::omni::LiteRtRunnerImpl>(compiled_model_.get());
    const std::vector<int> start_token_ids(
        metadata().decode_start_token_ids().begin(),
        metadata().decode_start_token_ids().end());
    std::unique_ptr<::litert::omni::asr::LiteRtSpeechRecognizer::Decoder> decoder;
    switch (decoder_type_) {
    case LITERT_LM_ASR_DECODER_TDT: {
      ABSL_ASSIGN_OR_RETURN(decoder, ::litert::omni::asr::TdtDecoder::Create(
                                         encoder.get(), start_token_ids,
                                         metadata().decode_statefully_after()));
      break;
    }
    case LITERT_LM_ASR_DECODER_CTC: {
      ABSL_ASSIGN_OR_RETURN(decoder, ::litert::omni::asr::CtcDecoder::Create(
                                         metadata().vocab_size()));
      break;
    }
    case LITERT_LM_ASR_DECODER_STATELESS: {
      ABSL_ASSIGN_OR_RETURN(decoder,
                            ::litert::omni::asr::StatelessDecoder::Create(
                                encoder.get(), start_token_ids,
                                metadata().decode_stop_token_id(),
                                metadata().decode_skip_until_token_id()));
      break;
    }
    default:
      return absl::InvalidArgumentError("Unsupported ASR decoder_type.");
    }
    return CreateMultiStagedSession(std::move(audio_source), std::move(encoder),
                                    std::move(decoder));
  }

private:
  std::unique_ptr<::litert::CompiledModel> compiled_model_;
  const LitertLmAsrDecoderType decoder_type_;
};

absl::StatusOr<::litert::Options>
CreateFileModelOptions(const LitertLmAsrConfig &config) {
  LITERT_ASSIGN_OR_RETURN(auto options, ::litert::Options::Create());
  uint32_t accelerators = static_cast<uint32_t>(::litert::HwAccelerators::kCpu);
  LITERT_ASSIGN_OR_RETURN(auto &cpu_options,
                          options.GetOptions<::litert::CpuOptions>());
  LITERT_RETURN_IF_ERROR(cpu_options.SetNumThreads(config.num_threads));
  if (config.backend == LITERT_LM_ASR_BACKEND_GPU) {
    accelerators |= static_cast<uint32_t>(::litert::HwAccelerators::kGpu);
    LITERT_ASSIGN_OR_RETURN(auto &gpu_options,
                            options.GetOptions<::litert::GpuOptions>());
    gpu_options.SetPrecision(::litert::GpuOptions::Precision::kFp32);
    gpu_options.EnableConstantTensorSharing(true);
  } else if (config.backend == LITERT_LM_ASR_BACKEND_NPU) {
    accelerators |= static_cast<uint32_t>(::litert::HwAccelerators::kNpu);
    LITERT_ASSIGN_OR_RETURN(
        auto &qnn_options,
        options.GetOptions<::litert::qualcomm::QualcommOptions>());
    qnn_options.SetHtpPerformanceMode(::litert::qualcomm::QualcommOptions::
                                          HtpPerformanceMode::kHighPerformance);
  }
  LITERT_RETURN_IF_ERROR(options.SetHardwareAccelerators(
      static_cast<::litert::HwAccelerators>(accelerators)));
  return options;
}

// Mirrors the feature settings of upstream's container factories, which the
// ABI's log-mel fields cannot express.
void ApplyFamilyLogMelDefaults(const LitertLmAsrConfig &config,
                               Metadata &metadata) {
  if (config.has_log_mel_config == 0) {
    return;
  }
  LogMelProto *log_mel = metadata.mutable_log_mel_spectrogram_config();
  log_mel->set_slaney_mel(true);
  log_mel->set_power_spectrum(true);
  log_mel->set_mel_floor(config.log_mel_norm_type ==
                                 LITERT_LM_ASR_LOG_MEL_NORM_WHISPER
                             ? 1e-10f
                             : 5.960464477539063e-08f);
}

absl::StatusOr<std::unique_ptr<OmniSessionFactory>>
CreateFileSessionFactory(const LitertLmAsrConfig &config,
                         const OmniEngine::Settings &settings) {
  ABSL_RETURN_IF_ERROR(::litert::omni::CheckFileReadable(config.model_path));
  ABSL_ASSIGN_OR_RETURN(auto tokenizer,
                        ::litert::omni::CreateTokenizer(
                            /*lm_resources=*/nullptr, config.tokenizer_path));
  LITERT_ASSIGN_OR_RETURN(auto environment, ::litert::Environment::Create({}));
  ABSL_ASSIGN_OR_RETURN(auto options, CreateFileModelOptions(config));
  LITERT_ASSIGN_OR_RETURN(auto compiled_model,
                          ::litert::CompiledModel::Create(
                              environment, config.model_path, options));
  Metadata metadata = ToMetadata(config);
  ApplyFamilyLogMelDefaults(config, metadata);
  return std::make_unique<FileAsrSessionFactory>(
      settings, ToSessionConfig(config), metadata, std::move(environment),
      std::move(tokenizer),
      std::make_unique<::litert::CompiledModel>(std::move(compiled_model)),
      config.decoder_type);
}

} // namespace

absl::StatusOr<std::unique_ptr<OmniSessionFactory>>
CreateAsrSessionFactory(const LitertLmAsrConfig &config) {
  const OmniEngine::Settings settings = ToSettings(config);
  if (!absl::EndsWith(config.model_path, ".litertlm")) {
    return CreateFileSessionFactory(config, settings);
  }
  ABSL_RETURN_IF_ERROR(::litert::omni::CheckFileReadable(config.model_path));
  ABSL_ASSIGN_OR_RETURN(const std::string model_name, ContainerModelName(config));
  ABSL_RETURN_IF_ERROR(CheckContainerFamily(model_name, config.model_path));
  const SessionConfig session_config = ToSessionConfig(config);
  Metadata metadata = ToMetadata(config);
  // Upstream's LM-backed decoders reject start tokens, which ABI version 1
  // presets and callers still supply for these families.
  if (absl::StrContains(model_name, "qwen3-asr") ||
      absl::StrContains(model_name, "tinygemma-asr")) {
    metadata.clear_decode_start_token_ids();
  }
  return ::litert::omni::OmniRegistry::Get().CreateSessionFactory(
      model_name, settings, &session_config, &metadata);
}

} // namespace litert_lm_native
