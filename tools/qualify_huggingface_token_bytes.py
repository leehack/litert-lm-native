#!/usr/bin/env python3
"""Compile the production ByteLevel adapter and optionally verify every HF ID."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
import shlex
import shutil
import subprocess

from huggingface_token_bytes_patch import SOURCES, apply as apply_token_bytes_patch

REPO = Path(__file__).resolve().parents[1]


def vocabulary_fixture(config: dict) -> dict:
    # Independent reference: construct GPT-2's bytes_to_unicode alphabet in its
    # specified order, then invert it without decoding incomplete UTF-8 bytes.
    direct = list(range(33, 127)) + list(range(161, 173)) + list(range(174, 256))
    missing = [byte for byte in range(256) if byte not in direct]
    inverse = {chr(byte): byte for byte in direct}
    inverse.update({chr(256 + index): byte for index, byte in enumerate(missing)})
    vocab = {int(id): token for token, id in config["model"]["vocab"].items()}
    special = set()
    for token in config.get("added_tokens", []):
        id = int(token["id"])
        if id in vocab and vocab[id] != token["content"]:
            raise ValueError("Conflicting added-token vocabulary ID")
        vocab[id] = token["content"]
        if token["special"]:
            special.add(id)
    if set(vocab) != set(range(len(vocab))):
        raise ValueError("Qualification requires a contiguous vocabulary")
    entries = []
    for id, token in sorted(vocab.items()):
        raw = token.encode("utf-8")
        if id not in special:
            try:
                raw = bytes(inverse[character] for character in token)
            except KeyError:
                pass  # ByteLevel's whole-token fallback.
        entries.append({"id": id, "raw": token, "hex": raw.hex(), "special": id in special})
    return {"config": {"decoder": config.get("decoder"),
                       "added_tokens": config.get("added_tokens", [])},
            "tokens": entries}


def mutation_controls(compiler: str, cflags: list[str], work_dir: Path) -> list[str]:
    header = (REPO / "native/bridge/huggingface_token_bytes.h").read_text()
    variants = {
        "raw-vocabulary": re.sub(r"if \(IsSpecialToken\(id\)\)\s*return token;", "return token;", header),
        "special-spelling-lost": re.sub(r"if \(IsSpecialToken\(id\)\)\s*return token;", "", header),
        "partial-utf8-lossy": header.replace(
            "bytes.push_back(static_cast<char>(inverse[codepoint]));",
            'if (inverse[codepoint] >= 128) bytes.append("\\xef\\xbf\\xbd"); '
            'else bytes.push_back(static_cast<char>(inverse[codepoint]));'),
    }
    killed = []
    for name, mutant in variants.items():
        if mutant == header:
            raise RuntimeError(f"Mutation {name} did not change production adapter")
        root = work_dir / name
        root.mkdir(parents=True, exist_ok=True)
        (root / "huggingface_token_bytes.h").write_text(mutant)
        source = root / "test.cc"
        shutil.copyfile(REPO / "native/bridge/huggingface_token_bytes_test.cc", source)
        binary = root / "test"
        subprocess.run([compiler, "-std=c++17", "-O2", *cflags, str(source),
                        "-o", str(binary)], check=True, timeout=120)
        failure = subprocess.run([str(binary.resolve())], capture_output=True, text=True,
                                 timeout=30)
        if failure.returncode == 0:
            raise RuntimeError(f"Regression mutation survived: {name}")
        killed.append(name)
    return killed


def qualify(work_dir: Path, tokenizer_json: Path | None = None,
            source_root: Path | None = None, mutations: bool = False, *,
            runtime_library: Path | None = None,
            llguidance_include: Path | None = None,
            schema_json: Path | None = None,
            observed_output: Path | None = None) -> dict:
    runtime_inputs = (runtime_library, llguidance_include, schema_json, observed_output)
    if any(runtime_inputs) and (not all(runtime_inputs) or not source_root or not tokenizer_json):
        raise ValueError("Packaged grammar controls require source, tokenizer, runtime library, "
                         "llguidance include directory, schema JSON and retained output")
    work_dir.mkdir(parents=True, exist_ok=True)
    compiler = shutil.which("clang++") or shutil.which("c++")
    if not compiler:
        raise RuntimeError("C++17 compiler required for token-byte qualification")
    cflags = shlex.split(subprocess.check_output(
        ["pkg-config", "--cflags", "nlohmann_json"], text=True))
    binary = work_dir / "huggingface_token_bytes_test"
    subprocess.run([compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", *cflags,
                    "-I", str(REPO / "native/bridge"),
                    str(REPO / "native/bridge/huggingface_token_bytes_test.cc"),
                    "-o", str(binary)], check=True, timeout=120)
    command = [str(binary.resolve())]
    result = {"adapterControls": "passed"}
    if tokenizer_json:
        data = tokenizer_json.read_bytes()
        config = json.loads(data)
        result.update(tokenizerSha256=hashlib.sha256(data).hexdigest(),
                      baseVocabulary=len(config["model"]["vocab"]),
                      addedTokens=len(config.get("added_tokens", [])),
                      specialTokens=sum(token["special"] for token in config.get("added_tokens", [])))
    else:
        direct = set(range(33, 127)) | set(range(161, 173)) | set(range(174, 256))
        extra = iter(range(256, 324))
        config = {"decoder": {"type": "ByteLevel"},
                  "model": {"vocab": {chr(byte if byte in direct else next(extra)): byte
                                      for byte in range(256)}},
                  "added_tokens": [{"id": 256, "content": "Ġ", "special": True},
                                   {"id": 257, "content": "Ã日本", "special": False}]}
        result["fixture"] = "all-256-bytes-and-added-token-controls"
    fixture = vocabulary_fixture(config)
    path = work_dir / "vocabulary.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")
    command.append(str(path.resolve()))
    result["vocabularyIds"] = len(fixture["tokens"])
    subprocess.run(command, check=True, timeout=30)
    if mutations:
        result["mutationsKilled"] = mutation_controls(compiler, cflags, work_dir)
    if source_root:
        patched = work_dir / "patched"
        headers = ["runtime/components/constrained_decoding/" + name for name in
                   ("llg_constraint_provider.h", "llg_constraint_config.h", "constraint_provider.h")]
        for name in [*SOURCES, *headers]:
            target = patched / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_root / name, target)
        apply_token_bytes_patch(patched, "v0.19.0")
        source_binary = work_dir / "huggingface_tokenizer_source_test"
        packages = ["absl_statusor", "absl_leak_check", "absl_status_macros", "absl_flat_hash_set"]
        flags = shlex.split(subprocess.check_output(
            ["pkg-config", "--cflags", "--libs", *packages], text=True))
        source_command = [compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", *cflags,
                        "-I", str(REPO / "tests/huggingface_token_bytes/shim"),
                        "-I", str(patched), "-I", str(REPO / "native"),
                        str(patched / "support/tokenizer/huggingface_tokenizer.cc"),
                        str(patched / "runtime/components/constrained_decoding/llg_constraint_provider.cc"),
                        str(REPO / "tests/huggingface_token_bytes/tokenizer_source_test.cc"),
                        *flags, "-o", str(source_binary)]
        subprocess.run(source_command, check=True, timeout=120)
        subprocess.run([str(source_binary.resolve()), *command[1:]],
                       check=True, timeout=30)
        result["patchedHuggingFaceSourceControls"] = "passed"
        result["jsonWhitespaceSourceControls"] = "passed"
        baseline_binary = work_dir / "raw_provider_cause_control"
        baseline_command = [str(source_root / "runtime/components/constrained_decoding/llg_constraint_provider.cc")
                            if arg == str(patched / "runtime/components/constrained_decoding/llg_constraint_provider.cc")
                            else str(baseline_binary) if arg == str(source_binary) else arg
                            for arg in source_command]
        subprocess.run(baseline_command, check=True, timeout=120)
        baseline = subprocess.run([str(baseline_binary.resolve()), *command[1:]],
                                  capture_output=True, text=True, timeout=30)
        if baseline.returncode == 0:
            raise RuntimeError("Original raw-vocabulary provider unexpectedly passed byte oracle")
        result["originalProviderCauseControl"] = "failed-as-expected"
        if mutations:
            provider = patched / "runtime/components/constrained_decoding/llg_constraint_provider.cc"
            original = provider.read_text()
            provider_mutations = {
                "text-callback-advertises-arbitrary-bytes": (
                    original.replace(".tokenize_assumes_string = true,",
                                     ".tokenize_assumes_string = false,"),
                    "text-only callback requires"),
                "unbounded-default-json-whitespace": (
                    original.replace(r"[\x20\x0A\x0D\x09]{1,8}",
                                     r"[\x20\x0A\x0D\x09]+"),
                    "default JSON whitespace must be bounded"),
                "caller-whitespace-options-overwritten": (
                    original.replace('!options.is_object() || options.contains("whitespace_pattern") ||\n'
                                     '      options.contains("whitespace_flexible")',
                                     '!options.is_object()'),
                    "explicit caller whitespace option retained"),
                "schema-property-order-sorted": (
                    original.replace("nlohmann::ordered_json", "nlohmann::json"),
                    "JSON property order retained"),
                "literal-string-whitespace-stripped": (
                    original.replace("return schema.dump();",
                                     "auto result = schema.dump(); "
                                     "result.erase(std::remove(result.begin(), result.end(), ' '), "
                                     "result.end()); return result;"),
                    "schema semantics and literal string whitespace retained"),
            }
            for name, (mutant, expected_error) in provider_mutations.items():
                if mutant == original:
                    raise RuntimeError(f"Provider mutation did not change source: {name}")
                mutant_source = work_dir / f"{name}.cc"
                mutant_source.write_text(mutant)
                mutant_binary = work_dir / name
                mutant_command = [str(mutant_source) if arg == str(provider)
                                  else str(mutant_binary) if arg == str(source_binary)
                                  else arg for arg in source_command]
                subprocess.run(mutant_command, check=True, timeout=120)
                failure = subprocess.run([str(mutant_binary.resolve()), *command[1:]],
                                         capture_output=True, text=True, timeout=30)
                if failure.returncode == 0 or expected_error not in failure.stderr:
                    raise RuntimeError(f"Provider mutation survived or failed unexpectedly: {name}: "
                                       f"{failure.stderr}")
                result["mutationsKilled"].append(name)
    if runtime_library:
        runtime_binary = work_dir / "grammar_runtime_test"
        runtime_command = [str(REPO / "tests/huggingface_token_bytes/grammar_runtime_test.cc")
                           if arg == str(REPO / "tests/huggingface_token_bytes/tokenizer_source_test.cc")
                           else str(runtime_binary) if arg == str(source_binary) else arg
                           for arg in source_command]
        runtime_command[1:1] = ["-I", str(llguidance_include)]
        runtime_command += [str(runtime_library.resolve()),
                            f"-Wl,-rpath,{runtime_library.resolve().parent}"]
        subprocess.run(runtime_command, check=True, timeout=120)
        runtime_result = subprocess.run(
            [str(runtime_binary.resolve()), str(tokenizer_json.resolve()),
             str(schema_json.resolve()), str(observed_output.resolve())],
            check=True, capture_output=True, text=True, timeout=30)
        result["packagedGrammarRuntimeControls"] = {
            "status": "passed", "modelInference": False,
            "stdout": runtime_result.stdout, "stderr": runtime_result.stderr,
            "inputsSha256": {name: hashlib.sha256(path.read_bytes()).hexdigest()
                             for name, path in {
                                 "runtimeLibrary": runtime_library,
                                 "llguidanceHeader": llguidance_include / "llguidance.h",
                                 "schema": schema_json, "retainedOutput": observed_output,
                             }.items()},
        }
    (work_dir / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--tokenizer-json", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--mutations", action="store_true")
    parser.add_argument("--runtime-library", type=Path)
    parser.add_argument("--llguidance-include", type=Path)
    parser.add_argument("--schema-json", type=Path)
    parser.add_argument("--observed-output", type=Path)
    args = parser.parse_args()
    print(json.dumps(qualify(
        args.work_dir, args.tokenizer_json, args.source_root, args.mutations,
        runtime_library=args.runtime_library, llguidance_include=args.llguidance_include,
        schema_json=args.schema_json, observed_output=args.observed_output), indent=2))


if __name__ == "__main__":
    main()
