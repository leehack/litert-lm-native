from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import package_upstream_prebuilts


class PackageUpstreamPrebuiltsTest(unittest.TestCase):
    def test_source_archive_filename_never_contains_the_raw_ref_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = package_upstream_prebuilts.source_archive_path(
                root, "refs/tags/x/../../escape"
            )

            self.assertEqual(archive.parent, root)
            self.assertNotIn("refs", archive.name)
            self.assertNotIn("..", archive.name)
            self.assertRegex(archive.name, r"^LiteRT-LM-[0-9a-f]{64}\.tar\.gz$")

    def test_materializes_pointer_before_copying_prebuilt(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_dir = root / "source" / "prebuilt" / "android_arm64"
            source_dir.mkdir(parents=True)
            source = source_dir / "libExample.so"
            source.write_text("git-lfs-pointer", encoding="utf-8")
            output = root / "bin"

            def materialize(
                directory: Path,
                *,
                upstream_tag: str,
                source_root: Path,
                suffixes: tuple[str, ...],
            ) -> int:
                self.assertEqual(directory, source_dir)
                self.assertEqual(upstream_tag, "v0.16.0")
                self.assertEqual(source_root, root / "source")
                self.assertIn(".so", suffixes)
                source.write_bytes(b"\x7fELF materialized")
                return 1

            with patch.object(package_upstream_prebuilts, "BIN_DIR", output):
                with patch.object(
                    package_upstream_prebuilts,
                    "PREBUILT_TARGETS",
                    {"android_arm64": ("android", "arm64")},
                ):
                    with patch.object(
                        package_upstream_prebuilts,
                        "materialize_git_lfs_libraries",
                        side_effect=materialize,
                    ):
                        copied = package_upstream_prebuilts.copy_prebuilts(
                            root / "source",
                            upstream_tag="v0.16.0",
                            clean=True,
                        )

            self.assertEqual(copied, 1)
            self.assertEqual(
                (output / "android" / "arm64" / source.name).read_bytes(),
                b"\x7fELF materialized",
            )

    def test_overrides_only_does_not_download_or_copy_upstream_source(self) -> None:
        with patch(
            "sys.argv",
            [
                "package_upstream_prebuilts.py",
                "--upstream-tag",
                "v0.16.0",
                "--overrides-only",
            ],
        ):
            with patch.object(
                package_upstream_prebuilts,
                "download_source",
            ) as download_source:
                with patch.object(
                    package_upstream_prebuilts,
                    "copy_prebuilts",
                ) as copy_prebuilts:
                    with patch.object(
                        package_upstream_prebuilts,
                        "apply_prebuilt_overrides",
                        return_value=2,
                    ) as apply_overrides:
                        self.assertEqual(package_upstream_prebuilts.main(), 0)

        download_source.assert_not_called()
        copy_prebuilts.assert_not_called()
        apply_overrides.assert_called_once_with("v0.16.0")

    def test_override_application_can_be_scoped_to_one_target(self) -> None:
        with patch.object(
            package_upstream_prebuilts,
            "apply_prebuilt_override",
        ) as apply_override:
            count = package_upstream_prebuilts.apply_prebuilt_overrides(
                "v0.16.0",
                platform="android",
                arch="arm64",
            )

        self.assertEqual(count, 1)
        self.assertEqual(apply_override.call_count, 1)
        selected = apply_override.call_args.args[0]
        self.assertEqual(selected.platform, "android")
        self.assertEqual(selected.arch, "arm64")

    def test_release_applies_overrides_after_runtime_artifact_merge(self) -> None:
        workflow = (
            package_upstream_prebuilts.REPO_ROOT
            / ".github"
            / "workflows"
            / "native_release.yml"
        ).read_text(encoding="utf-8")

        initial_package = workflow.index("- name: Package upstream prebuilt libraries")
        runtime_merge = workflow.index("- name: Merge source-built runtimes")
        final_overrides = workflow.index("- name: Apply pinned prebuilt overrides")
        manifest = workflow.index("- name: Generate and validate provenance manifest")

        self.assertLess(initial_package, runtime_merge)
        self.assertLess(runtime_merge, final_overrides)
        self.assertLess(final_overrides, manifest)
        self.assertIn("--skip-overrides", workflow)
        self.assertIn("--overrides-only", workflow)

    def test_new_release_tag_targets_the_built_commit(self) -> None:
        workflow = (
            package_upstream_prebuilts.REPO_ROOT
            / ".github"
            / "workflows"
            / "native_release.yml"
        ).read_text(encoding="utf-8")

        create_release = workflow[workflow.index('gh release create "'):]
        self.assertIn('--target "$NATIVE_COMMIT"', create_release)
        self.assertIn("tools/publication_state.py", workflow)
        self.assertIn("Create or safely resume exact draft", workflow)
        self.assertIn("releases/assets/$asset_id", workflow)
        self.assertIn("jq -jr .notes", workflow)
        self.assertNotIn("--slurp \\\n            \"repos/${GITHUB_REPOSITORY}/releases?per_page=100\" \\\n            --jq", workflow)
        self.assertIn("jq 'add' existing-release-pages.json", workflow)
        self.assertIn("--draft", create_release)
        self.assertIn("gh release edit", create_release)
        self.assertIn("--draft=false", create_release)
        self.assertIn("gh release upload", create_release)
        self.assertIn("--clobber", create_release)
        self.assertLess(
            create_release.index("gh release upload"),
            create_release.index("gh release edit"),
        )


if __name__ == "__main__":
    unittest.main()
