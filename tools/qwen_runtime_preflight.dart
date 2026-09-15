import 'dart:ffi';
import 'dart:io';

import 'package:llamadart/src/backends/litert_lm/litert_lm_runtime.dart'
    as runtime;

// Run in the workflow's exact pinned consumer checkout. Check its own inventory
// so an incomplete candidate cannot fall back to a downloaded default runtime.
void main() {
  final directory = Platform.environment['LLAMADART_LITERT_LM_LIB_DIR'];
  if (directory == null || directory.isEmpty) {
    throw StateError('An explicit candidate runtime directory is required.');
  }
  final abi = Abi.current();
  final primary = switch (abi) {
    Abi.macosArm64 => 'libLiteRtLm.dylib',
    Abi.linuxX64 => 'libLiteRtLm.so',
    Abi.windowsX64 => 'LiteRtLm.dll',
    _ => throw UnsupportedError('Unsupported Qwen qualification host: $abi'),
  };
  final required = runtime.liteRtLmRequiredLibrariesForAbi(abi);
  if (!required.contains(primary)) {
    throw StateError(
      'Consumer inventory does not contain the primary library.',
    );
  }
  for (final name in required) {
    if (!File('$directory/$name').existsSync()) {
      throw StateError('Candidate runtime is incomplete: $name');
    }
  }
  final companions = runtime.liteRtLmOpenCompanionLibraries([
    for (final name in required)
      if (name != primary) '$directory/$name',
  ]);
  final library = DynamicLibrary.open('$directory/$primary');
  for (final symbol in [
    'litert_lm_engine_settings_create',
    'litert_lm_engine_create',
    'litert_lm_engine_delete',
    'stream_proxy_create',
  ]) {
    library.lookup<NativeFunction<Void Function()>>(symbol);
  }
  print(
    'Verified candidate $directory/$primary; ${companions.length} companions',
  );
}
