import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

from android_gpu_safety_patch import SOURCES, apply, applies, digest, manifest

ROOT = Path(__file__).resolve().parents[1]


class AndroidGpuSafetyTest(unittest.TestCase):
    def test_version_decision_and_manifest(self):
        self.assertFalse(applies("v0.18.1"))
        self.assertTrue(applies("v0.19.0"))
        with self.assertRaises(RuntimeError):
            applies("v0.20.0")
        records = manifest("v0.19.0")
        self.assertEqual({r["source"] for r in records}, set(SOURCES))
        self.assertEqual(manifest("v0.18.1"), [])

    def test_changed_source_refuses_before_patch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in SOURCES:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("changed upstream\n")
            with self.assertRaisesRegex(RuntimeError, "requalify"):
                apply(root, "v0.19.0")

    def test_policy_and_identity_compile_against_crypto(self):
        compiler = shutil.which("clang++") or shutil.which("c++")
        if not compiler or not shutil.which("pkg-config"):
            self.skipTest("C++ compiler and pkg-config OpenSSL required")
        if subprocess.run(["pkg-config", "--exists", "openssl"]).returncode:
            self.skipTest("OpenSSL headers required for host hash tests")
        flags = shlex.split(subprocess.check_output(
            ["pkg-config", "--cflags", "--libs", "openssl"], text=True))
        with tempfile.TemporaryDirectory() as temp:
            binary = Path(temp) / "policy"
            subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                            "-Wno-deprecated-declarations", "-DLITERT_LM_GPU_SAFETY_TEST",
                            "-I", str(ROOT / "native"),
                            str(ROOT / "native/bridge/android_gpu_safety.cc"),
                            str(ROOT / "native/bridge/android_gpu_safety_test.cc"),
                            *flags, "-o", str(binary)], check=True, timeout=60)
            subprocess.run([str(binary)], check=True, timeout=30)
            model = os.environ.get("LITERT_GPU_SAFETY_MODEL")
            if model:
                subprocess.run([str(binary), model], check=True, timeout=60)

    @unittest.skipUnless(os.environ.get("LITERT_GPU_SAFETY_SOURCE"),
                         "set exact upstream source root to audit patch application")
    def test_exact_source_patch_and_idempotence(self):
        source = Path(os.environ["LITERT_GPU_SAFETY_SOURCE"])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in SOURCES:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source / name, target)
            apply(root, "v0.19.0")
            apply(root, "v0.19.0")
            for name, (_, post) in SOURCES.items():
                self.assertEqual(digest(root / name), post)
            text = (root / "c/engine.cc").read_text()
            start = text.index("LiteRtLmStatusCode litert_lm_engine_create(\n")
            end = text.index("\nvoid litert_lm_engine_delete(", start)
            body = text[start:end]
            harness = (ROOT / "native/bridge/android_gpu_c_api_test.cc").read_text()
            compiler = shutil.which("clang++") or shutil.which("c++")
            for mutation in (False, True):
                unit = root / "engine_test.cc"
                selected = body
                if mutation:
                    selected = selected.replace(
                        "if (!safety.ok()) return litert::lm::c::ToCStatus(safety);",
                        "// Evidence control: ignore preflight refusal.")
                unit.write_text(harness.replace("// PRODUCTION_ENGINE_CREATE", selected))
                binary = root / ("mutant" if mutation else "guard")
                subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra",
                                "-Werror", "-Wno-unused-variable", "-pthread",
                                "-I", str(ROOT / "native"), str(unit),
                                str(ROOT / "native/bridge/android_gpu_safety.cc"),
                                "-o", str(binary)], check=True, timeout=60)
                result = subprocess.run([str(binary)], capture_output=True, timeout=30)
                self.assertEqual(result.returncode == 0, not mutation,
                                 result.stderr.decode(errors="replace"))


if __name__ == "__main__":
    unittest.main()
