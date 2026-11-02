#include "bridge/litert_lm_asr_omni_input_source.h"

#include <algorithm>
#include <cmath>
#include <utility>
#include <vector>

#include "absl/cleanup/cleanup.h"
#include "absl/status/status.h"

namespace litert_lm_native {
namespace {

size_t MillisecondsToSamples(int sample_rate_hz, int milliseconds) {
  return static_cast<size_t>(std::llround(static_cast<double>(sample_rate_hz) *
                                          milliseconds / 1000.0));
}

// Upstream drains its source until one window is buffered, so a chunk of at
// most one window step keeps at most one ready window out of the bounded queue.
size_t WindowStepSamples(int sample_rate_hz, int input_milliseconds,
                         float overlap_ratio) {
  const size_t window = MillisecondsToSamples(sample_rate_hz, input_milliseconds);
  const size_t overlap = static_cast<size_t>(
      std::llround(window * static_cast<double>(overlap_ratio)));
  return std::max<size_t>(1, window - overlap);
}

} // namespace

PushAudioSource::PushAudioSource(int sample_rate_hz, int num_channels,
                                 int input_milliseconds, float overlap_ratio,
                                 int max_buffered_audio_milliseconds)
    : max_chunk_samples_(WindowStepSamples(sample_rate_hz, input_milliseconds,
                                           overlap_ratio)),
      max_buffered_samples_(MillisecondsToSamples(
          sample_rate_hz, max_buffered_audio_milliseconds)) {
  (void)num_channels;
}

size_t PushAudioSource::Push(const float *samples, size_t sample_count) {
  std::lock_guard<std::mutex> lock(input_mutex_);
  if (finished_ || cancelled_ || samples == nullptr || sample_count == 0) {
    return 0;
  }
  const size_t available = max_buffered_samples_ > pending_samples_.size()
                               ? max_buffered_samples_ - pending_samples_.size()
                               : 0;
  const size_t accepted = std::min(sample_count, available);
  pending_samples_.insert(pending_samples_.end(), samples, samples + accepted);
  return accepted;
}

absl::Status PushAudioSource::Finish() {
  std::lock_guard<std::mutex> lock(input_mutex_);
  if (cancelled_) {
    return absl::CancelledError("ASR audio input was cancelled.");
  }
  if (finished_) {
    return absl::FailedPreconditionError(
        "ASR audio input has already been finished.");
  }
  finished_ = true;
  return absl::OkStatus();
}

void PushAudioSource::Cancel() {
  std::lock_guard<std::mutex> lock(input_mutex_);
  cancelled_ = true;
}

bool PushAudioSource::IsFinished() const {
  std::lock_guard<std::mutex> lock(input_mutex_);
  return finished_;
}

bool PushAudioSource::IsFinishedAndDrained() const {
  std::lock_guard<std::mutex> lock(input_mutex_);
  return finished_ && pending_samples_.empty();
}

bool PushAudioSource::IsCancelled() const {
  std::lock_guard<std::mutex> lock(input_mutex_);
  return cancelled_;
}

void PushAudioSource::ResetInternal() {
  std::lock_guard<std::mutex> lock(input_mutex_);
  pending_samples_.clear();
  finished_ = false;
  end_of_input_sent_ = false;
  cancelled_ = false;
}

bool PushAudioSource::NeedScheduleInternal() const {
  std::lock_guard<std::mutex> lock(input_mutex_);
  return cancelled_ || !pending_samples_.empty() ||
         (finished_ && !end_of_input_sent_);
}

absl::Status PushAudioSource::ScheduleInternal() {
  SetState(State::kRunning);
  absl::Cleanup cleanup = [this] { SetState(State::kIdle); };

  ::litert::omni::OmniSession::Input input;
  {
    std::lock_guard<std::mutex> lock(input_mutex_);
    if (cancelled_) {
      return absl::CancelledError("ASR audio input was cancelled.");
    }
    if (pending_samples_.empty()) {
      if (!finished_) {
        return absl::NotFoundError("No ASR audio is buffered.");
      }
      if (end_of_input_sent_) {
        return absl::OutOfRangeError("End of ASR audio input reached.");
      }
      end_of_input_sent_ = true;
      input = ::litert::omni::OmniSession::EndOfInput{};
    } else {
      const size_t count = std::min(max_chunk_samples_, pending_samples_.size());
      std::vector<float> chunk(pending_samples_.begin(),
                               pending_samples_.begin() + count);
      pending_samples_.erase(pending_samples_.begin(),
                             pending_samples_.begin() + count);
      input = ::litert::omni::OmniSession::AudioInput{std::move(chunk)};
    }
  }
  PushOutput(std::move(input));
  return absl::OkStatus();
}

} // namespace litert_lm_native
