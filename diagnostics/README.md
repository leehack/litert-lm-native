# Diagnostics

For the explicit Qwen3 model repair, see
[Qwen3 tokenizer repair](../docs/qwen3_tokenizer_repair.md). It is separate from
the runner download workflow below and is never run automatically.

# Runner download diagnostic

This manual-only workflow screens the acquisition failures observed in native
release run `34856149932`, attempts 1 and 2, at native commit
`deef59818b0514c54929d7215c10ed6cba3b0f63` and upstream commit
`e9fd8c53ff968071774206163027dd84bedfe925`. It does not repair a demonstrated
transport defect, publish anything, qualify runtime artifacts or authorize a
publication retry. It does not modify successful attempt-2 artifacts.

The workflow must first be reviewed and merged onto the default branch to become
available for a separately authorized `workflow_dispatch`. It runs on Windows x64,
Ubuntu x64/arm64 and macOS arm64, covering the affected host/network classes.
There are no inputs, production build commands, release permissions, secrets,
mirrors, settings changes or model downloads.

## Samples and bounds

Each runner starts three independent rounds at approximately 0, 300 and 600
seconds. Each round has a 240-second process-tree deadline; the workflow job has a
17-minute deadline. Temporary npm, Bazelisk, Bazel output and repository caches
are new each round. Bazel runs in batch mode and ignores user rc files.

Each round gives the production Python downloader a separate 45-second outer
deadline to download the small pinned rules_shell archive. Its original urllib
User-Agent, redirects, 60-second socket timeout and three-attempt retry policy
remain intact inside that diagnostic deadline. The body is capped at 2 MiB per
attempt; a complete successful body must match the existing upstream SHA-256.
This complete small-archive check does not download or verify the full large
LiteRT-LM source archive.

Next, pinned npm package `@bazel/bazelisk@1.28.1` acquires/selects Bazel 7.6.1 with a
75-second outer deadline. A separate 60-second Bazel `query` fetches only a minimal
`http_archive` using the exact rules_shell URL and SHA-256; its empty filegroup
has no native target or dependency fanout. The fresh repository cache must contain
exactly one archive, independently matching the small pinned checksum and size
bound. This exercises Bazelisk and Bazel's
actual HTTP stacks. It does not claim the historical runners used Bazelisk
1.28.1: their exact bootstrap version was not recorded. npm acquisition is an
additional diagnostic prerequisite and can fail independently.

Finally, four concurrent urllib workers GET the exact failed source, host Bazel
binary and dependency URLs. Each response is limited to 64 KiB, with a 10-second
socket timeout. Eight URLs means at most 512 KiB of sampled response bodies per
round. HTTP 200 plus the expected gzip, ELF, Mach-O or PE prefix is screening
only, not full-body integrity or actual Bazel-client reproduction. Redirects can
consume additional time, so the outer deadline remains authoritative.

The managed clients do not expose a body-byte limit for Bazel/npm acquisition;
they are bounded here by one bootstrap plus one query per round, fresh disposable
caches and process deadlines. No claim of a strict network-byte cap is made for
those clients. A deadline, failed acquisition, missing sample or checksum failure
makes the diagnostic incomplete/failed; it must not count as recovery evidence.
Three passing rounds are operational evidence, not a guarantee the next release
run will succeed. All existing build, checksum, provenance and model gates remain
authoritative.

## Retained evidence and local checks

Only `diagnostic-results/*.json` is uploaded, for seven days. Reports separate the
investigated release identities from the current diagnostic workflow SHA/run ID/
attempt. They contain sanitized redirect host/path, allowlisted HTTP status,
request IDs, cache/Retry-After metadata where available, durations, body bounds,
checksums and client results. Raw client logs, exceptions, headers, signed query
strings, credentials and temporary caches are never uploaded or printed.

Run the offline contract tests with:

```sh
python3 -m unittest discover -s diagnostics -p 'test_*.py'
```

A separately authorized local one-round check can use
`python3 diagnostics/runner_downloads.py --round-report /tmp/download-round.json`.
It is local evidence, not runner evidence. Running the script without arguments
uses the three-round schedule. Diagnostic-only changes do not trigger the full
nine-target PR qualification workflow; the existing Validate job runs these
lightweight tests.
