#ifndef LITERT_LM_ASR_SESSION_ADAPTER_H_
#define LITERT_LM_ASR_SESSION_ADAPTER_H_

#include <variant>

namespace litert_lm_native {

enum class AsrOutputKind { kText, kEnd, kUnsupported };

template <typename Text> struct AsrOutputView {
  AsrOutputKind kind;
  const Text *text;
};

// Older ASR sessions return MergeResult directly; OmniSession returns a
// variant.
template <typename Text> AsrOutputView<Text> ViewAsrOutput(const Text &output) {
  return {AsrOutputKind::kText, &output};
}

template <typename End, typename Text, typename Audio>
AsrOutputView<Text>
ViewAsrOutput(const std::variant<End, Text, Audio> &output) {
  if (const auto *text = std::get_if<Text>(&output)) {
    return {AsrOutputKind::kText, text};
  }
  return {std::holds_alternative<End>(output) ? AsrOutputKind::kEnd
                                              : AsrOutputKind::kUnsupported,
          nullptr};
}

template <typename Session>
auto ProcessAsrNextImpl(Session &session, int)
    -> decltype(session.ProcessNextChunk()) {
  return session.ProcessNextChunk();
}

template <typename Session>
auto ProcessAsrNextImpl(Session &session, long)
    -> decltype(session.ProcessNext()) {
  return session.ProcessNext();
}

template <typename Session> auto ProcessAsrNext(Session &session) {
  return ProcessAsrNextImpl(session, 0);
}

} // namespace litert_lm_native
#endif // LITERT_LM_ASR_SESSION_ADAPTER_H_
