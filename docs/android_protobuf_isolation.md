# Android bundled protobuf isolation

Owner [#105](https://github.com/leehack/litert-lm-native/issues/105) tracks a
loader-time protobuf ABI collision in the v0.19 Android candidate. Android's
system `libprotobuf-cpp-lite.so` constructor resolved
`google::protobuf::internal::fixed_address_empty_string` to the bundled runtime's
24-byte, read-only definition. Its initializing store faulted in that runtime
mapping. Matched model-free controls still crashed after clearing `DF_1_GLOBAL`;
a diagnostic name-only control for that object loaded. The system constructor's
GOT relocation, faulting instruction and captured register/mapping identify the
cross-library binding. These controls establish the collision, not engine or
GPU qualification; their edited binaries must never ship.

The owner `libLiteRtLm.so` link now uses
`native/bridge/android_private_protobuf.lds` only when both Android and the
existing `litert_lm_c_api_v1=true` define are selected. Its anonymous version
script localizes `*protobuf*` definitions. Other exports keep their original
link policy, including the C runtime, ASR ABI v1, stream bridge and GPU plugin
interfaces. The audited v0.19 public C headers and bridge headers expose no
protobuf API. This changes the wrapper link, not upstream sources, public
signatures or symbol names. Older compatibility baselines and other platforms
keep their existing link policy.

`DF_1_GLOBAL` and `stream_proxy_load_global` remain intact. They are public
loader/plugin contracts; removing the flag alone does not isolate symbols in a
shared dependency lookup group. `-Bsymbolic` alone also leaves definitions
available to system-library lookups. Protobuf definitions must leave the
external dynamic-symbol surface and bind internally during the actual link.
C++ symbols without `protobuf` in their names retain their existing visibility.

The build and packaged dependency validators require an explicit upstream
compatibility tag. Android C API 1.0 runtimes fail if any defined global, weak or
GNU-unique dynamic symbol contains `protobuf`, or if any required C/ASR/stream
export is missing. A remaining hidden nonlocal dynamic symbol is also rejected:
a post-link visibility-byte edit is not equivalent to linker localization on
Android. Undefined imports and local static-table entries are not exports.
Existing GLOBAL, dependency-closure, plugin-export, ABI and 16 KB LOAD-alignment
checks remain in force.

Run model-free compiler/linker controls with a configured NDK:

```bash
ANDROID_NDK_HOME=/path/to/android-ndk \
ANDROID_PROTOBUF_REQUIRE_NDK=1 \
  python3 -m unittest discover -s tools -p test_android_protobuf_policy.py -v
```

These compile arm64 and x86_64 ELF fixtures without executing them. They use the
wrapper's selected linker options, compare the complete before/after dynamic
export sets, verify protobuf localization and internal relocations, and preserve
an unrelated C++ helper plus public/plugin symbols. Negative controls exercise
leaked symbols, required export loss, GLOBAL, alignment and dependency closure.
Both Android CI build lanes require these controls; ordinary tooling runs skip
only the compiler fixtures when no NDK is available.

Before publication or downstream adoption, rebuild both Android architectures
at the new exact native head and inspect the real export/relocation sets: only
protobuf-named exports may disappear, all public and real plugin imports must
remain satisfied, and bundled/system protobuf objects must stay separate in the
matched original and public-loader order/namespace controls. Repeat affected
Android GPU delegate and sampler execution, output-oracle comparisons and
lifecycle/cancel/reload qualification. Loader/version success and these static
fixtures do not satisfy those gates or close the separate GPU-output issue #51.
The shared owner change also retains all eight platform builds and the existing
three desktop real-model qualification jobs. The exact native commit identifies
this wrapper policy; `upstream.sourcePatches` continues to describe upstream
source edits only.
