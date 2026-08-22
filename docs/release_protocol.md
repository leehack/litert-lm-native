# LiteRT-LM Native Release Protocol

Native release tags identify this repository's immutable artifact set. Upstream
source identity and native wrapper identity remain separate provenance fields.

## Release identities

| Purpose | Upstream identity | Native release tag | GitHub classification |
| --- | --- | --- | --- |
| Stable | exact upstream `vMAJOR.MINOR.PATCH` tag and commit | the same `vMAJOR.MINOR.PATCH` | release |
| Stable rebuild | same exact stable tag and commit | `vMAJOR.MINOR.PATCH-N` | prerelease |
| Development | exact full upstream commit | `g` plus its first 12 hex characters | prerelease |
| Development rebuild | same exact full commit | `g<12hex>-N` | prerelease |
| Legacy stable rebuild | exact historical stable tag | `vMAJOR.MINOR.PATCH-native.N` | unchanged, read only |

`N` starts at 1 and increases numerically. Legacy `-native.N` releases count
in the same rebuild sequence. Because `v0.16.0-native.1` and
`v0.16.0-native.2` already exist, the next rebuild of that exact upstream line
would be `v0.16.0-3`. The workflow rejects `v0.16.0-1` and `v0.16.0-2` even
though those compact tag strings do not exist.

The development tag is deterministic but abbreviated for usability. The full
40-character upstream commit in `manifest.json` is authoritative. A
development input also names the latest stable `upstreamCompatibilityTag` whose
ABI and capability contract it is expected to satisfy. It does not claim that
the development commit has that stable tag.

## Exact-input workflow

`.github/workflows/native_release.yml` accepts these independent identities:

- `release_tag`: immutable native artifact identity
- `upstream_tag`: exact stable upstream tag, or empty for development
- `upstream_commit`: exact 40-character upstream source commit
- `upstream_compatibility_tag`: stable ABI/capability baseline
- `native_commit`: exact 40-character commit containing the build and bridge
- `correlation_id`: caller-provided audit identifier shared with orchestration
- `publication_approval`: `prepare-only` or `publish`

The workflow checks that a stable tag resolves to the requested commit and that
the dispatched repository ref resolves to `native_commit`. It rejects tag or
release collisions, stable rollback, reuse or decrease of a rebuild number,
legacy output forms, partial publication matrices, and publication without the
required real-model smoke evidence.

`prepare-only` builds and uploads a 14-day release candidate but cannot write a
GitHub release. `publish` is an explicit manual boundary. The publish job
rechecks provenance and history, creates a draft release, validates its assets
and downloaded manifest, and promotes the draft only after validation passes.
Both paths emit `release-result.json`, which binds the caller correlation ID to
the exact workflow run, inputs, commits, validation counts, smoke targets, and
candidate identity. Published releases replace that record with the validated
draft release ID, URL, and GitHub SHA-256 digests before promotion.

The scheduled `.github/workflows/auto_upstream_release.yml` only detects a
consumable stable upstream candidate and uploads `preparation.json`. It has
read-only permissions and cannot dispatch the build or publish.

Cross-repository orchestration should resolve all commits first, dispatch this
workflow against a ref that resolves to `native_commit`, and use
`publication_approval=prepare-only`. A maintainer must separately approve a
publish dispatch. Publication never updates `llamadart` pins.

## Manifest contract

Schema 2 keeps the following sections distinct:

- `release`: native tag, channel, kind, rebuild number, and prerelease class
- `upstream`: repository, stable tag or null, exact commit, compatibility
  baseline, development identity, and any pinned prebuilt overrides
- `native`: repository and exact native build commit
- `abi`: upstream C boundary and bridge ABI versions
- `capabilities`: release-wide behavioral claims
- `platforms`: explicit platform/architecture entries and artifact paths
- `artifacts`: SHA-256 digest and provenance for every packaged file
- `realModelSmokes`: model, fixture, runtime, source commits, platform, and
  passing result recorded by the release run

Schema 1 manifests and all existing archives remain valid for explicit legacy
consumption. New releases emit schema 2 only. Consumers must not infer upstream
source, capability, platform support, or rebuild order from the release tag or
filename alone.

## Current upstream boundary

As of 2026-08-22, upstream `v0.16.1` and `v0.16.0` resolve to the same commit,
`924e79c91542761242244e4f1651851f822e4cbb`. The `v0.16.1` release publishes
only `litert_lm_main.macos_arm64`; it does not publish the required official C
runtime XCFramework assets. It is therefore not a new consumable native source
line. The latest consumable native artifact remains the immutable legacy release
`v0.16.0-native.2` until a separately approved release is built and validated.
