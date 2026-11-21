// Copyright 2026 Google LLC.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#include <cstdint>
#include <memory>
#include <vector>

#include <gmock/gmock.h>
#include <gtest/gtest.h>

#include "absl/status/status.h"
#include "absl/status/status_matchers.h"
#include "absl/synchronization/mutex.h"
#include "ml_drift/common/data_type.h"
#include "ml_drift/common/gpu_model.h"
#include "ml_drift/common/gpu_model_builder.h"
#include "ml_drift/common/model.h"
#include "ml_drift/common/model_hints.h"
#include "ml_drift/common/precision.h"
#include "ml_drift/common/shape.h"
#include "ml_drift/common/task/tensor_desc.h"
#include "ml_drift/common/tensor.h"
#include "ml_drift/webgpu/execution_environment.h"
#include "ml_drift/webgpu/inference_context.h"
#include "ml_drift/webgpu/spatial_tensor.h"
#include "ml_drift_delegate/delegate/gpu_backend.h"
#include "ml_drift_delegate/delegate/gpu_backend_webgpu.h"

namespace litert::ml_drift {
namespace {

namespace drift = ::ml_drift;
using ::absl_testing::IsOk;
using ::absl_testing::IsOkAndHolds;
using ::absl_testing::StatusIs;
using ::testing::ElementsAre;

class SpatialTensorBindingsTest : public ::testing::Test {
protected:
  void Initialize(int cached_steps) {
    ASSERT_THAT(backend_.wgpu_env().Initialize(), IsOk());
    backend_.set_num_steps_of_command_buffer_preparations(cached_steps);

    drift::CreateGpuModelInfo create_info;
    create_info.precision = drift::CalculationsPrecision::kF32;
    create_info.storage_type = drift::TensorStorageType::kBuffer;
    create_info.hints.Add(drift::ModelHints::kFastTuning);
    drift::GpuModelBuilder builder(backend_.wgpu_env().GetInfo(),
                                   create_info.hints, create_info.precision,
                                   create_info.storage_type);
    const auto input =
        builder.AddTensor(drift::BHWC(1, 1, 1, 4), drift::DataType::kFloat32);
    auto output = input;
    for (int i = 0; i < 8; ++i) {
      output = builder.Multiplication(output, 2.0f);
      output = builder.Add(output, 1.0f);
    }
    drift::GpuModel model;
    ASSERT_THAT(builder.GetGpuModel(std::vector<uint32_t>{input.id},
                                    std::vector<uint32_t>{output.id}, &model),
                IsOk());
    input_id_ = input.id;
    output_id_ = output.id;
    auto input_desc = model.tensors.at(input_id_);
    output_desc_ = model.tensors.at(output_id_);
    create_info.external_mutable_tensors[input_id_] = input_desc;
    create_info.external_mutable_tensors[output_id_] = output_desc_;

    const auto &device = backend_.wgpu_env().device();
    drift::TensorFloat32 input_cpu;
    input_cpu.shape = drift::BHWC(1, 1, 1, 4);
    input_cpu.data = {0, 0, 0, 0};
    input_desc.UploadData(input_cpu);
    ASSERT_THAT(input_a_.CreateFromDescriptor(device, input_desc), IsOk());
    input_cpu.data = {1, 1, 1, 1};
    input_desc.UploadData(input_cpu);
    ASSERT_THAT(input_b_.CreateFromDescriptor(device, input_desc), IsOk());
    ASSERT_THAT(CreateTensor(device, output_desc_, &output_a_), IsOk());
    ASSERT_THAT(CreateTensor(device, output_desc_, &output_b_), IsOk());

    input_cpu.data = {2, 2, 2, 2};
    updated_input_desc_ = input_desc;
    updated_input_desc_.UploadData(input_cpu);

    auto context = backend_.CreateInferenceContext(
        create_info, model, /*serialized_model=*/nullptr,
        /*may_share_memory_manager=*/true);
    ASSERT_THAT(context.status(), IsOk());
    context_ = *std::move(context);
    ASSERT_THAT(context_->SetCommandBufferHint(4), IsOk());
  }

  void Bind(drift::webgpu::SpatialTensor &input,
            drift::webgpu::SpatialTensor &output) {
    ASSERT_THAT(context_->BindSpatialTensor(input_id_, &input), IsOk());
    ASSERT_THAT(context_->BindSpatialTensor(output_id_, &output), IsOk());
  }

  void ExpectUnderlyingBindings(drift::webgpu::SpatialTensor &input,
                                drift::webgpu::SpatialTensor &output) {
    absl::MutexLock lock(backend_.memory_manager_mutex());
    auto &wgpu_context =
        static_cast<GpuInferenceContextWebGpu &>(*context_).wgpu_ctx();
    EXPECT_EQ(wgpu_context.GetTensor(input_id_), &input);
    EXPECT_EQ(wgpu_context.GetTensor(output_id_), &output);
  }

  void ExpectOutput(drift::webgpu::SpatialTensor &tensor, float expected) {
    ASSERT_THAT(backend_.WaitForCompletion(), IsOk());
    auto descriptor = output_desc_;
    ASSERT_THAT(tensor.ToDescriptor(backend_.wgpu_env().device(), &descriptor),
                IsOk());
    drift::TensorFloat32 output_cpu;
    descriptor.DownloadData(&output_cpu);
    EXPECT_THAT(output_cpu.data,
                ElementsAre(expected, expected, expected, expected));
  }

  GpuBackendWebGpu backend_;
  drift::ValueId input_id_;
  drift::ValueId output_id_;
  drift::TensorDescriptor output_desc_;
  drift::TensorDescriptor updated_input_desc_;
  drift::webgpu::SpatialTensor input_a_;
  drift::webgpu::SpatialTensor output_a_;
  drift::webgpu::SpatialTensor input_b_;
  drift::webgpu::SpatialTensor output_b_;
  std::unique_ptr<GpuInferenceContext> context_;
};

TEST_F(SpatialTensorBindingsTest, StagesBindingsWhenPreparingBuffers) {
  ASSERT_NO_FATAL_FAILURE(Initialize(2));
  ASSERT_NO_FATAL_FAILURE(Bind(input_a_, output_a_));
  ASSERT_THAT(context_->Dispatch(), IsOk());
  ASSERT_NO_FATAL_FAILURE(Bind(input_b_, output_b_));

  EXPECT_THAT(context_->GetSpatialTensor(input_id_), IsOkAndHolds(&input_b_));
  EXPECT_THAT(context_->GetSpatialTensor(output_id_), IsOkAndHolds(&output_b_));
  ExpectUnderlyingBindings(input_a_, output_a_);
}

TEST_F(SpatialTensorBindingsTest, RejectsHintChangesAfterDispatch) {
  ASSERT_NO_FATAL_FAILURE(Initialize(2));
  ASSERT_NO_FATAL_FAILURE(Bind(input_a_, output_a_));
  ASSERT_THAT(context_->Dispatch(), IsOk());

  EXPECT_THAT(context_->SetCommandBufferHint(8),
              StatusIs(absl::StatusCode::kFailedPrecondition));
}

TEST_F(SpatialTensorBindingsTest, CachedBuffersUseTheirOwnBindings) {
  ASSERT_NO_FATAL_FAILURE(Initialize(2));
  for (int step = 0; step < 20; ++step) {
    if (step == 2) {
      // A fresh value distinguishes replaying slot zero from retaining its
      // initial output when the cached buffer points to slot one's tensors.
      ASSERT_THAT(backend_.WaitForCompletion(), IsOk());
      ASSERT_THAT(input_a_.UploadDescriptorData(backend_.wgpu_env().queue(),
                                                updated_input_desc_),
                  IsOk());
    }
    if (step % 2 == 0) {
      ASSERT_NO_FATAL_FAILURE(Bind(input_a_, output_a_));
    } else {
      ASSERT_NO_FATAL_FAILURE(Bind(input_b_, output_b_));
    }
    ASSERT_THAT(context_->Dispatch(), IsOk());
    if (step == 2) {
      ASSERT_NO_FATAL_FAILURE(ExpectOutput(output_a_, 767.0f));
    }
  }
  ASSERT_NO_FATAL_FAILURE(ExpectOutput(output_a_, 767.0f));
  ASSERT_NO_FATAL_FAILURE(ExpectOutput(output_b_, 511.0f));
}

TEST_F(SpatialTensorBindingsTest, UncachedBuffersBindImmediately) {
  ASSERT_NO_FATAL_FAILURE(Initialize(0));
  ASSERT_NO_FATAL_FAILURE(Bind(input_b_, output_b_));
  ExpectUnderlyingBindings(input_b_, output_b_);
  ASSERT_THAT(context_->Dispatch(), IsOk());
  ASSERT_NO_FATAL_FAILURE(ExpectOutput(output_b_, 511.0f));
}

} // namespace
} // namespace litert::ml_drift
