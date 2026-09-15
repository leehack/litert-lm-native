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

## Runtime bytes and model evidence

A model smoke's library digest must identify the final packaged runtime. macOS
source builds normalize the dylib install name to `@rpath/libLiteRtLm.dylib`
during staging, before loading the library for the smoke. Apple packaging checks
the same identity and leaves an already-normalized dylib untouched. Any later
runtime byte change requires a fresh model smoke; never rewrite a recorded digest
to make older evidence match a different binary.

The macOS regression test compiles a real Mach-O dylib and runs the production
staging and packaging functions. It verifies successful strict manifest binding
and rejection after a post-smoke install-name change. This is packaging coverage;
its synthetic model fields are not real-model qualification evidence.

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
the dispatched repository ref resolves exactly to `native_commit`, which must
also already be reachable from `main`. This binds the workflow definition and
the checked-out release tooling to the same source revision instead of silently
mixing a newer workflow with older scripts. It rejects tag or
release collisions, stable rollback, orphan rebuilds without the aligned base
and immediate lower same-line predecessor, reuse or decrease of a rebuild number,
legacy output forms, partial publication matrices, and publication without the
required real-model smoke evidence.

Stable manual preflight applies the same consumability decision as scheduled
detection before any of the nine platform builds start. A metadata-only tag at
an already packaged commit is rejected unless the requested native identity is
an explicitly ordered rebuild, and every stable input must publish the required
official iOS and macOS C-runtime XCFramework archives. This makes upstream
`v0.16.1` fail before matrix allocation.

`prepare-only` builds and uploads a 14-day release candidate but cannot write a
GitHub release. `publish` is an explicit manual boundary. The publish job
runs automatically after successful full qualification when a maintainer explicitly
dispatches `publication_approval=publish` on canonical repository `main`, with
`native_commit` equal to the dispatch SHA. This is the publication intent boundary;
there is no additional reviewer environment or PAT dependency. Other events,
repositories, refs, partial matrices, and disabled smokes cannot publish.
Only the isolated publication job receives `contents: write`; build jobs and
upstream code retain read permissions and no persisted checkout credentials.
Before any release mutation, trusted dispatch-SHA tools validate the candidate's
full manifest and all three CPU model smokes (Linux x64, Windows x64, macOS arm64),
and reconstruct its result against exact inputs, correlation ID and workflow run.
Failed-job retries may reuse a successful package artifact from an earlier attempt
of the same run; future attempts and cross-run artifacts fail closed. The job
shares a non-canceling repository-wide concurrency group with every other
publication job, so its final history recheck and all later mutations are
serialized across release tags. The job
rechecks provenance and history, creates a draft release, validates its assets
and downloaded manifest, and promotes the draft only after validation passes.
Draft state is deterministic: a retry may resume only a still-draft release
whose target commit, title, prerelease class, exact-input notes, and correlation
identity all match. The notes also bind the original GitHub workflow run ID, so
only a failed-job rerun of that exact run may replace partial assets; a new
dispatch cannot take over the draft even if its caller reuses the correlation
ID. The lightweight candidate tag must still target the exact native commit. A
matching retry removes partial draft assets and uploads the
candidate again. If draft promotion succeeded remotely but the client lost the
response, an exact retry revalidates the published release, tag target, complete
asset bytes, manifest, and stored transaction result, then exits without a
write. Any mismatch or unrelated published collision fails closed. Before
promotion, every GitHub asset name, uploaded state, byte size, and SHA-256 must
match the locally prepared candidate, and the release/tag identity is queried
and validated again after the final result upload. An
upload or validation failure therefore leaves a non-public draft that can be
safely retried without deleting or rewriting a published release.
Both paths emit `release-result.json`, which binds the caller correlation ID to
the exact workflow run, inputs, commits, validation counts, smoke targets, and
candidate identity. Published releases replace that record with the validated
draft release ID, URL, and GitHub SHA-256 digests before promotion.

Pull requests that change release tooling run the read-only
`.github/workflows/pr_release_qualification.yml` workflow. Its inputs are fixed
to the current compatible stable line; it checks out the exact pull-request
head, builds all nine platform targets, and requires pinned real-model evidence
on Linux x64, Windows x64, and macOS arm64. It contains no publication input,
write permission, release command, or call into the write-scoped publication
job.

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
- `realModelSmokes`: model, tokenizer, fixture, and runtime hashes; immutable
  source URLs/release asset; exact commits; ABI/backend; transcript expectation;
  platform; and passing transcript recorded by the release run

Schema 2 requires the exact package identity, all nine platform records, every
native artifact bound to one platform with digest and provenance, and complete
release/ABI/capability declarations. The owner-generated canonical fixture is
checked at `tools/fixtures/schema2_contract_manifest.json`.

Schema 1 manifests and all existing archives remain valid for explicit legacy
consumption; they never require the schema-2-only `release-result.json` asset.
New releases emit schema 2 only. Consumers must not infer upstream
source, capability, platform support, or rebuild order from the release tag or
filename alone.

## Current upstream boundary

As of 2026-08-22, upstream `v0.16.1` and `v0.16.0` resolve to the same commit,
`924e79c91542761242244e4f1651851f822e4cbb`. The `v0.16.1` release publishes
only `litert_lm_main.macos_arm64`; it does not publish the required official C
runtime XCFramework assets. It is therefore not a new consumable native source
line. The latest consumable native artifact remains the immutable legacy release
`v0.16.0-native.2` until a separately approved release is built and validated.

### Draft tags and interrupted publication

Creating a GitHub draft does not necessarily create its Git tag. Read-only
preflight and publication-history checks accept a genuine tag API 404 only for
one reconciled exact draft transaction. Published releases always require the
exact lightweight tag; permission, rate-limit, server, transport, malformed
response, wrong-target, and annotated-tag failures are not missing-tag evidence.

After full qualification, the serialized publication job reconciles the draft
again and verifies any existing partial assets against the retained candidate.
Only this writer may create a missing lightweight ref, using the create endpoint
and the exact native commit. It never updates, force-pushes, or deletes a ref.
A conflict or uncertain create response requires independent exact ref readback
and unchanged release identity and assets before any asset replacement. Later
promotion checks remain strict. An interrupted exact draft/ref is retained for
safe same-run recovery; no automatic tag rollback is attempted.

Release receipts use the canonical repository/tag URL derived from exact inputs.
GitHub can give drafts an ephemeral `untagged-...` URL even when the tag exists;
publishing changes that presentation URL without changing transaction identity.
The receipt still binds the exact release ID and complete asset digests.

A retry may also encounter the final validated receipt uploaded just before a
failed promotion. This receipt is accepted only with the complete byte-exact
candidate, its recorded GitHub digest, and a reconstructed exact same-run result
from a prior or current attempt. Foreign receipts and mismatched partial assets
fail before any deletion or upload.

Merging a lifecycle fix does not change code pinned to an existing failed run.
A draft remains bound to its original workflow run, native commit, upstream
identity, and correlation ID. Recovery of a transaction created by older code
requires a separate explicit decision about bounded continuation or retirement
before a new qualified transaction. Never adopt or relabel its retained candidate
as a new run or native commit.

Run the maintained stateful workflow suite with
`python3 tests/test_release_tag_lifecycle.py`. It requires Bash 4 or newer;
set `LIFECYCLE_BASH=/path/to/bash` when the default shell binary is older.
The `Publication lifecycle` Ubuntu CI job runs this suite separately from the
macOS `tools/` unit-test discovery. It uses a local fake GitHub service and
never dispatches or mutates a real release.


### ASR smoke asset downloads

The three immutable Moonshine smoke assets keep their pinned source URLs and
SHA-256 values. Each uncached asset download has at most three attempts, a
30-second socket timeout, and a 300-second elapsed budget. The elapsed budget
includes process startup, DNS, connection/redirect/header handling, body reads,
backoff and checksum verification. A supervised worker writes only temporary
staging files; timeout kills and waits for that worker, and only the parent may
atomically replace the cached asset after verified success within the budget.

HTTP 429, 500, 502, 503, 504 and transport failures may retry. Permanent HTTP
errors and checksum mismatches fail immediately. Retry-After accepts bounded
seconds or HTTP dates, caps waits at 30 seconds, and never extends the remaining
budget; malformed, negative or oversized values use bounded exponential backoff.
Errors identify the asset and failure class without remote URLs or raw exception
text. Failed transfers remove temporary files and leave an existing cache file
unchanged; every cache hit still requires its exact checksum, so an existing
corrupt file is never treated as verified.

Other shared-downloader consumers retain their existing in-process timeout
behavior unless they explicitly request the elapsed budget. Shared retries now
reject permanent HTTP failures immediately and use safe diagnostics. The tests in
`tools/test_download_utils.py` use a local HTTP server and the real worker path,
including 429 recovery, truncated/stalled/trickling responses, redirects, header
bounds, checksum rejection, cache preservation and worker cleanup.
