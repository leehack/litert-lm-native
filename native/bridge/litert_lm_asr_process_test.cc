// Compiles the production process_next body with both upstream API shapes.
#include "bridge/litert_lm_asr_bridge.h"
#include "bridge/litert_lm_asr_session_adapter.h"
#include <cassert>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <memory>
#include <mutex>
#include <string>
#include <utility>
#include <variant>

namespace absl {
struct Status {
  int code = 0;
  bool ok() const { return code == 0; }
};
Status InvalidArgumentError(const char *) { return {1}; }
Status CancelledError(const char *) { return {2}; }
Status UnimplementedError(const char *) { return {3}; }
Status FailedPreconditionError(const char *) { return {4}; }
bool IsNotFound(Status s) { return s.code == 5; }
bool IsOutOfRange(Status s) { return s.code == 6; }
template <class T> struct StatusOr {
  T value{};
  Status error{};
  StatusOr(T v) : value(std::move(v)) {}
  StatusOr(Status s) : error(s) {}
  bool ok() const { return error.ok(); }
  Status status() const { return error; }
  const T &operator*() const { return value; }
};
} // namespace absl
struct UpstreamMergeResult {
  std::string confirmed_text, unconfirmed_text;
};
struct End {};
struct Audio {};
#if TEST_OMNI_API
using Output = std::variant<End, UpstreamMergeResult, Audio>;
#else
using Output = UpstreamMergeResult;
#endif
struct AudioSource {
  bool cancelled = false, can_process = false, drained = false;
  bool IsCancelled() const { return cancelled; }
  bool CanProcess() const { return can_process; }
  bool IsFinishedAndDrained() const { return drained; }
};
struct TestSession {
  absl::StatusOr<Output> next{Output{UpstreamMergeResult{"text", "partial"}}};
  absl::StatusOr<Output> flush{Output{UpstreamMergeResult{"final", ""}}};
  std::shared_ptr<AudioSource> source;
  bool drain_on_process = false;
  int next_calls = 0, flush_calls = 0;
#if TEST_OMNI_API
  absl::StatusOr<Output> ProcessNext(){
#else
  absl::StatusOr<Output> ProcessNextChunk() {
#endif
      ++next_calls;
  if (drain_on_process)
    source->drained = true;
  return next;
} absl::StatusOr<Output> Flush() {
  ++flush_calls;
  return flush;
}
}
;
struct LitertLmAsrSession {
  std::shared_ptr<AudioSource> audio_source = std::make_shared<AudioSource>();
  std::shared_ptr<TestSession> session = std::make_shared<TestSession>();
  std::mutex process_mutex;
  bool final_result_returned = false;
  LitertLmAsrSession() { session->source = audio_source; }
};
void ClearError(char **) {}
LitertLmAsrStatus ReturnStatus(absl::Status s, char **) {
  if (s.ok())
    return LITERT_LM_ASR_STATUS_OK;
  if (s.code == 1)
    return LITERT_LM_ASR_STATUS_INVALID_ARGUMENT;
  if (s.code == 2)
    return LITERT_LM_ASR_STATUS_CANCELLED;
  if (s.code == 4)
    return LITERT_LM_ASR_STATUS_FAILED_PRECONDITION;
  return LITERT_LM_ASR_STATUS_INTERNAL;
}
LitertLmAsrStatus ReturnInternalException(const char *, const std::exception *,
                                          char **) {
  return LITERT_LM_ASR_STATUS_INTERNAL;
}
absl::Status PopulateResult(const UpstreamMergeResult &source, bool final,
                            LitertLmAsrResult *out) {
  out->confirmed_text = strdup(source.confirmed_text.c_str());
  out->unconfirmed_text = strdup(source.unconfirmed_text.c_str());
  out->is_final = final;
  return {};
}

// PRODUCTION_PROCESS_NEXT

int main() {
  LitertLmAsrResult out{};
  out.struct_size = sizeof(out);
  auto release = [&] {
    free(out.confirmed_text);
    free(out.unconfirmed_text);
    out.confirmed_text = out.unconfirmed_text = nullptr;
    out.is_final = 0;
  };
  auto call = [&](LitertLmAsrSession &s) {
    return litert_lm_asr_session_process_next(&s, &out, nullptr);
  };
  LitertLmAsrSession streaming;
  assert(call(streaming) == LITERT_LM_ASR_STATUS_NEEDS_MORE_AUDIO);
  assert(streaming.session->next_calls == 0 &&
         streaming.session->flush_calls == 0);
  streaming.audio_source->can_process = true;
  assert(call(streaming) == LITERT_LM_ASR_STATUS_OK && !out.is_final);
  assert(std::string(out.confirmed_text) == "text" &&
         std::string(out.unconfirmed_text) == "partial");
  release();
  streaming.audio_source->can_process = false;
  streaming.audio_source->drained = true;
  assert(call(streaming) == LITERT_LM_ASR_STATUS_OK && out.is_final);
  assert(std::string(out.confirmed_text) == "final");
  release();
  assert(call(streaming) == LITERT_LM_ASR_STATUS_END_OF_STREAM);
  assert(streaming.session->flush_calls == 1);
  LitertLmAsrSession cancelled;
  cancelled.audio_source->cancelled = true;
  assert(call(cancelled) == LITERT_LM_ASR_STATUS_CANCELLED);
  assert(cancelled.session->next_calls == 0);
  for (int error : {5, 6}) {
    LitertLmAsrSession empty;
    empty.audio_source->drained = true;
    empty.session->flush = absl::Status{error};
    assert(call(empty) == LITERT_LM_ASR_STATUS_OK && out.is_final);
    assert(std::string(out.confirmed_text).empty());
    release();
  }
  LitertLmAsrSession pending;
  pending.audio_source->can_process = true;
  pending.session->next = absl::Status{5};
  assert(call(pending) == LITERT_LM_ASR_STATUS_NEEDS_MORE_AUDIO);
  assert(pending.session->flush_calls == 0);
  pending.session->next = absl::Status{6};
  assert(call(pending) == LITERT_LM_ASR_STATUS_INTERNAL);
  assert(pending.session->flush_calls == 0 && !pending.final_result_returned);
  LitertLmAsrSession failed;
  failed.audio_source->drained = true;
  failed.session->flush = absl::Status{3};
  assert(call(failed) == LITERT_LM_ASR_STATUS_INTERNAL);
  assert(!failed.final_result_returned && !out.is_final);
#if TEST_OMNI_API
  for (bool flush : {false, true}) {
    LitertLmAsrSession audio;
    audio.audio_source->can_process = !flush;
    audio.audio_source->drained = flush;
    if (flush)
      audio.session->flush = Output{Audio{}};
    else
      audio.session->next = Output{Audio{}};
    assert(call(audio) == LITERT_LM_ASR_STATUS_INTERNAL);
    assert(!audio.final_result_returned && !out.is_final);
  }
  LitertLmAsrSession premature;
  premature.audio_source->can_process = true;
  premature.session->next = Output{End{}};
  assert(call(premature) == LITERT_LM_ASR_STATUS_FAILED_PRECONDITION);
  assert(premature.session->flush_calls == 0);
  for (bool range : {false, true}) {
    LitertLmAsrSession ended;
    ended.audio_source->can_process = true;
    ended.session->drain_on_process = true;
    ended.session->next = range ? absl::StatusOr<Output>(absl::Status{6})
                                : absl::StatusOr<Output>(Output{End{}});
    assert(call(ended) == LITERT_LM_ASR_STATUS_OK && out.is_final);
    assert(std::string(out.confirmed_text) == "final");
    release();
    assert(call(ended) == LITERT_LM_ASR_STATUS_END_OF_STREAM);
    assert(ended.session->flush_calls == 1);
  }
  LitertLmAsrSession empty_end;
  empty_end.audio_source->drained = true;
  empty_end.session->flush = Output{End{}};
  assert(call(empty_end) == LITERT_LM_ASR_STATUS_OK && out.is_final);
  assert(std::string(out.confirmed_text).empty());
  release();
#endif
}
