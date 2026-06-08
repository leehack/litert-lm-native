#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path

from runtime_dependency_utils import elf_needed_libraries, is_elf, is_system_needed

REPO_ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"
STREAM_PROXY_SOURCE = REPO_ROOT / "native" / "stream_proxy" / "stream_proxy.c"
UPSTREAM_REPO = "google-ai-edge/LiteRT-LM"
MACOS_MINIMUM_OS = "14.0"
UPSTREAM_ARCHIVE_URL = (
    "https://github.com/google-ai-edge/LiteRT-LM/archive/refs/tags/{tag}.tar.gz"
)

RUNTIME_TARGETS = {
    ("android", "arm64"): {
        "bazel_target": "//c:libLiteRtLm.so",
        "bazel_config": "android_arm64",
        "bazel_options": [
            "--linkopt=-Wl,-z,max-page-size=16384",
            "--linkopt=-Wl,-z,common-page-size=16384",
        ],
        "output": "bazel-bin/c/libLiteRtLm.so",
        "library": "libLiteRtLm.so",
    },
    ("android", "x64"): {
        "bazel_target": "//c:libLiteRtLm.so",
        "bazel_config": "android_x86_64",
        "bazel_options": [
            "--linkopt=-Wl,-z,max-page-size=16384",
            "--linkopt=-Wl,-z,common-page-size=16384",
        ],
        "output": "bazel-bin/c/libLiteRtLm.so",
        "library": "libLiteRtLm.so",
    },
    ("linux", "arm64"): {
        "bazel_target": "//c:libLiteRtLm.so",
        "bazel_configs": ["linux", "linux_arm64"],
        "output": "bazel-bin/c/libLiteRtLm.so",
        "library": "libLiteRtLm.so",
    },
    ("linux", "x64"): {
        "bazel_target": "//c:libLiteRtLm.so",
        "bazel_config": "linux",
        "output": "bazel-bin/c/libLiteRtLm.so",
        "library": "libLiteRtLm.so",
    },
    ("macos", "arm64"): {
        "bazel_target": "//c:libLiteRtLm.dylib",
        "bazel_configs": ["macos", "macos_arm64"],
        "output": "bazel-bin/c/libLiteRtLm.dylib",
        "library": "libLiteRtLm.dylib",
    },
    ("macos", "x64"): {
        "bazel_target": "//c:libLiteRtLm.dylib",
        "bazel_config": "macos",
        "bazel_options": [
            "--cpu=darwin_x86_64",
            "--platforms=@build_bazel_apple_support//platforms:darwin_x86_64",
        ],
        "output": "bazel-bin/c/libLiteRtLm.dylib",
        "library": "libLiteRtLm.dylib",
    },
    ("windows", "x64"): {
        "bazel_target": "//c:LiteRtLm.dll",
        "bazel_config": "windows",
        "output": "bazel-bin/c/LiteRtLm.dll",
        "library": "LiteRtLm.dll",
    },
}

REQUIRED_C_API_SYMBOLS = [
    b"litert_lm_engine_settings_create",
    b"litert_lm_engine_create",
    b"litert_lm_session_config_set_lora_file",
    b"litert_lm_session_config_set_audio_lora_file",
    b"litert_lm_conversation_create",
    b"litert_lm_conversation_send_message_stream",
]

REQUIRED_STREAM_PROXY_SYMBOLS = [
    b"stream_proxy_load_global",
    b"stream_proxy_create",
    b"stream_proxy_delete",
    b"stream_proxy_free_string",
]

SHARED_TARGETS = """

# Added by litert-lm-native packaging. Upstream publishes the C API as a static
# cc_library for most platforms; Dart/Flutter FFI needs a loadable library.
cc_library(
    name = "stream_proxy",
    srcs = ["stream_proxy.c"],
    alwayslink = True,
    linkopts = select({
        "@platforms//os:android": ["-ldl"],
        "@platforms//os:linux": ["-ldl"],
        "//conditions:default": [],
    }),
)

cc_binary(
    name = "libLiteRtLm.so",
    linkshared = True,
    deps = [
        ":engine",
        ":stream_proxy",
        "//schema/capabilities:capabilities_c",
    ],
)

cc_binary(
    name = "libLiteRtLm.dylib",
    linkshared = True,
    deps = [
        ":engine",
        ":stream_proxy",
        "//schema/capabilities:capabilities_c",
    ],
)

cc_binary(
    name = "LiteRtLm.dll",
    linkshared = True,
    deps = [
        ":engine",
        ":stream_proxy",
        "//schema/capabilities:capabilities_c",
    ],
)
"""


def run(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    printable = " ".join(command)
    print(f"+ {printable}", flush=True)
    if os.name == "nt":
        subprocess.run(printable, cwd=cwd, env=env, check=True, shell=True)
    else:
        subprocess.run(command, cwd=cwd, env=env, check=True)


def download_upstream(tag: str, work_dir: Path) -> Path:
    archive_path = work_dir / f"LiteRT-LM-{tag}.tar.gz"
    url = UPSTREAM_ARCHIVE_URL.format(tag=tag)
    print(f"Downloading {url}", flush=True)
    urllib.request.urlretrieve(url, archive_path)
    with tarfile.open(archive_path, "r:gz") as archive:
        archive.extractall(work_dir, filter="data")
    candidates = [path for path in work_dir.iterdir() if path.is_dir()]
    if len(candidates) != 1:
        raise RuntimeError(f"Expected one extracted source directory, got {candidates}")
    return candidates[0]


def _replace_once(text: str, old: str, new: str, path: Path) -> str:
    if old not in text:
        if new in text:
            return text
        raise RuntimeError(f"Could not find patch target in {path}: {old[:80]!r}")
    return text.replace(old, new, 1)


def _insert_before_once(text: str, marker: str, insertion: str, path: Path) -> str:
    if insertion + marker in text:
        return text
    if marker not in text:
        raise RuntimeError(f"Could not find insertion point in {path}: {marker[:80]!r}")
    return text.replace(marker, insertion + marker, 1)


def _insert_after_once(text: str, marker: str, insertion: str, path: Path) -> str:
    if marker + insertion in text:
        return text
    if marker not in text:
        raise RuntimeError(f"Could not find insertion point in {path}: {marker[:80]!r}")
    return text.replace(marker, marker + insertion, 1)


def patch_upstream_lora_support(source_root: Path) -> None:
    """Enable LiteRT-LM text LoRA through the C ABI."""
    c_build_path = source_root / "c" / "BUILD"
    text = c_build_path.read_text(encoding="utf-8")
    text = _insert_after_once(
        text,
        '    "//runtime/proto:token_cc_proto",\n',
        '    "//runtime/util:scoped_file",\n',
        c_build_path,
    )
    c_build_path.write_text(text, encoding="utf-8")

    engine_h_path = source_root / "c" / "engine.h"
    text = engine_h_path.read_text(encoding="utf-8")
    text = _insert_after_once(
        text,
        """void litert_lm_session_config_set_sampler_params(
    LiteRtLmSessionConfig* config, const LiteRtLmSamplerParams* sampler_params);

""",
        """// Sets a LoRA adapter file for this session config.
// @param config The config to modify.
// @param path Path to a LiteRT-LM LoRA adapter file.
// @return true when the file is opened and attached to the session config.
LITERT_LM_C_API_EXPORT
bool litert_lm_session_config_set_lora_file(LiteRtLmSessionConfig* config,
                                            const char* path);

// Sets an audio LoRA adapter file for this session config.
// @param config The config to modify.
// @param path Path to a LiteRT-LM audio LoRA adapter file.
// @return true when the file is opened and attached to the session config.
LITERT_LM_C_API_EXPORT
bool litert_lm_session_config_set_audio_lora_file(
    LiteRtLmSessionConfig* config, const char* path);

""",
        engine_h_path,
    )
    engine_h_path.write_text(text, encoding="utf-8")

    engine_cc_path = source_root / "c" / "engine.cc"
    text = engine_cc_path.read_text(encoding="utf-8")
    text = _insert_after_once(
        text,
        '#include "runtime/util/logging.h"\n',
        '#include "runtime/util/scoped_file.h"\n',
        engine_cc_path,
    )
    text = _insert_before_once(
        text,
        "void litert_lm_session_config_delete(LiteRtLmSessionConfig* config) {\n",
        """bool litert_lm_session_config_set_lora_file(
    LiteRtLmSessionConfig* config, const char* path) {
  if (!config || !config->config || !path || path[0] == '\\0') {
    ABSL_LOG(ERROR) << "Invalid session config or LoRA path";
    return false;
  }
  auto scoped_file = litert::lm::ScopedFile::Open(path);
  if (!scoped_file.ok()) {
    ABSL_LOG(ERROR) << "Failed to open LoRA file: "
                    << scoped_file.status();
    return false;
  }
  config->config->SetScopedLoraFile(
      std::make_shared<litert::lm::ScopedFile>(std::move(*scoped_file)));
  return true;
}

bool litert_lm_session_config_set_audio_lora_file(
    LiteRtLmSessionConfig* config, const char* path) {
  if (!config || !config->config || !path || path[0] == '\\0') {
    ABSL_LOG(ERROR) << "Invalid session config or audio LoRA path";
    return false;
  }
  auto scoped_file = litert::lm::ScopedFile::Open(path);
  if (!scoped_file.ok()) {
    ABSL_LOG(ERROR) << "Failed to open audio LoRA file: "
                    << scoped_file.status();
    return false;
  }
  config->config->SetAudioScopedLoraFile(
      std::make_shared<litert::lm::ScopedFile>(std::move(*scoped_file)));
  return true;
}

""",
        engine_cc_path,
    )
    engine_cc_path.write_text(text, encoding="utf-8")

    executor_build_path = source_root / "runtime" / "executor" / "BUILD"
    text = executor_build_path.read_text(encoding="utf-8")
    text = _replace_once(
        text,
        """        "//runtime/components:model_resources",
        "//runtime/components:model_resources_litert_lm",
        "//runtime/components:model_resources_task",
        "//runtime/components:sampler",
""",
        """        "//runtime/components:model_resources",
        "//runtime/components:model_resources_litert_lm",
        "//runtime/components:model_resources_task",
        "//runtime/components:lora_manager",
        "//runtime/components:sampler",
""",
        executor_build_path,
    )
    executor_build_path.write_text(text, encoding="utf-8")

    executor_base_path = (
        source_root / "runtime" / "executor" / "llm_executor_base.h"
    )
    text = executor_base_path.read_text(encoding="utf-8")
    text = _insert_after_once(
        text,
        "namespace litert::lm {\n\n",
        "class ModelAssets;\n\n",
        executor_base_path,
    )
    text = _insert_before_once(
        text,
        """  // Resets all of the internal states (e.g. KVCache). Loaded and used LoRA
  // models are not affected (remain loaded and in use).
""",
        """  // Loads a LoRA model into executor-owned resources.
  virtual absl::Status LoadLoRA(uint32_t lora_id,
                                const ModelAssets& model_assets) {
    return absl::UnimplementedError(absl::StrCat(
        "LoadLoRA not implemented for backend: ", ExecutorBackendName()));
  }

  // Selects the LoRA model to use for the active context. Passing nullopt
  // clears the active LoRA for base-model sessions.
  virtual absl::Status UseLoRA(std::optional<uint32_t> lora_id) {
    if (!lora_id.has_value()) {
      return absl::OkStatus();
    }
    return absl::UnimplementedError(absl::StrCat(
        "UseLoRA not implemented for backend: ", ExecutorBackendName()));
  }

""",
        executor_base_path,
    )
    executor_base_path.write_text(text, encoding="utf-8")

    compiled_h_path = (
        source_root
        / "runtime"
        / "executor"
        / "llm_litert_compiled_model_executor.h"
    )
    text = compiled_h_path.read_text(encoding="utf-8")
    text = _insert_after_once(
        text,
        '#include "runtime/components/embedding_lookup/embedding_lookup_manager.h"\n',
        '#include "runtime/components/lora_manager.h"\n',
        compiled_h_path,
    )
    text = _insert_after_once(
        text,
        """  absl::Status RestoreContext(
      std::unique_ptr<LlmContext> context_data) override;

""",
        """  absl::Status LoadLoRA(uint32_t lora_id,
                         const ModelAssets& model_assets) override;

  absl::Status UseLoRA(std::optional<uint32_t> lora_id) override;

""",
        compiled_h_path,
    )
    text = _insert_after_once(
        text,
        """  absl::Status BindTensorsAndRunDecode(TensorBuffer* output_logits);
""",
        """  absl::Status AppendActiveLoraInputBuffers(
      absl::flat_hash_map<absl::string_view, TensorBuffer>& input_buffers);
""",
        compiled_h_path,
    )
    text = _insert_before_once(
        text,
        """  // The MTP drafter model.
  std::unique_ptr<LlmLiteRtMtpDrafter> mtp_drafter_;
""",
        """  std::unique_ptr<LoraManager> lora_manager_;
  std::optional<uint32_t> active_lora_id_;

""",
        compiled_h_path,
    )
    compiled_h_path.write_text(text, encoding="utf-8")

    compiled_cc_path = (
        source_root
        / "runtime"
        / "executor"
        / "llm_litert_compiled_model_executor.cc"
    )
    text = compiled_cc_path.read_text(encoding="utf-8")
    text = _replace_once(
        text,
        """absl::Status LlmLiteRtCompiledModelExecutorBase::BindTensorsAndRunDecode(
    TensorBuffer* output_logits) {
  absl::flat_hash_map<absl::string_view, TensorBuffer> decode_input_buffers;
  for (const auto& [input_name, input_buffer] : decode_input_buffers_) {
    LITERT_ASSIGN_OR_RETURN(auto input_buffer_dup, input_buffer.Duplicate());
    decode_input_buffers[input_name] = std::move(input_buffer_dup);
  }
  for (const auto& [input_name, input_buffer] : *input_kv_cache_buffers_) {
    LITERT_ASSIGN_OR_RETURN(auto input_buffer_dup, input_buffer.Duplicate());
    decode_input_buffers[input_name] = std::move(input_buffer_dup);
  }
  absl::flat_hash_map<absl::string_view, TensorBuffer> decode_output_buffers;
""",
        """absl::Status LlmLiteRtCompiledModelExecutorBase::BindTensorsAndRunDecode(
    TensorBuffer* output_logits) {
  absl::flat_hash_map<absl::string_view, TensorBuffer> decode_input_buffers;
  for (const auto& [input_name, input_buffer] : decode_input_buffers_) {
    LITERT_ASSIGN_OR_RETURN(auto input_buffer_dup, input_buffer.Duplicate());
    decode_input_buffers[input_name] = std::move(input_buffer_dup);
  }
  for (const auto& [input_name, input_buffer] : *input_kv_cache_buffers_) {
    LITERT_ASSIGN_OR_RETURN(auto input_buffer_dup, input_buffer.Duplicate());
    decode_input_buffers[input_name] = std::move(input_buffer_dup);
  }
  RETURN_IF_ERROR(AppendActiveLoraInputBuffers(decode_input_buffers));
  absl::flat_hash_map<absl::string_view, TensorBuffer> decode_output_buffers;
""",
        compiled_cc_path,
    )
    text = _insert_before_once(
        text,
        "int LlmLiteRtCompiledModelExecutorBase::BindTensorsAndRunDecodeStatic(\n",
        """absl::Status LlmLiteRtCompiledModelExecutorBase::AppendActiveLoraInputBuffers(
    absl::flat_hash_map<absl::string_view, TensorBuffer>& input_buffers) {
  if (!active_lora_id_.has_value()) {
    return absl::OkStatus();
  }
  RET_CHECK_NE(lora_manager_, nullptr) << "LoRA manager is not initialized.";
  ASSIGN_OR_RETURN(auto lora_buffers, lora_manager_->GetLoRABuffers());
  for (auto& [input_name, input_buffer] : lora_buffers) {
    input_buffers[input_name] = std::move(input_buffer);
  }
  return absl::OkStatus();
}

""",
        compiled_cc_path,
    )
    text = _replace_once(
        text,
        """absl::StatusOr<std::unique_ptr<LlmContext>>
LlmLiteRtCompiledModelExecutorBase::CloneContext() const {
  std::optional<uint32_t> lora_id;
  ASSIGN_OR_RETURN(auto kv_cache_buffers, CloneKVCacheBuffers());
""",
        """absl::StatusOr<std::unique_ptr<LlmContext>>
LlmLiteRtCompiledModelExecutorBase::CloneContext() const {
  std::optional<uint32_t> lora_id =
      llm_context_->processed_context().lora_id();
  ASSIGN_OR_RETURN(auto kv_cache_buffers, CloneKVCacheBuffers());
""",
        compiled_cc_path,
    )
    text = _insert_before_once(
        text,
        """absl::Status LlmLiteRtCompiledModelExecutorBase::RestoreContext(
    std::unique_ptr<LlmContext> context_data) {
  llm_context_ = std::move(context_data);
""",
        """absl::Status LlmLiteRtCompiledModelExecutorBase::LoadLoRA(
    uint32_t lora_id, const ModelAssets& model_assets) {
  if (lora_manager_ == nullptr) {
    ASSIGN_OR_RETURN(lora_manager_,
                     LoraManager::Create(*compiled_model_,
                                         kDecodeSignatureRunner));
  }
  return lora_manager_->LoadLoRA(lora_id, model_assets);
}

absl::Status LlmLiteRtCompiledModelExecutorBase::UseLoRA(
    std::optional<uint32_t> lora_id) {
  if (!lora_id.has_value()) {
    active_lora_id_ = std::nullopt;
    return absl::OkStatus();
  }
  if (lora_manager_ == nullptr) {
    return absl::FailedPreconditionError("LoRA manager is not initialized.");
  }
  RETURN_IF_ERROR(lora_manager_->UseLoRA(*lora_id));
  active_lora_id_ = lora_id;
  return absl::OkStatus();
}

""",
        compiled_cc_path,
    )
    text = _replace_once(
        text,
        """absl::Status LlmLiteRtCompiledModelExecutorBase::RestoreContext(
    std::unique_ptr<LlmContext> context_data) {
  llm_context_ = std::move(context_data);

  // We can keep our kv cache buffers if this is the first step. This lets us
""",
        """absl::Status LlmLiteRtCompiledModelExecutorBase::RestoreContext(
    std::unique_ptr<LlmContext> context_data) {
  llm_context_ = std::move(context_data);
  RETURN_IF_ERROR(UseLoRA(llm_context_->processed_context().lora_id()));

  // We can keep our kv cache buffers if this is the first step. This lets us
""",
        compiled_cc_path,
    )
    compiled_cc_path.write_text(text, encoding="utf-8")

    resource_manager_h_path = (
        source_root
        / "runtime"
        / "framework"
        / "resource_management"
        / "resource_manager.h"
    )
    text = resource_manager_h_path.read_text(encoding="utf-8")
    text = _insert_after_once(
        text,
        '#include "absl/container/flat_hash_map.h"  // from @com_google_absl\n',
        '#include "absl/container/flat_hash_set.h"  // from @com_google_absl\n',
        resource_manager_h_path,
    )
    text = _insert_after_once(
        text,
        """  absl::flat_hash_map<std::string, uint32_t> lora_hash_to_id_;

""",
        """  absl::flat_hash_set<uint32_t> loaded_lora_ids_;

""",
        resource_manager_h_path,
    )
    resource_manager_h_path.write_text(text, encoding="utf-8")

    resource_manager_cc_path = (
        source_root
        / "runtime"
        / "framework"
        / "resource_management"
        / "resource_manager.cc"
    )
    text = resource_manager_cc_path.read_text(encoding="utf-8")
    text = _insert_after_once(
        text,
        """  absl::Status RestoreContext(
      std::unique_ptr<LlmContext> llm_context) override {
    return llm_executor_->RestoreContext(std::move(llm_context));
  }

""",
        """  absl::Status LoadLoRA(uint32_t lora_id,
                         const ModelAssets& model_assets) override {
    return llm_executor_->LoadLoRA(lora_id, model_assets);
  }

  absl::Status UseLoRA(std::optional<uint32_t> lora_id) override {
    return llm_executor_->UseLoRA(lora_id);
  }

""",
        resource_manager_cc_path,
    )
    text = _replace_once(
        text,
        """  // TODO: b/462499294 -
  //   1. Check if lora is loaded or not.
  //   2. Get the lora id.
  //   3. If lora is not loaded, load the lora.

  // Check if the lora is already loaded.
  // TODO: b/462499294 - Use the real lora path.
  bool lora_is_loaded =
      lora_hash_to_id_.find("fake_lora_path") != lora_hash_to_id_.end();

  // Find the lora id. If lora_id is not nullopt, it means the lora is used.
  std::optional<uint32_t> lora_id = AssignLoraId(
      /*lora_path=*/"",
      /*has_scoped_lora_file=*/session_config.GetScopedLoraFile() != nullptr);

  // If lora is used and not loaded, load the lora.
  if (lora_id.has_value() && !lora_is_loaded) {
    RET_CHECK(session_config.GetScopedLoraFile() != nullptr);
    ASSIGN_OR_RETURN(ModelAssets model_assets,
                     ModelAssets::Create(session_config.GetScopedLoraFile(),
                                         /*model_path=*/""));
    return absl::InvalidArgumentError("Lora is not supported.");
  }
""",
        """  // Find the lora id. If lora_id is not nullopt, it means the lora is used.
  std::optional<uint32_t> lora_id = AssignLoraId(
      /*lora_path=*/"",
      /*has_scoped_lora_file=*/session_config.GetScopedLoraFile() != nullptr);

  if (lora_id.has_value()) {
    RET_CHECK(session_config.GetScopedLoraFile() != nullptr);
    ASSIGN_OR_RETURN(ModelAssets model_assets,
                     ModelAssets::Create(session_config.GetScopedLoraFile(),
                                         /*model_path=*/""));
    MovableMutexLock lock(&executor_mutex_);
    if (!loaded_lora_ids_.contains(*lora_id)) {
      RETURN_IF_ERROR(llm_executor_->LoadLoRA(*lora_id, model_assets));
      loaded_lora_ids_.insert(*lora_id);
    }
  }
""",
        resource_manager_cc_path,
    )
    resource_manager_cc_path.write_text(text, encoding="utf-8")


def patch_upstream_build(source_root: Path) -> None:
    stream_proxy_target = source_root / "c" / "stream_proxy.c"
    shutil.copy2(STREAM_PROXY_SOURCE, stream_proxy_target)

    build_path = source_root / "c" / "BUILD"
    text = build_path.read_text(encoding="utf-8")
    insert_before = "\ncc_test(\n    name = \"engine_test\","
    packaging_marker = "# Added by litert-lm-native packaging."
    packaging_start = text.find(packaging_marker)
    if packaging_start != -1:
        packaging_end = text.find(insert_before, packaging_start)
        if packaging_end == -1:
            raise RuntimeError("Could not find packaging block end in upstream c/BUILD")
        text = text[:packaging_start].rstrip() + text[packaging_end:]
    if insert_before not in text:
        raise RuntimeError("Could not find insertion point in upstream c/BUILD")
    patched_build = text.replace(insert_before, SHARED_TARGETS + insert_before, 1)
    build_path.write_text(patched_build, encoding="utf-8")

    workspace_path = source_root / "WORKSPACE"
    workspace_text = workspace_path.read_text(encoding="utf-8")
    zlib_url = 'url = "https://zlib.net/fossils/zlib-1.3.1.tar.gz",'
    if zlib_url in workspace_text:
        workspace_path.write_text(
            workspace_text.replace(
                zlib_url,
                """urls = [
        "https://github.com/madler/zlib/releases/download/v1.3.1/zlib-1.3.1.tar.gz",
        "https://zlib.net/fossils/zlib-1.3.1.tar.gz",
    ],""",
            ),
            encoding="utf-8",
        )

    rules_rust_patch_path = source_root / "PATCH.rules_rust"
    rules_rust_patch_text = rules_rust_patch_path.read_text(encoding="utf-8")
    if '+    "x86_64-apple-darwin",' not in rules_rust_patch_text:
        hunk_header = "@@ -28,6 +28,9 @@\n"
        if hunk_header in rules_rust_patch_text:
            rules_rust_patch_text = rules_rust_patch_text.replace(
                hunk_header,
                "@@ -28,6 +28,10 @@\n",
                1,
            )
        marker = '     "aarch64-apple-darwin",\n'
        if marker not in rules_rust_patch_text:
            raise RuntimeError("Could not find rules_rust triple insertion point")
        rules_rust_patch_path.write_text(
            rules_rust_patch_text.replace(
                marker,
                marker + '+    "x86_64-apple-darwin",\n',
                1,
            ),
            encoding="utf-8",
        )

    patch_upstream_lora_support(source_root)


def bazel_command() -> list[str]:
    if shutil.which("bazelisk"):
        return ["bazelisk"]
    if shutil.which("npx"):
        return ["npx", "--yes", "@bazel/bazelisk@latest"]
    if shutil.which("bazel"):
        return ["bazel"]
    raise RuntimeError("Could not find bazelisk, bazel, or npx")


def build_runtime(source_root: Path, platform: str, arch: str, jobs: str | None) -> Path:
    target = RUNTIME_TARGETS[(platform, arch)]
    configs = [
        f"--config={config}"
        for config in target.get("bazel_configs", [target.get("bazel_config")])
        if config
    ]
    command = bazel_command()
    output_user_root = os.environ.get("BAZEL_OUTPUT_USER_ROOT")
    if output_user_root:
        if not os.path.isabs(output_user_root):
            output_user_root = str((REPO_ROOT / output_user_root).resolve())
        command.append(f"--output_user_root={output_user_root}")
    command += [
        "build",
        *configs,
        *target.get("bazel_options", []),
        target["bazel_target"],
        "--define=litert_link_capi_so=true",
        "--define=resolve_symbols_in_exec=false",
    ]
    if platform == "macos":
        command.append(f"--macos_minimum_os={MACOS_MINIMUM_OS}")
    if jobs:
        command.append(f"--jobs={jobs}")
    run(command, source_root)

    if "output" in target:
        output = source_root / target["output"]
        if not output.is_file():
            raise RuntimeError(f"Expected build output missing: {output}")
        return output

    matches = sorted(source_root.glob(target["output_glob"]))
    if not matches:
        raise RuntimeError(f"Expected build output missing: {target['output_glob']}")
    return matches[0]


def stage_runtime(output: Path, platform: str, arch: str) -> Path:
    target = RUNTIME_TARGETS[(platform, arch)]
    stage_dir = BIN_DIR / platform / arch
    stage_dir.mkdir(parents=True, exist_ok=True)
    staged = stage_dir / target["library"]
    shutil.copy2(output, staged)
    print(f"Staged {staged}", flush=True)
    return staged


def stage_runtime_dependencies(
    output: Path,
    source_root: Path,
    platform: str,
    arch: str,
) -> None:
    if platform == "macos":
        stage_macho_runtime_dependencies(output, source_root, platform, arch)
        return

    stage_dir = BIN_DIR / platform / arch
    staged = stage_dir / RUNTIME_TARGETS[(platform, arch)]["library"]
    queued = [staged]
    seen = set()
    dependency_cache: dict[str, Path | None] = {}

    while queued:
        current = queued.pop()
        if current in seen:
            continue
        seen.add(current)
        if not is_elf(current):
            continue
        for library_name in elf_needed_libraries(current):
            if is_system_needed(platform, library_name):
                continue
            destination = stage_dir / library_name
            if not destination.exists():
                dependency = find_runtime_dependency(
                    source_root,
                    output,
                    library_name,
                    dependency_cache,
                )
                if dependency is None:
                    raise RuntimeError(
                        f"{current} depends on {library_name}, but that library "
                        "was not found in the Bazel output tree."
                    )
                shutil.copy2(dependency, destination)
                print(f"Staged runtime dependency {destination}", flush=True)
            queued.append(destination)


def stage_macho_runtime_dependencies(
    output: Path,
    source_root: Path,
    platform: str,
    arch: str,
) -> None:
    stage_dir = BIN_DIR / platform / arch
    staged = stage_dir / RUNTIME_TARGETS[(platform, arch)]["library"]
    queued = [staged]
    seen = set()
    dependency_cache: dict[str, Path | None] = {}

    while queued:
        current = queued.pop()
        if current in seen:
            continue
        seen.add(current)
        for install_name in macho_needed_libraries(current):
            if is_system_macho_needed(install_name):
                continue
            library_name = Path(install_name).name
            if library_name == current.name:
                continue
            destination = stage_dir / library_name
            if not destination.exists():
                dependency = find_runtime_dependency(
                    source_root,
                    output,
                    library_name,
                    dependency_cache,
                )
                if dependency is None:
                    raise RuntimeError(
                        f"{current} depends on {install_name}, but {library_name} "
                        "was not found in the Bazel output tree."
                    )
                shutil.copy2(dependency, destination)
                print(f"Staged runtime dependency {destination}", flush=True)
            queued.append(destination)


def macho_needed_libraries(path: Path) -> list[str]:
    result = subprocess.run(
        ["otool", "-L", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    libraries: list[str] = []
    for line in result.stdout.splitlines()[1:]:
        stripped = line.strip()
        if not stripped:
            continue
        libraries.append(stripped.split(" ", 1)[0])
    return libraries


def is_system_macho_needed(install_name: str) -> bool:
    return (
        install_name.startswith("/System/Library/")
        or install_name.startswith("/usr/lib/")
        or install_name == Path(install_name).name
    )


def find_runtime_dependency(
    source_root: Path,
    output: Path,
    library_name: str,
    cache: dict[str, Path | None],
) -> Path | None:
    if library_name in cache:
        return cache[library_name]

    roots = [
        output.parent,
        output.parent / f"{output.name}.runfiles",
        source_root / "bazel-bin",
        source_root / "bazel-out",
    ]
    for root in roots:
        if not root.exists():
            continue
        for candidate in root.rglob(library_name):
            if candidate.is_file():
                cache[library_name] = candidate
                return candidate
    cache[library_name] = None
    return None


def validate_exported_symbols(output: Path) -> None:
    data = output.read_bytes()
    required_symbols = REQUIRED_C_API_SYMBOLS + REQUIRED_STREAM_PROXY_SYMBOLS
    missing = [
        symbol.decode("ascii")
        for symbol in required_symbols
        if symbol not in data
    ]
    if missing:
        raise RuntimeError(
            f"{output} does not contain required LiteRT-LM/StreamProxy symbols: "
            + ", ".join(missing)
        )
    print(f"Validated LiteRT-LM and StreamProxy symbols in {output}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=f"Build the upstream {UPSTREAM_REPO} C runtime library."
    )
    parser.add_argument("--upstream-tag", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--arch", required=True)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--jobs")
    args = parser.parse_args()

    key = (args.platform, args.arch)
    if key not in RUNTIME_TARGETS:
        supported = ", ".join(f"{p}/{a}" for p, a in sorted(RUNTIME_TARGETS))
        raise SystemExit(f"Unsupported target {args.platform}/{args.arch}; supported: {supported}")

    if args.source_root:
        source_root = args.source_root.resolve()
        patch_upstream_build(source_root)
        output = build_runtime(source_root, args.platform, args.arch, args.jobs)
        validate_exported_symbols(output)
        stage_runtime(output, args.platform, args.arch)
        stage_runtime_dependencies(output, source_root, args.platform, args.arch)
        return 0

    with tempfile.TemporaryDirectory(
        prefix="litert-lm-native-build-",
        ignore_cleanup_errors=os.name == "nt",
    ) as tmp:
        source_root = download_upstream(args.upstream_tag, Path(tmp))
        patch_upstream_build(source_root)
        output = build_runtime(source_root, args.platform, args.arch, args.jobs)
        validate_exported_symbols(output)
        stage_runtime(output, args.platform, args.arch)
        stage_runtime_dependencies(output, source_root, args.platform, args.arch)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
