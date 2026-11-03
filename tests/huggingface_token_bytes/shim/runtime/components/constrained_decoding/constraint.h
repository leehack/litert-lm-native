// Grammar execution is outside the tokenizer-init seam.
#pragma once
namespace litert::lm {
class Constraint {
 public:
  virtual ~Constraint() = default;
};
}  // namespace litert::lm
