#include "litert_lm_asr_session_adapter.h"

#include <cassert>
#include <string>
#include <variant>

struct Text {
  std::string confirmed_text;
  std::string unconfirmed_text;
};
struct End {};
struct Audio {};
using Output = std::variant<End, Text, Audio>;
struct LegacySession {
  int calls = 0;
  Text ProcessNextChunk() {
    ++calls;
    return {"legacy", "partial"};
  }
};
struct OmniSession {
  int calls = 0;
  Output ProcessNext() {
    ++calls;
    return Text{"omni", "partial"};
  }
};

int main() {
  using namespace litert_lm_native;
  LegacySession legacy;
  const auto old_result = ProcessAsrNext(legacy);
  const auto old_view = ViewAsrOutput(old_result);
  assert(legacy.calls == 1 && old_view.kind == AsrOutputKind::kText);
  assert(old_view.text->confirmed_text == "legacy");
  assert(old_view.text->unconfirmed_text == "partial");
  OmniSession omni;
  const auto result = ProcessAsrNext(omni);
  const auto view = ViewAsrOutput(result);
  assert(omni.calls == 1 && view.kind == AsrOutputKind::kText);
  assert(view.text->confirmed_text == "omni" &&
         view.text->unconfirmed_text == "partial");
  Output end = End{};
  assert(ViewAsrOutput(end).kind == AsrOutputKind::kEnd);
  assert(ViewAsrOutput(end).text == nullptr);
  Output audio = Audio{};
  assert(ViewAsrOutput(audio).kind == AsrOutputKind::kUnsupported);
  assert(ViewAsrOutput(audio).text == nullptr);
  Output empty = Text{};
  assert(ViewAsrOutput(empty).kind == AsrOutputKind::kText);
  assert(ViewAsrOutput(empty).text->confirmed_text.empty());
}
