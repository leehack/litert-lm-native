#ifndef LITERT_LM_NATIVE_BRIDGE_LITERT_LM_ASR_OMNI_INPUT_SOURCE_H_
#define LITERT_LM_NATIVE_BRIDGE_LITERT_LM_ASR_OMNI_INPUT_SOURCE_H_

#include <cstddef>
#include <deque>
#include <mutex>

#include "absl/status/status.h"
#include "omni/omni_session.h"

namespace litert_lm_native {

// Bounded, thread-safe PCM queue feeding an upstream ASR OmniSession. Upstream
// builds the overlapping inference windows, so this source only hands over
// samples and the end-of-input marker.
class PushAudioSource final : public ::litert::omni::OmniSession::InputSource {
public:
  PushAudioSource(int sample_rate_hz, int num_channels, int input_milliseconds,
                  float overlap_ratio, int max_buffered_audio_milliseconds);

  size_t Push(const float *samples, size_t sample_count);
  absl::Status Finish();
  void Cancel();

  // The session decides whether a window is ready, so it is always asked.
  bool CanProcess() const { return true; }
  bool IsFinished() const;
  bool IsFinishedAndDrained() const;
  bool IsCancelled() const;

protected:
  void ResetInternal() override;
  bool NeedScheduleInternal() const override;
  absl::Status ScheduleInternal() override;

private:
  const size_t max_chunk_samples_;
  const size_t max_buffered_samples_;

  mutable std::mutex input_mutex_;
  std::deque<float> pending_samples_;
  bool finished_ = false;
  bool end_of_input_sent_ = false;
  bool cancelled_ = false;
};

} // namespace litert_lm_native

#endif // LITERT_LM_NATIVE_BRIDGE_LITERT_LM_ASR_OMNI_INPUT_SOURCE_H_
