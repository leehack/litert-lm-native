cmake_minimum_required(VERSION 3.22)
project(litert_lm_native LANGUAGES C CXX)

option(LITERT_LM_NATIVE_BUILD_SHIM "Build the scaffold C ABI shim" ON)

if(LITERT_LM_NATIVE_BUILD_SHIM)
  add_library(litert_lm_native SHARED src/litert_lm_c_api.cc)
  target_include_directories(litert_lm_native PUBLIC include)
  target_compile_features(litert_lm_native PUBLIC cxx_std_17)
  target_compile_definitions(litert_lm_native
    PRIVATE LITERT_LM_NATIVE_BUILDING_LIBRARY)
  set_target_properties(litert_lm_native PROPERTIES
    CXX_VISIBILITY_PRESET hidden
    VISIBILITY_INLINES_HIDDEN YES
    OUTPUT_NAME litert_lm_native)
endif()
