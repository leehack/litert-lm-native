#pragma once
#include "llguidance.h"
#include "runtime/components/constrained_decoding/constraint.h"
namespace litert::lm {
inline ::LlgConstraint* captured_created_constraint = nullptr;
class LlgConstraint : public Constraint {
 public:
  LlgConstraint(::LlgConstraint* value, int, int) {
    captured_created_constraint = value;
  }
};
}  // namespace litert::lm
