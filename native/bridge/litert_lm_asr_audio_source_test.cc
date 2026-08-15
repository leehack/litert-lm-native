#include "bridge/litert_lm_asr_audio_source.h"

#include <cstddef>
#include <vector>

#include "absl/status/status.h"
#include "gtest/gtest.h"

namespace litert_lm_native {
namespace {

TEST(PushAudioSourceTest, ProducesOverlappingWindows) {
  PushAudioSource source(/*sample_rate_hz=*/10, /*num_channels=*/1,
                         /*input_milliseconds=*/1000, /*overlap_ratio=*/0.2f,
                         /*max_buffered_audio_milliseconds=*/2000);
  const std::vector<float> first = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9};
  EXPECT_EQ(source.Push(first.data(), first.size()), first.size());
  ASSERT_TRUE(source.CanProcess());
  ASSERT_TRUE(source.Schedule().ok());
  ASSERT_TRUE(source.HasOutput());
  auto first_output = source.GetOutput();
  ASSERT_TRUE(first_output.ok());
  EXPECT_EQ(*first_output, first);

  const std::vector<float> second = {10, 11, 12, 13, 14, 15, 16, 17};
  EXPECT_EQ(source.Push(second.data(), second.size()), second.size());
  ASSERT_TRUE(source.Schedule().ok());
  auto second_output = source.GetOutput();
  ASSERT_TRUE(second_output.ok());
  EXPECT_EQ(*second_output,
            (std::vector<float>{8, 9, 10, 11, 12, 13, 14, 15, 16, 17}));

  EXPECT_TRUE(source.Finish().ok());
  EXPECT_TRUE(source.IsFinishedAndDrained());
  EXPECT_TRUE(absl::IsOutOfRange(source.Schedule()));
}

TEST(PushAudioSourceTest, PadsFinalPartialWindow) {
  PushAudioSource source(/*sample_rate_hz=*/10, /*num_channels=*/1,
                         /*input_milliseconds=*/1000, /*overlap_ratio=*/0.2f,
                         /*max_buffered_audio_milliseconds=*/2000);
  const std::vector<float> samples = {1, 2, 3};
  EXPECT_EQ(source.Push(samples.data(), samples.size()), samples.size());
  EXPECT_FALSE(source.CanProcess());
  EXPECT_TRUE(source.Finish().ok());
  EXPECT_TRUE(source.CanProcess());
  ASSERT_TRUE(source.Schedule().ok());
  auto output = source.GetOutput();
  ASSERT_TRUE(output.ok());
  EXPECT_EQ(*output, (std::vector<float>{1, 2, 3, 0, 0, 0, 0, 0, 0, 0}));
  EXPECT_TRUE(source.IsFinishedAndDrained());
}

TEST(PushAudioSourceTest, AppliesBoundedBackpressure) {
  PushAudioSource source(/*sample_rate_hz=*/10, /*num_channels=*/1,
                         /*input_milliseconds=*/1000, /*overlap_ratio=*/0.0f,
                         /*max_buffered_audio_milliseconds=*/1000);
  const std::vector<float> samples(12, 0.5f);
  EXPECT_EQ(source.Push(samples.data(), samples.size()), 10u);
  EXPECT_EQ(source.Push(samples.data(), 1), 0u);
  ASSERT_TRUE(source.Schedule().ok());
  EXPECT_EQ(source.Push(samples.data() + 10, 2), 2u);
}

TEST(PushAudioSourceTest, CancelAndResetAreReusable) {
  PushAudioSource source(/*sample_rate_hz=*/10, /*num_channels=*/1,
                         /*input_milliseconds=*/1000, /*overlap_ratio=*/0.0f,
                         /*max_buffered_audio_milliseconds=*/1000);
  const std::vector<float> samples(10, 0.5f);
  EXPECT_EQ(source.Push(samples.data(), samples.size()), samples.size());
  source.Cancel();
  EXPECT_TRUE(source.IsCancelled());
  EXPECT_TRUE(absl::IsCancelled(source.Schedule()));

  source.Reset();
  EXPECT_FALSE(source.IsCancelled());
  EXPECT_EQ(source.Push(samples.data(), samples.size()), samples.size());
  EXPECT_TRUE(source.Schedule().ok());
}

} // namespace
} // namespace litert_lm_native
