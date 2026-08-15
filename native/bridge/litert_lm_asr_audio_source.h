#ifndef LITERT_LM_NATIVE_BRIDGE_LITERT_LM_ASR_AUDIO_SOURCE_H_
#define LITERT_LM_NATIVE_BRIDGE_LITERT_LM_ASR_AUDIO_SOURCE_H_

#include <cstddef>
#include <cstdint>
#include <deque>
#include <mutex>
#include <vector>

#include "absl/status/status.h"
#include "omni/asr/audio_source.h"

namespace litert_lm_native {

// Bounded, thread-safe streaming PCM source for LiteRT-LM's ASR pipeline.
// The source creates fixed-size overlapping windows without re-accepting the
// overlap samples from the caller.
class PushAudioSource final : public ::litert::omni::asr::AudioSource {
public:
  PushAudioSource(int sample_rate_hz, int num_channels, int input_milliseconds,
                  float overlap_ratio, int max_buffered_audio_milliseconds);

  size_t Push(const float *samples, size_t sample_count);
  absl::Status Finish();
  void Cancel();

  bool CanProcess() const;
  bool IsFinished() const;
  bool IsFinishedAndDrained() const;
  bool IsCancelled() const;

  void Reset() override;
  int GetSampleRateHz() const override { return sample_rate_hz_; }
  int GetNumChannels() const override { return num_channels_; }

protected:
  bool NeedScheduleInternal() const override;
  absl::Status ScheduleInternal() override;

private:
  bool CanProcessLocked() const;

  const int sample_rate_hz_;
  const int num_channels_;
  const size_t window_samples_;
  const size_t overlap_samples_;
  const size_t step_samples_;
  const size_t max_buffered_samples_;

  mutable std::mutex input_mutex_;
  std::deque<float> pending_samples_;
  std::vector<float> overlap_;
  bool started_ = false;
  bool finished_ = false;
  bool cancelled_ = false;
};

} // namespace litert_lm_native

#endif // LITERT_LM_NATIVE_BRIDGE_LITERT_LM_ASR_AUDIO_SOURCE_H_
