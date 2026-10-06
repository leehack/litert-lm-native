from __future__ import annotations

import plistlib
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import apple_privacy_manifest as validator
import package_apple_xcframeworks as packager
import package_ios_runtime as ios

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "tools" / "apple_privacy_manifest.py"
MACHO = b"\xcf\xfa\xed\xfe"
IOS = "ios-arm64"
MACOS = "macos-arm64"
METAL = "LiteRtMetalAccelerator"
MODEL_FILES = ("C617.1", "3B52.1")


def framework_root(name: str, identifier: str) -> str:
    return f"{name}.xcframework/{identifier}/{name}.framework"


def manifest_path(name: str, identifier: str) -> str:
    resources = "Versions/A/Resources/" if identifier.startswith("macos") else ""
    return f"{framework_root(name, identifier)}/{resources}PrivacyInfo.xcprivacy"


def binary_path(name: str, identifier: str) -> str:
    version = "Versions/A/" if identifier.startswith("macos") else ""
    return f"{framework_root(name, identifier)}/{version}{name}"


def manifest(name: str, platform: str, **overrides: object) -> bytes:
    content = plistlib.loads(validator.manifest_bytes(name, platform))
    content.update(overrides)
    return plistlib.dumps(content)


def accessed(category: object, *reasons: object) -> dict[str, object]:
    return {
        "NSPrivacyAccessedAPIType": category,
        "NSPrivacyAccessedAPITypeReasons": list(reasons),
    }


def library(identifier: str, path: str) -> dict[str, str]:
    return {
        "LibraryIdentifier": identifier,
        "LibraryPath": path,
        "SupportedPlatform": identifier.split("-", 1)[0],
    }


def write_archive(
    directory: str,
    members: dict[str, bytes | None],
    *,
    name: str = METAL,
    identifiers: tuple[str, ...] = (IOS, MACOS),
    libraries: list[dict[str, str]] | None = None,
) -> Path:
    """Write an XCFramework zip of framework slices; None drops a member."""
    content: dict[str, bytes | None] = {
        f"{name}.xcframework/Info.plist": plistlib.dumps(
            {
                "AvailableLibraries": libraries
                or [library(identifier, f"{name}.framework") for identifier in identifiers]
            }
        ),
    }
    if libraries is None:
        for identifier in identifiers:
            platform = identifier.split("-", 1)[0]
            content[binary_path(name, identifier)] = MACHO + platform.encode()
            content[manifest_path(name, identifier)] = validator.manifest_bytes(name, platform)
    content.update(members)
    archive = Path(directory) / "xcframework.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        for member, data in content.items():
            if data is not None:
                bundle.writestr(member, data)
    return archive


class DeclarationTests(unittest.TestCase):
    def test_each_framework_declares_only_its_audited_reasons(self) -> None:
        self.assertEqual(
            {
                ("LiteRtLm", "ios"): {
                    validator.FILE_TIMESTAMP: MODEL_FILES,
                    validator.SYSTEM_BOOT_TIME: ("35F9.1",),
                },
                ("LiteRtLm", "macos"): {validator.FILE_TIMESTAMP: MODEL_FILES},
                ("CLiteRTLM", "ios"): {},
                (METAL, "ios"): {
                    validator.FILE_TIMESTAMP: MODEL_FILES,
                    validator.USER_DEFAULTS: ("CA92.1",),
                },
                (METAL, "macos"): {validator.FILE_TIMESTAMP: MODEL_FILES},
                ("LiteRtTopKMetalSampler", "ios"): {validator.USER_DEFAULTS: ("CA92.1",)},
                ("LiteRtTopKMetalSampler", "macos"): {},
            },
            validator.DECLARATIONS,
        )

    def test_generated_manifests_are_valid_and_report_no_tracking_or_collection(self) -> None:
        for (name, platform), declaration in validator.DECLARATIONS.items():
            with self.subTest(name=name, platform=platform):
                data = validator.manifest_bytes(name, platform)
                content = plistlib.loads(data)

                self.assertEqual(([], declaration), validator.validate_manifest(data))
                self.assertIs(False, content["NSPrivacyTracking"])
                self.assertEqual([], content["NSPrivacyTrackingDomains"])
                self.assertEqual([], content["NSPrivacyCollectedDataTypes"])

    def test_unaudited_framework_has_no_manifest(self) -> None:
        for name, platform in (("LiteRtWebGpuAccelerator", "ios"), ("CLiteRTLM", "macos")):
            with self.subTest(name=name, platform=platform), self.assertRaisesRegex(
                RuntimeError, f"No audited Apple privacy declaration for {name} on {platform}"
            ):
                validator.manifest_bytes(name, platform)

    @unittest.skipUnless(sys.platform == "darwin", "plutil ships with macOS")
    def test_generated_manifests_pass_plutil_lint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for name, platform in validator.DECLARATIONS:
                path = Path(directory) / f"{name}-{platform}.xcprivacy"
                path.write_bytes(validator.manifest_bytes(name, platform))
                subprocess.run(["plutil", "-lint", str(path)], check=True, capture_output=True)


class PackagerTests(unittest.TestCase):
    def test_ios_framework_carries_its_manifest_in_the_bundle_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source" / f"{METAL}.framework"
            source.mkdir(parents=True)
            (source / METAL).write_bytes(MACHO)

            framework = packager.prepare_framework(
                source, Path(directory) / "work" / source.name, METAL
            )

            self.assertEqual(
                validator.manifest_bytes(METAL, "ios"),
                (framework / "PrivacyInfo.xcprivacy").read_bytes(),
            )
            self.assertFalse((source / "PrivacyInfo.xcprivacy").exists())

    def test_macos_framework_carries_its_manifest_in_versioned_resources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            library_file = Path(directory) / f"lib{METAL}.dylib"
            library_file.write_bytes(MACHO)
            with patch.object(packager, "run"):
                framework = Path(
                    packager.make_macos_framework_argument(
                        METAL, {"arm64": library_file}, Path(directory) / "work"
                    )[1]
                )

            self.assertEqual(
                validator.manifest_bytes(METAL, "macos"),
                (framework / "Versions/A/Resources/PrivacyInfo.xcprivacy").read_bytes(),
            )
            self.assertEqual(
                ["Headers", METAL, "Modules", "Resources", "Versions"],
                sorted(path.name for path in framework.iterdir()),
            )

    def test_unaudited_framework_is_not_packaged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source" / "Unaudited.framework"
            source.mkdir(parents=True)
            (source / "Unaudited").write_bytes(MACHO)
            with self.assertRaisesRegex(RuntimeError, "No audited Apple privacy declaration"):
                packager.prepare_framework(
                    source, Path(directory) / "work" / source.name, "Unaudited"
                )

    def test_packaging_fails_before_reporting_an_archive_that_fails_the_audit(self) -> None:
        archives = [ROOT / "dist/first.zip", ROOT / "dist/second.zip"]
        arguments = ["package", "--release-tag", "v0.17.0-8", "--compatibility-tag", "v0.17.0"]
        for errors in ([], [f"{IOS}: under-declared"]):
            with self.subTest(errors=errors), patch.object(sys, "argv", arguments), patch.object(
                packager, "package_all", return_value=archives
            ), patch.object(packager, "validate_ios_archives"), patch.object(
                packager, "validate_archive", return_value=errors
            ) as validate:
                if errors:
                    with self.assertRaisesRegex(
                        RuntimeError, f"first.zip: {IOS}: under-declared"
                    ):
                        packager.main()
                else:
                    self.assertEqual(0, packager.main())
                self.assertEqual(
                    [((archive,), {"audit_imports": True}) for archive in archives],
                    [tuple(call) for call in validate.call_args_list],
                )

    def test_release_packages_and_audits_before_checksums_and_upload(self) -> None:
        workflow = (ROOT / ".github/workflows/native_release.yml").read_text()

        self.assertTrue(
            -1
            < workflow.find("python3 tools/package_apple_xcframeworks.py")
            < workflow.find("python3 tools/package_release.py")
            < workflow.find("Create release archives")
            < workflow.find("Upload prepared release candidate")
        )

    def test_pull_requests_run_these_tests_on_macos(self) -> None:
        workflow = (ROOT / ".github/workflows/validate.yml").read_text()
        job = workflow.split("  validate:\n", 1)[1].split("\n  publication-lifecycle:", 1)[0]

        self.assertIn("runs-on: macos-latest", job)
        self.assertIn("python3 -m unittest discover -s tools -p 'test_*.py'", job)


class ValidateArchiveTests(unittest.TestCase):
    def errors(self, members: dict[str, bytes | None], **archive: object) -> list[str]:
        with tempfile.TemporaryDirectory() as directory:
            return validator.validate_archive(write_archive(directory, members, **archive))

    def test_accepts_the_audited_manifest_in_every_framework_slice(self) -> None:
        self.assertEqual([], self.errors({}))

    def test_rejects_a_slice_without_a_manifest(self) -> None:
        path = manifest_path(METAL, IOS)

        self.assertEqual(
            [f"{IOS}: missing privacy manifest at {path}"], self.errors({path: None})
        )

    def test_rejects_a_manifest_outside_the_versioned_resources_directory(self) -> None:
        path = manifest_path(METAL, MACOS)
        stray = f"{framework_root(METAL, MACOS)}/PrivacyInfo.xcprivacy"

        self.assertEqual(
            [
                f"{MACOS}: unexpected privacy manifest at {stray}",
                f"{MACOS}: missing privacy manifest at {path}",
            ],
            self.errors({path: None, stray: validator.manifest_bytes(METAL, "macos")}),
        )

    def test_rejects_a_manifest_that_is_not_a_property_list(self) -> None:
        path = manifest_path(METAL, MACOS)
        errors = self.errors({path: b"<plist><dict>"})

        self.assertEqual(1, len(errors))
        self.assertIn(f"{path} is not a valid property list", errors[0])

    def test_rejects_inaccurate_declarations(self) -> None:
        timestamp = validator.FILE_TIMESTAMP
        cases = {
            "NSPrivacyTracking must be false": manifest(METAL, "ios", NSPrivacyTracking=True),
            "NSPrivacyCollectedDataTypes must be an empty array": manifest(
                METAL, "ios", NSPrivacyCollectedDataTypes=[{"NSPrivacyCollectedDataType": "x"}]
            ),
            "NSPrivacyAccessedAPITypes must be an array": manifest(
                METAL, "ios", NSPrivacyAccessedAPITypes="C617.1"
            ),
            "unknown required-reason API category: 'Timestamp'": manifest(
                METAL, "ios", NSPrivacyAccessedAPITypes=[accessed("Timestamp", "C617.1")]
            ),
            f"{timestamp} declares unapproved reason '35F9.1'": manifest(
                METAL, "ios", NSPrivacyAccessedAPITypes=[accessed(timestamp, "35F9.1")]
            ),
            f"{timestamp} must declare at least one reason": manifest(
                METAL, "ios", NSPrivacyAccessedAPITypes=[accessed(timestamp)]
            ),
            "unknown required-reason API category: ['Timestamp']": manifest(
                METAL, "ios", NSPrivacyAccessedAPITypes=[accessed(["Timestamp"], "C617.1")]
            ),
            f"{timestamp} declares unapproved reason ['C617.1']": manifest(
                METAL, "ios", NSPrivacyAccessedAPITypes=[accessed(timestamp, ["C617.1"])]
            ),
            f"{timestamp} is declared more than once": manifest(
                METAL,
                "ios",
                NSPrivacyAccessedAPITypes=[
                    accessed(timestamp, *MODEL_FILES),
                    accessed(timestamp, *MODEL_FILES),
                ],
            ),
        }
        path = manifest_path(METAL, IOS)
        for expected, data in cases.items():
            with self.subTest(expected=expected):
                self.assertEqual([f"{IOS}: {path} {expected}"], self.errors({path: data}))

    def test_rejects_a_valid_manifest_that_belongs_to_another_framework(self) -> None:
        path = manifest_path(METAL, IOS)
        cases = {
            "another framework": validator.manifest_bytes("LiteRtTopKMetalSampler", "ios"),
            "another platform": validator.manifest_bytes(METAL, "macos"),
            "another approved reason": manifest(
                METAL,
                "ios",
                NSPrivacyAccessedAPITypes=[
                    accessed(validator.FILE_TIMESTAMP, "C617.1"),
                    accessed(validator.USER_DEFAULTS, "CA92.1"),
                ],
            ),
        }
        for case, data in cases.items():
            with self.subTest(case=case):
                self.assertEqual(
                    [f"{IOS}: {path} differs from the audited declaration for {METAL} on ios"],
                    self.errors({path: data}),
                )

    def test_rejects_a_framework_without_an_audited_declaration(self) -> None:
        name = "LiteRtWebGpuAccelerator"
        members = {
            binary_path(name, IOS): MACHO,
            manifest_path(name, IOS): validator.manifest_bytes("CLiteRTLM", "ios"),
        }

        self.assertEqual(
            [f"{IOS}: no audited privacy declaration for {name} on ios"],
            self.errors(members, name=name, libraries=[library(IOS, f"{name}.framework")]),
        )

    def test_bare_library_slices_are_limited_to_macos(self) -> None:
        name = "CLiteRTLMMac"
        dylib = "libCLiteRTLM_mac.dylib"
        cases = {
            MACOS: [],
            IOS: [f"{IOS}: {dylib} is not a framework and cannot carry a privacy manifest"],
        }
        for identifier, expected in cases.items():
            with self.subTest(identifier=identifier):
                self.assertEqual(
                    expected,
                    self.errors(
                        {f"{name}.xcframework/{identifier}/{dylib}": MACHO},
                        name=name,
                        libraries=[library(identifier, dylib)],
                    ),
                )

    def test_rejects_a_manifest_beside_a_bare_library(self) -> None:
        name = "CLiteRTLMMac"
        dylib = "libCLiteRTLM_mac.dylib"
        stray = f"{name}.xcframework/{MACOS}/PrivacyInfo.xcprivacy"

        self.assertEqual(
            [f"{MACOS}: unexpected privacy manifest at {stray}"],
            self.errors(
                {
                    f"{name}.xcframework/{MACOS}/{dylib}": MACHO,
                    stray: validator.manifest_bytes("CLiteRTLM", "ios"),
                },
                name=name,
                libraries=[library(MACOS, dylib)],
            ),
        )

    def test_import_audit_requires_declarations_to_match_each_framework(self) -> None:
        references = {
            MACHO + b"ios": ({"_fstat", "_mach_absolute_time"}, set()),
            MACHO + b"macos": ({"_abort"}, set()),
        }
        with tempfile.TemporaryDirectory() as directory, patch.object(
            validator,
            "binary_api_references",
            side_effect=lambda binary: references[binary.read_bytes()],
        ):
            errors = validator.validate_archive(
                write_archive(directory, {}), audit_imports=True
            )

        self.assertEqual(
            [
                f"{IOS}: uses {validator.SYSTEM_BOOT_TIME} via _mach_absolute_time "
                "but the manifest does not declare it",
                f"{IOS}: manifest declares {validator.USER_DEFAULTS} but the "
                "binary uses none of its APIs",
                f"{MACOS}: manifest declares {validator.FILE_TIMESTAMP} but the "
                "binary uses none of its APIs",
            ],
            errors,
        )

    def test_import_audit_covers_dylibs_nested_in_the_framework(self) -> None:
        nested = f"{framework_root(METAL, MACOS)}/Versions/A/Dependencies/libnested.dylib"
        references = {
            MACHO + b"ios": ({"_fstat", "_OBJC_CLASS_$_NSUserDefaults"}, set()),
            MACHO + b"macos": ({"_abort"}, set()),
            MACHO + b"nested": ({"_fstat", "_statfs"}, set()),
        }
        with tempfile.TemporaryDirectory() as directory, patch.object(
            validator,
            "binary_api_references",
            side_effect=lambda binary: references[binary.read_bytes()],
        ):
            errors = validator.validate_archive(
                write_archive(directory, {nested: MACHO + b"nested"}), audit_imports=True
            )

        self.assertEqual(
            [
                f"{MACOS}: uses {validator.DISK_SPACE} via _statfs but the manifest "
                "does not declare it"
            ],
            errors,
        )

    def test_import_audit_rejects_swift_imports_it_cannot_attribute(self) -> None:
        references = {
            MACHO + b"ios": (
                {"_fstat", "_OBJC_CLASS_$_NSUserDefaults", "_$s10Foundation4DateVMa"},
                set(),
            ),
            MACHO + b"macos": ({"_fstat"}, set()),
        }
        with tempfile.TemporaryDirectory() as directory, patch.object(
            validator,
            "binary_api_references",
            side_effect=lambda binary: references[binary.read_bytes()],
        ):
            errors = validator.validate_archive(
                write_archive(directory, {}), audit_imports=True
            )

        self.assertEqual(
            [
                f"{IOS}: imports Swift symbols such as _$s10Foundation4DateVMa, "
                "which this audit does not cover"
            ],
            errors,
        )

    def test_import_audit_rejects_a_framework_without_a_binary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            errors = validator.validate_archive(
                write_archive(directory, {binary_path(METAL, IOS): b"text"}, identifiers=(IOS,)),
                audit_imports=True,
            )

        self.assertEqual(
            [f"{IOS}: {framework_root(METAL, IOS)} contains no Mach-O binary"], errors
        )

    def test_cli_fails_on_an_unreadable_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "xcframework.zip"
            archive.write_bytes(b"not a zip")
            result = subprocess.run(
                [sys.executable, str(VALIDATOR), str(archive)],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(1, result.returncode)
        self.assertIn("error: xcframework.zip:", result.stderr)


class RequiredCategoryTests(unittest.TestCase):
    def test_maps_symbol_variants_classes_and_selectors_to_categories(self) -> None:
        self.assertEqual(
            {
                validator.FILE_TIMESTAMP: ["_fstat", "_stat"],
                validator.SYSTEM_BOOT_TIME: ["systemUptime"],
                validator.DISK_SPACE: ["_statfs"],
                validator.USER_DEFAULTS: ["_OBJC_CLASS_$_NSUserDefaults"],
            },
            validator.required_categories(
                {
                    "_stat$INODE64",
                    "_fstat",
                    "_statfs$INODE64",
                    "_OBJC_CLASS_$_NSUserDefaults",
                    "_clock_gettime",
                },
                {"systemUptime", "fileURLWithPath:", "boolForKey:"},
            ),
        )

    def test_user_defaults_reached_without_a_class_symbol_still_count(self) -> None:
        for selector in ("standardUserDefaults", "initWithSuiteName:"):
            with self.subTest(selector=selector):
                self.assertEqual(
                    {validator.USER_DEFAULTS: [selector]},
                    validator.required_categories({"_objc_getClass"}, {selector}),
                )


class ToolOutputParsingTests(unittest.TestCase):
    def test_reads_symbols_and_selectors_from_data_rows_of_every_architecture(self) -> None:
        outputs = {
            "nm": (
                "\n/tmp/systemUptime (for architecture x86_64):\n"
                "_stat$INODE64\n"
                "\n/tmp/systemUptime (for architecture arm64):\n"
                "                 U _mach_absolute_time\n"
            ),
            "otool": (
                "/tmp/systemUptime (architecture x86_64):\n"
                "Contents of (__TEXT,__objc_methname) section\n"
                "0000000000003f8a  boolForKey:\n"
                "/tmp/systemUptime (architecture arm64):\n"
                "Contents of (__TEXT,__objc_methname) section\n"
                "0000000000003f9b  standardUserDefaults\n"
            ),
        }
        with patch.object(
            validator, "tool_output", side_effect=lambda command: outputs[command[0]]
        ) as tool:
            references = validator.binary_api_references(Path("/tmp/systemUptime"))

        self.assertEqual(
            ({"_stat$INODE64", "_mach_absolute_time"}, {"boolForKey:", "standardUserDefaults"}),
            references,
        )
        for (command,), _ in tool.call_args_list:
            self.assertEqual(["-arch", "all"], command[command.index("-arch") :][:2])


@unittest.skipUnless(
    sys.platform == "darwin",
    "needs the Apple toolchain to build and inspect Mach-O binaries",
)
class MachOImportAuditTests(unittest.TestCase):
    PLAIN = "int plain(void) { return 1; }\n"
    REQUIRED_REASON = (
        "#import <Foundation/Foundation.h>\n"
        "#include <mach/mach_time.h>\n"
        "#include <sys/stat.h>\n"
        "double required_reason(int fd) {\n"
        "  struct stat info;\n"
        "  fstat(fd, &info);\n"
        '  stat("/", &info);\n'
        "  return [[NSProcessInfo processInfo] systemUptime] + mach_absolute_time();\n"
        "}\n"
    )
    DEFAULTS_BY_CLASS = (
        "#import <Foundation/Foundation.h>\n"
        "BOOL verbose(void) {\n"
        '  return [[NSUserDefaults standardUserDefaults] boolForKey:@"Verbose"];\n'
        "}\n"
    )
    DEFAULTS_BY_NAME = (
        "#import <Foundation/Foundation.h>\n"
        "#import <objc/runtime.h>\n"
        "BOOL verbose(void) {\n"
        '  id defaults = [(id)objc_getClass("NSUserDefaults") standardUserDefaults];\n'
        '  return [defaults boolForKey:@"Verbose"];\n'
        "}\n"
    )

    def dylib(self, work: Path, sources: dict[str, str], *, name: str = "fixture") -> Path:
        """Build a dylib with one source per architecture, fat when there are two."""
        thin = []
        for arch, source in sources.items():
            source_file = work / f"{name}-{arch}.m"
            source_file.write_text(source, encoding="utf-8")
            thin.append(work / f"{name}-{arch}.dylib")
            subprocess.run(
                [
                    "xcrun", "clang", "-dynamiclib", "-arch", arch,
                    "-framework", "Foundation", str(source_file), "-o", str(thin[-1]),
                ],
                check=True,
                capture_output=True,
            )
        if len(thin) == 1:
            return thin[0]
        fat = work / f"{name}.dylib"
        subprocess.run(
            ["xcrun", "lipo", "-create", *map(str, thin), "-output", str(fat)],
            check=True,
            capture_output=True,
        )
        return fat

    def audit(self, directory: str, name: str, identifier: str, binary: Path) -> list[str]:
        archive = write_archive(
            directory,
            {binary_path(name, identifier): binary.read_bytes()},
            name=name,
            identifiers=(identifier,),
        )
        return validator.validate_archive(archive, audit_imports=True)

    def test_audits_every_architecture_of_a_fat_slice(self) -> None:
        architectures = ("arm64", "x86_64")
        for importing in architectures:
            with self.subTest(importing=importing), tempfile.TemporaryDirectory() as directory:
                binary = self.dylib(
                    Path(directory),
                    {
                        arch: self.REQUIRED_REASON if arch == importing else self.PLAIN
                        for arch in architectures
                    },
                )

                self.assertEqual(
                    [
                        f"{IOS}: uses {validator.FILE_TIMESTAMP} via _fstat, _stat "
                        "but the manifest does not declare it",
                        f"{IOS}: uses {validator.SYSTEM_BOOT_TIME} via "
                        "_mach_absolute_time, systemUptime but the manifest does "
                        "not declare it",
                    ],
                    self.audit(directory, "CLiteRTLM", IOS, binary),
                )

    def test_detects_user_defaults_by_class_reference_and_by_selector(self) -> None:
        cases = {
            self.DEFAULTS_BY_CLASS: "_OBJC_CLASS_$_NSUserDefaults, standardUserDefaults",
            self.DEFAULTS_BY_NAME: "standardUserDefaults",
        }
        for source, evidence in cases.items():
            with self.subTest(evidence=evidence), tempfile.TemporaryDirectory() as directory:
                binary = self.dylib(Path(directory), {"arm64": source})

                self.assertEqual(
                    [
                        f"{IOS}: uses {validator.USER_DEFAULTS} via {evidence} but "
                        "the manifest does not declare it"
                    ],
                    self.audit(directory, "CLiteRTLM", IOS, binary),
                )
                self.assertEqual(
                    [], self.audit(directory, "LiteRtTopKMetalSampler", IOS, binary)
                )

    def test_accepts_a_binary_that_references_no_required_reason_api(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            binary = self.dylib(Path(directory), {"arm64": self.PLAIN, "x86_64": self.PLAIN})

            self.assertEqual([], self.audit(directory, "CLiteRTLM", IOS, binary))
            self.assertEqual(
                [
                    f"{IOS}: manifest declares {validator.USER_DEFAULTS} but the "
                    "binary uses none of its APIs"
                ],
                self.audit(directory, "LiteRtTopKMetalSampler", IOS, binary),
            )

    def test_audits_a_dylib_nested_in_a_framework(self) -> None:
        name = "LiteRtTopKMetalSampler"
        nested = f"{framework_root(name, MACOS)}/Versions/A/Dependencies/libnested.dylib"
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            archive = write_archive(
                directory,
                {
                    binary_path(name, MACOS): self.dylib(
                        work, {"arm64": self.PLAIN}, name="main"
                    ).read_bytes(),
                    nested: self.dylib(
                        work, {"arm64": self.PLAIN, "x86_64": self.REQUIRED_REASON}
                    ).read_bytes(),
                },
                name=name,
                identifiers=(MACOS,),
            )

            self.assertEqual(
                [
                    f"{MACOS}: uses {validator.FILE_TIMESTAMP} via _fstat, _stat "
                    "but the manifest does not declare it",
                    f"{MACOS}: uses {validator.SYSTEM_BOOT_TIME} via "
                    "_mach_absolute_time, systemUptime but the manifest does "
                    "not declare it",
                ],
                validator.validate_archive(archive, audit_imports=True),
            )


@unittest.skipUnless(sys.platform == "darwin", "packages with xcodebuild and codesign")
class PackagedXcframeworkTests(unittest.TestCase):
    NAME = "LiteRtTopKMetalSampler"
    DEFAULTS = MachOImportAuditTests.DEFAULTS_BY_CLASS
    UNDECLARED = DEFAULTS + (
        "#include <sys/stat.h>\n"
        "long long size(int fd) { struct stat info; fstat(fd, &info); return info.st_size; }\n"
    )

    def build(self, directory: Path, sdk: str, source: str) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        source_file = directory / "fixture.m"
        source_file.write_text(source, encoding="utf-8")
        output = directory / f"lib{self.NAME}.dylib"
        minimum = {
            "iphoneos": ["-miphoneos-version-min=15.0"],
            "iphonesimulator": ["-mios-simulator-version-min=15.0"],
            "macosx": [],
        }[sdk]
        subprocess.run(
            [
                "xcrun", "--sdk", sdk, "clang", "-dynamiclib", "-arch", "arm64", *minimum,
                "-framework", "Foundation", str(source_file), "-o", str(output),
            ],
            check=True,
            capture_output=True,
        )
        return output

    def package(self, root: Path, device_source: str) -> Path:
        for arch, sdk, source in (
            ("arm64", "iphoneos", device_source),
            ("arm64-sim", "iphonesimulator", self.DEFAULTS),
        ):
            target = root / "bin/ios" / arch
            ios.stage_dependency_framework({"sdk": sdk}, target, self.build(target, sdk, source))
        macos = self.build(root / "bin/macos/arm64", "macosx", MachOImportAuditTests.PLAIN)
        work = root / "work"
        work.mkdir(exist_ok=True)
        with patch.object(packager, "BIN_DIR", root / "bin"):
            return packager.package_ios_framework_module(
                self.NAME,
                work,
                root / "dist",
                "fixture",
                extra_args=packager.make_macos_framework_argument(
                    self.NAME, {"arm64": macos}, work
                ),
            )

    def test_real_archive_passes_the_audit_until_a_slice_gains_an_undeclared_api(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = self.package(root, self.DEFAULTS)
            with zipfile.ZipFile(archive) as bundle:
                names = set(bundle.namelist())

            self.assertEqual(
                {
                    manifest_path(self.NAME, IOS),
                    manifest_path(self.NAME, "ios-arm64-simulator"),
                    manifest_path(self.NAME, MACOS),
                },
                {name for name in names if name.endswith("PrivacyInfo.xcprivacy")},
            )
            packager.validate_privacy_manifests([archive])

            with self.assertRaisesRegex(
                RuntimeError,
                f"{IOS}: uses {validator.FILE_TIMESTAMP} via _fstat but the manifest "
                "does not declare it",
            ):
                packager.validate_privacy_manifests([self.package(root, self.UNDECLARED)])

    def test_signed_macos_framework_seals_its_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            core = self.build(work / "raw", "macosx", MachOImportAuditTests.PLAIN)
            framework = Path(
                packager.make_macos_framework_argument("LiteRtLm", {"arm64": core}, work)[1]
            )
            packager.complete_macos_primary_framework(framework, {}, work)

            subprocess.run(
                ["codesign", "--verify", "--deep", "--strict", str(framework)],
                check=True,
                capture_output=True,
            )
            sealed = plistlib.loads(
                (framework / "Versions/A/_CodeSignature/CodeResources").read_bytes()
            )
            self.assertIn("Resources/PrivacyInfo.xcprivacy", sealed["files2"])


if __name__ == "__main__":
    unittest.main()
