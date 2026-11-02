#include "bridge/litert_lm_asr_omni_input_source.h"

#include <cstdlib>
#include <iostream>
#include <variant>
#include <vector>

namespace {
void Require(bool condition, const char* message) {
  if (!condition) {
    std::cerr << message << '\n';
    std::exit(1);
  }
}

using Source = litert_lm_native::PushAudioSource;
using Session = litert::omni::OmniSession;

std::vector<float> ReadAudio(Source& source) {
  Require(source.Schedule().ok(), "schedule audio");
  auto output = source.GetOutput();
  Require(output.ok() && std::holds_alternative<Session::AudioInput>(*output),
          "audio variant");
  return std::get<Session::AudioInput>(*output).pcm_samples;
}
}  // namespace

int main() {
  Source source(10, 1, 1000, 0.2f, 1000);
  const std::vector<float> samples = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11};
  Require(!source.NeedSchedule(), "empty source must not schedule");
  Require(absl::IsNotFound(source.Schedule()), "empty input is not EOF");
  Require(source.IsIdle(), "empty scheduling restores idle");
  Require(source.Push(samples.data(), samples.size()) == 10, "bounded capacity");
  Require(source.Push(samples.data(), 1) == 0, "full queue backpressure");
  Require(ReadAudio(source) == std::vector<float>({0, 1, 2, 3, 4, 5, 6, 7}),
          "one step only; upstream owns overlap");
  Require(source.Push(samples.data() + 10, 2) == 2, "capacity recovers after drain");
  Require(source.Finish().ok(), "finish accepted");
  Require(absl::IsFailedPrecondition(source.Finish()), "duplicate finish rejected");
  Require(source.Push(samples.data(), 1) == 0, "push after finish rejected");
  Require(!source.IsFinishedAndDrained(), "remaining samples precede EOF");
  Require(ReadAudio(source) == std::vector<float>({8, 9, 10, 11}),
          "tail preserved without padding or duplicated overlap");
  Require(source.IsFinishedAndDrained(), "finished queue drained");
  Require(source.NeedSchedule(), "EOF still needs delivery");
  Require(source.Schedule().ok(), "schedule EOF");
  auto eof = source.GetOutput();
  Require(eof.ok() && std::holds_alternative<Session::EndOfInput>(*eof), "EOF variant");
  Require(!source.NeedSchedule(), "EOF delivered once");
  Require(absl::IsOutOfRange(source.Schedule()), "after EOF is exhausted");
  Require(source.IsIdle(), "EOF scheduling restores idle");

  source.Reset();
  Require(!source.IsFinished() && !source.IsCancelled() && !source.HasOutput(),
          "reset clears terminal state");
  Require(source.Push(samples.data(), 10) == 10, "reset restores capacity");
  Require(source.Schedule().ok() && source.HasOutput(), "queue output before reset");
  source.Reset();
  Require(!source.HasOutput() && !source.NeedSchedule(), "reset drops old PCM and output");
  source.Cancel();
  Require(source.IsCancelled(), "cancel state");
  Require(source.Push(samples.data(), 1) == 0, "push after cancel rejected");
  Require(absl::IsCancelled(source.Finish()), "finish after cancel rejected");
  Require(absl::IsCancelled(source.Schedule()), "cancelled scheduling reports cancellation");
  Require(source.IsIdle(), "cancel scheduling restores idle");
  source.Reset();
  Require(source.Push(samples.data(), 2) == 2, "reuse after cancel");
  Require(ReadAudio(source) == std::vector<float>({0, 1}), "no stale cancelled data");
  Require(source.Finish().ok() && source.Schedule().ok(), "reuse emits EOF");
  source.Reset();
  Require(!source.HasOutput() && !source.IsFinished(), "reset drops queued EOF");
  std::cout << "Omni push-source lifecycle checks passed\n";
}
