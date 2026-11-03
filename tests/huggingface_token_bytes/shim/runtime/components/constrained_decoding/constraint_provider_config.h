#pragma once
#include <variant>

#include "runtime/components/constrained_decoding/llg_constraint_config.h"
namespace litert::lm {
using ConstraintArg = std::variant<int, LlGuidanceConstraintArg>;
}
