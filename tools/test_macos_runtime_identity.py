from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import build_upstream_runtime
import macos_runtime_identity
import package_macos_runtime
from generate_schema2_contract_fixture import (
    NATIVE_COMMIT, RELEASE_TAG, UPSTREAM_COMMIT, UPSTREAM_TAG, generate_manifest,
)
from litert_lm_symbols import required_bridge_symbols, required_c_api_symbols
from validate_release_manifest import validate_schema_2_payload


class MacosRuntimeIdentityTest(unittest.TestCase):
    def test_normalized_identity_never_invokes_a_writer(self) -> None:
        result = subprocess.CompletedProcess([], 0, "runtime:\n@rpath/libLiteRtLm.dylib\n")
        with patch.object(macos_runtime_identity.subprocess, "run", return_value=result) as run:
            macos_runtime_identity.normalize_macos_runtime_identity(Path("runtime"))
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0], ["otool", "-D", "runtime"])

    def test_ambiguous_identity_fails_closed(self) -> None:
        result = subprocess.CompletedProcess([], 0, "runtime:\none\ntwo\n")
        with patch.object(macos_runtime_identity.subprocess, "run", return_value=result) as run:
            with self.assertRaisesRegex(RuntimeError, "one thin macOS dylib"):
                macos_runtime_identity.normalize_macos_runtime_identity(Path("runtime"))
        self.assertEqual(run.call_count, 1)

    @unittest.skipUnless(sys.platform == "darwin", "requires the macOS production packaging tools")
    def test_staged_model_identity_survives_real_packaging_and_rejects_skew(self) -> None:
        # This compiled test fixture checks packaging identity, not model quality.
        # Runtime/model qualification uses the separate real-model smoke workflow.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "runtime.c"
            symbols = set(required_c_api_symbols(UPSTREAM_TAG) + required_bridge_symbols(UPSTREAM_TAG))
            source.write_text("\n".join(f"void {name.decode()}(void) {{}}" for name in sorted(symbols)))
            output = root / "libLiteRtLm.dylib"
            subprocess.run([
                "xcrun", "clang", "-dynamiclib", "-arch", "arm64",
                "-mmacosx-version-min=14.0",
                "-install_name", "bazel-out/darwin_arm64-opt/bin/bridge/libLiteRtLm.dylib",
                str(source), "-o", str(output),
            ], check=True)
            original_digest = hashlib.sha256(output.read_bytes()).hexdigest()
            with patch.object(build_upstream_runtime, "BIN_DIR", root / "bin"), \
                 patch.object(package_macos_runtime, "BIN_DIR", root / "bin"):
                staged = build_upstream_runtime.stage_runtime(output, "macos", "arm64")
                qualified_digest = hashlib.sha256(staged.read_bytes()).hexdigest()
                self.assertNotEqual(original_digest, qualified_digest)
                self.assertEqual(hashlib.sha256(output.read_bytes()).hexdigest(), original_digest)
                # Loading and smoke evidence happen after stage_runtime in production.
                # Spy on the real subprocess boundary: an unconditional rewrite can
                # preserve today's bytes but still violate the no-writer contract.
                with patch.object(subprocess, "run", wraps=subprocess.run) as packaging_run:
                    package_macos_runtime.stage_source_built_runtime(
                        [{"arch": "arm64", "source_arch": "arm64", "source": staged}],
                        clean=True, upstream_tag=UPSTREAM_TAG,
                    )
                runtime_writes = [
                    call.args[0]
                    for call in packaging_run.call_args_list
                    if Path(call.args[0][0]).name == "install_name_tool"
                    and str(staged) in [str(argument) for argument in call.args[0][1:]]
                ]
                self.assertEqual(runtime_writes, [], "Packaging must not rewrite a qualified runtime")
                packaged_digest = hashlib.sha256(staged.read_bytes()).hexdigest()
                self.assertEqual(qualified_digest, packaged_digest)
                subprocess.run(["codesign", "--verify", str(staged)], check=True)

                manifest = generate_manifest()
                runtime = next(item for item in manifest["artifacts"] if item["path"] == "bin/macos/arm64/libLiteRtLm.dylib")
                runtime["sha256"] = packaged_digest
                smoke = deepcopy(manifest["realModelSmokes"][0])
                smoke.update(platform="macos", arch="arm64")
                smoke["library"] = {"fileName": staged.name, "sha256": qualified_digest}
                smoke["source"]["runtimeReleaseAsset"] = f"litert-lm-native-runtime-macos-arm64-{RELEASE_TAG}.tar.gz"
                manifest["realModelSmokes"].append(smoke)

                def validate() -> None:
                    validate_schema_2_payload(
                        manifest, upstream_tag=UPSTREAM_TAG, upstream_commit=UPSTREAM_COMMIT,
                        compatibility_tag=UPSTREAM_TAG, native_commit=NATIVE_COMMIT,
                        release_tag=RELEASE_TAG,
                    )

                validate()
                # Reproduce a post-smoke Mach-O byte mutation. The evidence must fail.
                subprocess.run(["install_name_tool", "-id", "@rpath/wrong-runtime.dylib", str(staged)], check=True)
                runtime["sha256"] = hashlib.sha256(staged.read_bytes()).hexdigest()
                with self.assertRaisesRegex(SystemExit, "packaged runtime artifact"):
                    validate()


if __name__ == "__main__":
    unittest.main()
