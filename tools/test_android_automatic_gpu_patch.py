import json
import unittest

from android_automatic_gpu_patch import verify_executor_compile_actions

EXECUTORS = (
    "audio_litert_compiled_model_executor",
    "litert_compiled_model_executor_utils",
    "llm_executor_settings_utils",
    "vision_litert_compiled_model_executor",
)


class AndroidGpuCompileActionsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.graph = {
            "targets": [{"id": index, "label": f"//runtime/executor:{name}"}
                        for index, name in enumerate(EXECUTORS, 1)],
            "actions": [{"targetId": index, "arguments": ["clang", "-DANDROID"]}
                        for index in range(1, len(EXECUTORS) + 1)],
        }

    def test_accepts_automatic_selection_in_all_executors(self) -> None:
        verify_executor_compile_actions(json.dumps(self.graph))

    def test_rejects_a_forced_backend_in_each_executor(self) -> None:
        for action, executor in zip(self.graph["actions"], EXECUTORS):
            with self.subTest(executor=executor):
                action["arguments"].append("-DLITERT_USE_WEBGPU_ACCELERATOR")
                with self.assertRaisesRegex(RuntimeError, f"forced to WebGPU in .*{executor}"):
                    verify_executor_compile_actions(json.dumps(self.graph))
                action["arguments"].pop()

    def test_rejects_a_forced_backend_in_a_parameter_file(self) -> None:
        self.graph["actions"][0]["paramFiles"] = [{
            "arguments": ["-D", "LITERT_USE_WEBGPU_ACCELERATOR=0"],
        }]
        with self.assertRaisesRegex(RuntimeError, "forced to WebGPU"):
            verify_executor_compile_actions(json.dumps(self.graph))

    def test_rejects_a_missing_executor_compile_action(self) -> None:
        self.graph["actions"].pop()
        with self.assertRaisesRegex(RuntimeError, "missing for .*vision_litert_compiled_model_executor"):
            verify_executor_compile_actions(json.dumps(self.graph))
