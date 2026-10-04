# Bounded v0.17.0 upstream BUILD gate, e9fd8c53ff968071774206163027dd84bedfe925.

# Pass --define=LITERT_LM_FST_CONSTRAINTS_DISABLED=1 to disable FST constraints.
config_setting(
    name = "litert_lm_fst_constraints_disabled",
    define_values = {
        "LITERT_LM_FST_CONSTRAINTS_DISABLED": "1",
    },
)


cc_library(
    name = "gemma3_data_processor",
    srcs = ["gemma3_data_processor.cc"],
    hdrs = ["gemma3_data_processor.h"],
    defines = select({
        ":litert_lm_fst_constraints_disabled": ["LITERT_LM_FST_CONSTRAINTS_DISABLED"],
        "//conditions:default": [],
    }),
    deps = [
        ":data_utils",
        ":gemma3_data_processor_config",
        ":model_data_processor",
        ":multimodal_processor_helper",
        "@com_google_absl//absl/log:absl_log",
        "@com_google_absl//absl/memory",
        "@com_google_absl//absl/status",
        "@com_google_absl//absl/status:status_macros",
        "@com_google_absl//absl/status:statusor",
        "@com_google_absl//absl/strings",
        "@com_google_absl//absl/strings:string_view",
        "@nlohmann_json//:json",
        "@litert//litert/cc:litert_layout",
        "//runtime/components:prompt_template",
        "//runtime/components/constrained_decoding:constraint",
        "//runtime/components/tool_use:parser_utils",
        "//runtime/components/tool_use:python_tool_format_utils",
        "//runtime/conversation:io_types",
        "//runtime/conversation:prompt_utils",
        "//runtime/engine:io_types",
        "//runtime/util:litert_status_util",
        "//runtime/util:memory_mapped_file",
        "//support/preprocessor:audio_preprocessor",
        "//support/preprocessor:audio_preprocessor_miniaudio",
        "//support/preprocessor:image_preprocessor",
        "//support/preprocessor:image_preprocessor_impl",
        "//support/tokenizer",
        "//support/tokenizer:sentencepiece_tokenizer",
        "@com_googlesource_code_re2//:re2",
        "@sentencepiece//:sentencepiece_model_cc_proto",
    ] + select({
        ":litert_lm_fst_constraints_disabled": [],
        "//conditions:default": [
            "//runtime/components/constrained_decoding:gemma_model_constraint_provider_lib",
        ],
    }),
)

cc_library(
    name = "function_gemma_data_processor",
    srcs = ["function_gemma_data_processor.cc"],
    hdrs = ["function_gemma_data_processor.h"],
    defines = select({
        ":litert_lm_fst_constraints_disabled": ["LITERT_LM_FST_CONSTRAINTS_DISABLED"],
        "//conditions:default": [],
    }),
    deps = [
        ":function_gemma_data_processor_config",
        ":model_data_processor",
        "@com_google_absl//absl/log:absl_log",
        "@com_google_absl//absl/memory",
        "@com_google_absl//absl/status",
        "@com_google_absl//absl/status:status_macros",
        "@com_google_absl//absl/status:statusor",
        "@com_google_absl//absl/strings",
        "@com_google_absl//absl/strings:string_view",
        "@nlohmann_json//:json",
        "//runtime/components/constrained_decoding:constraint",
        "//runtime/components/tool_use:fc_tool_format_utils",
        "//runtime/components/tool_use:parser_utils",
        "//runtime/conversation:io_types",
        "//runtime/engine:io_types",
        "//runtime/util:litert_status_util",
        "//support/tokenizer",
        "//support/tokenizer:sentencepiece_tokenizer",
        "@sentencepiece//:sentencepiece_model_cc_proto",
    ] + select({
        ":litert_lm_fst_constraints_disabled": [],
        "//conditions:default": [
            "//runtime/components/constrained_decoding:gemma_model_constraint_provider_lib",
        ],
    }),
)

cc_library(
    name = "gemma4_data_processor",
    srcs = ["gemma4_data_processor.cc"],
    hdrs = ["gemma4_data_processor.h"],
    defines = select({
        ":litert_lm_fst_constraints_disabled": ["LITERT_LM_FST_CONSTRAINTS_DISABLED"],
        "//conditions:default": [],
    }),
    deps = [
        ":data_utils",
        ":gemma4_data_processor_config",
        ":model_data_processor",
        ":multimodal_processor_helper",
        "@com_google_absl//absl/log:absl_log",
        "@com_google_absl//absl/memory",
        "@com_google_absl//absl/status",
        "@com_google_absl//absl/status:status_macros",
        "@com_google_absl//absl/status:statusor",
        "@com_google_absl//absl/strings",
        "@com_google_absl//absl/strings:string_view",
        "@nlohmann_json//:json",
        "//runtime/components:prompt_template",
        "//runtime/components/constrained_decoding:constraint",
        "//runtime/components/tool_use:parser_utils",
        "//runtime/conversation:io_types",
        "//runtime/conversation:prompt_utils",
        "//runtime/engine:io_types",
        "//runtime/util:litert_status_util",
        "//runtime/util:memory_mapped_file",
        "//support/preprocessor:audio_preprocessor",
        "//support/preprocessor:audio_preprocessor_miniaudio",
        "//support/preprocessor:image_preprocessor",
        "//support/preprocessor:stb_image_preprocessor",
        "//support/tokenizer",
        "//support/tokenizer:sentencepiece_tokenizer",
        "@com_googlesource_code_re2//:re2",
        "@sentencepiece//:sentencepiece_model_cc_proto",
    ] + select({
        ":litert_lm_fst_constraints_disabled": [],
        "//conditions:default": [
            "//runtime/components/constrained_decoding:gemma_model_constraint_provider_lib",
        ],
    }),
)
