// Model-free stage replay and regression tests for the carried v0.18 ASR fix.
#include <cstdlib>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#include "omni/asr/timestamp_text_merger.h"

using litert::omni::SingleThreadedStageWithDeque;
using litert::omni::asr::TimestampTextMerger;
using litert::omni::asr::Word;

class FixtureWords : public SingleThreadedStageWithDeque<std::vector<Word>> {
 public:
  void Add(const std::string& text) {
    std::istringstream input(text);
    std::vector<Word> words;
    for (std::string w; input >> w;) {
      // Optional @milliseconds lets differential tests exercise timed models.
      auto at = w.rfind('@');
      words.push_back(at == std::string::npos
                          ? Word{w, std::nullopt}
                          : Word{w.substr(0, at), std::stoi(w.substr(at + 1))});
    }
    PushOutput(std::move(words));
  }

 private:
  bool NeedScheduleInternal() const override { return false; }
  absl::Status ScheduleInternal() override { return absl::OkStatus(); }
};

std::string Replay(const std::vector<std::string>& windows, float overlap,
                   bool states = false) {
  FixtureWords words;
  TimestampTextMerger merger(&words, overlap);
  std::string transcript;
  auto drain = [&]() {
    while (merger.HasOutput()) {
      auto o = merger.GetOutput().value();
      if (states) {
        transcript += "[" + o.confirmed_text + "|" + o.unconfirmed_text + "]";
      } else if (!o.confirmed_text.empty()) {
        if (!transcript.empty()) transcript += " ";
        transcript += o.confirmed_text;
      }
    }
  };
  for (const auto& w : windows) {
    words.Add(w);
    if (!merger.Schedule().ok()) std::abort();
    drain();
  }
  if (!merger.Flush().ok()) std::abort();
  drain();
  if (!merger.Flush().ok() || merger.HasOutput()) std::abort();
  merger.Reset();
  words.Add("reset reset keeps repeats");
  if (!merger.Schedule().ok()) std::abort();
  auto result = merger.GetOutput().value();
  if (overlap > 0 && result.unconfirmed_text != "reset reset keeps repeats")
    std::abort();
  return transcript;
}

void Expect(const std::vector<std::string>& windows,
            const std::string& expected, float overlap = 0.4f) {
  auto actual = Replay(windows, overlap);
  if (actual != expected) {
    std::cerr << "expected: " << expected << "\nactual: " << actual << "\n";
    std::exit(1);
  }
}

int main(int argc, char** argv) {
  if (argc == 1) {
    Expect({"And so my fellow Americans ask not.",
            "ask not. what your country can do for you.",
            "One tree can do for you, ask what you can do for your country."},
           "And so my fellow Americans ask not. what your country can do for "
           "you. ask what you can do for your country.");
    Expect(
        {"say very very loudly now", "very very loudly now please please stop"},
        "say very very loudly now please please stop");
    Expect({"we go now we go now", "we go now and rest"},
           "we go now we go now and rest");
    Expect({"we can do for you uh", "One tree can do for you ask again again"},
           "we can do for you ask again again");
    Expect({"a clean window ends here", "ends here and keeps going"},
           "a clean window ends here and keeps going");
    Expect({"Go go, never never stop."}, "Go go, never never stop.");
    Expect({"go go", "go go"}, "go go go go", 0.0f);
    Expect({"", "Go go, never never stop.", ""}, "Go go, never never stop.");
    return 0;
  }
  float overlap = std::stof(argv[1]);
  bool states = argc > 2 && std::string(argv[2]) == "--states";
  std::vector<std::string> windows;
  for (std::string line; std::getline(std::cin, line);) {
    if (line == "===") {
      std::cout << Replay(windows, overlap, states) << '\n';
      windows.clear();
    } else {
      windows.push_back(line);
    }
  }
  if (!windows.empty()) std::cout << Replay(windows, overlap, states) << '\n';
}
