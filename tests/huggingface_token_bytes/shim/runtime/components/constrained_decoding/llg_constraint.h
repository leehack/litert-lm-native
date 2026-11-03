#pragma once
#include "llguidance.h"
#include "runtime/components/constrained_decoding/constraint.h"
namespace litert::lm {
class LlgConstraint : public Constraint {
 public:
  LlgConstraint(::LlgConstraint*, int, int) {}
};
}  // namespace litert::lm
