#include "bridge/litert_lm_asr_audio_source.h"

#include <algorithm>
#include <cmath>
#include <utility>

#include "absl/cleanup/cleanup.h"
#include "absl/status/status.h"

namespace litert_lm_native {
namespace {

size_t MillisecondsToSamples(int sample_rate_hz, int milliseconds) {
  return static_cast<size_t>(std::llround(static_cast<double>(sample_rate_hz) *
                                          milliseconds / 1000.0));
}

} // namespace

PushAudioSource::PushAudioSource(int sample_rate_hz, int num_channels,
                                 int input_milliseconds, float overlap_ratio,
                                 int max_buffered_audio_milliseconds)
    : sample_rate_hz_(sample_rate_hz), num_channels_(num_channels),
      window_samples_(
          MillisecondsToSamples(sample_rate_hz, input_milliseconds)),
      overlap_samples_(static_cast<size_t>(
          std::llround(window_samples_ * static_cast<double>(overlap_ratio)))),
      step_samples_(window_samples_ - overlap_samples_),
      max_buffered_samples_(MillisecondsToSamples(
          sample_rate_hz, max_buffered_audio_milliseconds)) {}

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

bool PushAudioSource::CanProcess() const {
  std::lock_guard<std::mutex> lock(input_mutex_);
  return CanProcessLocked();
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

void PushAudioSource::Reset() {
  WaitForStateThenSetState(State::kIdle, State::kRunning);
  {
    std::lock_guard<std::mutex> lock(input_mutex_);
    pending_samples_.clear();
    overlap_.clear();
    started_ = false;
    finished_ = false;
    cancelled_ = false;
  }
  ClearOutputsThenSetState(State::kIdle);
}

bool PushAudioSource::NeedScheduleInternal() const {
  std::lock_guard<std::mutex> lock(input_mutex_);
  return CanProcessLocked();
}

bool PushAudioSource::CanProcessLocked() const {
  if (cancelled_) {
    return true;
  }
  const size_t required = started_ ? step_samples_ : window_samples_;
  return pending_samples_.size() >= required ||
         (finished_ && !pending_samples_.empty());
}

absl::Status PushAudioSource::ScheduleInternal() {
  SetState(State::kRunning);
  absl::Cleanup cleanup = [this] { SetState(State::kIdle); };

  std::vector<float> chunk;
  {
    std::lock_guard<std::mutex> lock(input_mutex_);
    if (cancelled_) {
      return absl::CancelledError("ASR audio input was cancelled.");
    }
    if (finished_ && pending_samples_.empty()) {
      return absl::OutOfRangeError("End of ASR audio input reached.");
    }

    const size_t required = started_ ? step_samples_ : window_samples_;
    if (pending_samples_.size() < required && !finished_) {
      return absl::NotFoundError(
          "A complete ASR inference window is not ready.");
    }

    chunk.reserve(window_samples_);
    if (started_) {
      chunk.insert(chunk.end(), overlap_.begin(), overlap_.end());
    }

    const size_t accepted_from_pending =
        std::min(required, pending_samples_.size());
    for (size_t i = 0; i < accepted_from_pending; ++i) {
      chunk.push_back(pending_samples_.front());
      pending_samples_.pop_front();
    }
    chunk.resize(window_samples_, 0.0f);

    overlap_.assign(chunk.end() - overlap_samples_, chunk.end());
    started_ = true;
  }

  PushOutput(std::move(chunk));
  return absl::OkStatus();
}

} // namespace litert_lm_native
