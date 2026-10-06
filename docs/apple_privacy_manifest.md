# Apple Privacy Manifest

Every framework slice of the Apple SwiftPM XCFramework zips embeds a
`PrivacyInfo.xcprivacy`. Apple requires an SDK to report its own
[required-reason API](https://developer.apple.com/documentation/bundleresources/describing-use-of-required-reason-api)
use on iOS, iPadOS, tvOS, visionOS and watchOS; it cannot rely on the host
app's manifest. `tools/package_apple_xcframeworks.py` generates each manifest
from `DECLARATIONS` in `tools/apple_privacy_manifest.py`, one declaration per
framework and platform, because the frameworks reference different APIs.

## Location

| Slice | Bundle layout | Manifest path inside `<Name>.framework` |
| --- | --- | --- |
| `ios-arm64`, `ios-*-simulator` | flat | `PrivacyInfo.xcprivacy` |
| `macos-*` framework | versioned | `Versions/A/Resources/PrivacyInfo.xcprivacy` |

A manifest in the root of a versioned framework is unsealed content and fails
code signing. The packager writes the manifest before it ad-hoc signs the
macOS `LiteRtLm.framework`, so that signature seals it. The other frameworks
are sealed when the consumer's Xcode build embeds and signs them.

## Declarations

No framework tracks, contacts tracking domains, or collects data.

| Framework | Platform | Category | Reasons |
| --- | --- | --- | --- |
| `LiteRtLm` | iOS | File Timestamp | `C617.1`, `3B52.1` |
| `LiteRtLm` | iOS | System Boot Time | `35F9.1` |
| `LiteRtLm` | macOS | File Timestamp | `C617.1`, `3B52.1` |
| `CLiteRTLM` | iOS | none | |
| `LiteRtMetalAccelerator` | iOS | File Timestamp | `C617.1`, `3B52.1` |
| `LiteRtMetalAccelerator` | iOS | User Defaults | `CA92.1` |
| `LiteRtMetalAccelerator` | macOS | File Timestamp | `C617.1`, `3B52.1` |
| `LiteRtTopKMetalSampler` | iOS | User Defaults | `CA92.1` |
| `LiteRtTopKMetalSampler` | macOS | none | |

Reason texts are in Apple's
[NSPrivacyAccessedAPITypeReasons](https://developer.apple.com/documentation/bundleresources/app-privacy-configuration/nsprivacyaccessedapitypes/nsprivacyaccessedapitypereasons)
reference.

## Call-site audit

Audited on the `v0.17.0-7` archives (upstream `v0.17.0`,
`e9fd8c53ff968071774206163027dd84bedfe925`), for every slice and architecture.
`LiteRtLm` is built here from upstream source. `LiteRtMetalAccelerator` and
`LiteRtTopKMetalSampler` are upstream prebuilt binaries
(`prebuilt/ios_arm64`, `prebuilt/ios_sim_arm64`, `prebuilt/macos_arm64`) that
this repository only repackages, so their call sites come from disassembly.
`CLiteRTLM` is a re-export shim with no imports.

No binary imports a disk-space or active-keyboard API or a Swift symbol, no
`sysctl` name reads boot time, and no `dlsym` or class-name lookup names a
required-reason API.

### File Timestamp: `stat`, `fstat`, `lstat`

`LiteRtLm`, all slices:

- `litert::lm::GetFileCacheIdentifier(const ScopedFile&)` reads `st_mtime` and
  `st_size` of the model file to name the on-device weight and program caches.
- `litert::ScopedFile::GetSizeImpl` sizes the model file for
  `LitertLmLoader::Initialize` and `MemoryMappedFile::Create`.
- `tflite::MMAPAllocation`, `tflite::FileCopyAllocation` and
  `weight_loader::LiteRtWeightLoader::PrepareAccessForBuffer` size model and
  weight files before mapping them.
- `tflite::xnnpack::IsFileEmpty` and `MMapHandle::Map`, and
  `tflite::delegates::SerializationEntry::GetData`, size the XNNPACK weight
  cache and delegate serialization cache.

`LiteRtMetalAccelerator`, all slices: `ml_drift::MMapHandle::Map` sizes the
ML Drift program and weight cache files (`SerializationProgramCache`,
`SerializationWeightCache`, `CacheBuilder`).

The model path comes from the caller, and the caches sit in the caller's
cache directory or, when none is set, beside the model. An app that keeps
models in its container needs `C617.1`; an app that opens a model the user
picked in place needs `3B52.1`. The runtime cannot tell which, so both are
declared. The metadata stays on the device. `0A2A.1` does not apply: no
framework wraps a timestamp API for the app.

`LiteRtLm` also links Rust `std::fs` whole, because the dylib exports every
symbol. Its stat-family calls have these callers:

- The `tokenizers` crate (`BPE::read_file`, `WordLevel::read_file`), where
  `File::read_to_end` sizes a vocabulary file named by a tokenizer
  configuration. LiteRT-LM hands tokenizers their JSON as a string
  (`tokenizers_new_from_str`), and a file named there would be a model asset
  like the ones above.
- The panic backtrace symbolizer, which maps loaded binary images.
- `chrono`'s local time zone, which calls `lstat` on `/etc/localtime` and
  reads zoneinfo files. No LiteRT-LM code calls into it directly; its template
  code uses `chrono::Utc`. If it were reached, no approved reason would
  describe it: `/etc/localtime` is a system file, neither in the app container
  nor user-granted.
- `libtest`'s terminfo lookup, which has no caller outside `libtest`.

`flatbuffers::LoadFileRaw` and `DirExists`, and miniaudio's
`ma_default_vfs_info`, have no direct caller.

In `LiteRtMetalAccelerator`, the linked `tflite::MMAPAllocation`,
`FileCopyAllocation` and `SerializationEntry::GetData` copies have no direct
caller.

### System Boot Time: `mach_absolute_time`

`LiteRtLm`, iOS slices only. The four call sites are miniaudio's `ma_timer`
(`ma_timer_init`, `ma_device_read__null`, `ma_device_write__null`,
`ma_device_thread__null`), which subtracts two readings to pace the null audio
device. That is `35F9.1`, elapsed time between events inside the app. LiteRT-LM
only decodes audio with `ma_decoder` and never opens a device, so the code is
unreached. The macOS slice does not import `mach_absolute_time`.

### User Defaults: `NSUserDefaults`

`LiteRtMetalAccelerator` and `LiteRtTopKMetalSampler`, iOS slices only. Both
link Google Toolbox for Mac's `GTMLogger`. `-[GTMLogLevelFilter
startObservingUserDefaultsIfNeeded]` observes, and `IsVerboseLoggingEnabled`
reads with `boolForKey:`, the `GTMVerboseLogging` key of
`[NSUserDefaults standardUserDefaults]`. That key is a logging switch in the
host app's own defaults domain, neither a system nor a managed-configuration
key, so `CA92.1` applies; Google Toolbox for Mac declares the same reason for
this code in its own manifest. Only `+[GTMLogger standardLogger]` creates the
filter, and nothing in either binary sends `sharedLogger` or a `standardLogger`
message, so the read happens only if other code in the process uses that
class.

## Artifacts without a manifest

A privacy manifest lives in a bundle. These artifacts have none to put it in:

- The macOS-only library XCFrameworks, each a bare dylib: `CLiteRTLMMac`,
  `GemmaModelConstraintProvider`, `LiteRt`, `LiteRtTopKWebGpuSampler`,
  `LiteRtWebGpuAccelerator` and `WebgpuDawn`. Apple does not require
  required-reason declarations on macOS. `GemmaModelConstraintProvider`,
  `LiteRt` and `LiteRtWebGpuAccelerator` import `fstat` (`LiteRt` also `stat`);
  the others import no required-reason API.
- The `litert-lm-native-runtime-*` tarballs. Their flat dylibs cannot carry a
  manifest, and their iOS `.framework` directories are packaging inputs that
  stay unchanged, so the `manifest.json` artifact inventory that consumers
  validate does not change. An app that embeds those instead of the
  XCFrameworks declares the categories above in its own
  `PrivacyInfo.xcprivacy`.

## Validation

`tools/package_apple_xcframeworks.py` fails unless every zip it produced
passes the same check as:

```bash
python3 tools/apple_privacy_manifest.py --audit-imports dist/spm/<tag>/*.zip
```

The release workflow runs the packager before it generates `manifest.json`
and `SHA256SUMS`, so an archive that fails is never checksummed or uploaded.
Pull-request qualification runs the same packager. The check fails when:

- a framework slice lacks the manifest or carries it in the wrong place, or a
  bare library slice targets anything but macOS;
- the manifest is not a valid property list, reports tracking or collected
  data, or names an unknown category or unapproved reason;
- the manifest differs from the audited declaration for that framework and
  platform, or the framework has none;
- the declared categories differ from the required-reason symbols and
  Objective-C selectors that any Mach-O file in the framework, nested dylibs
  included, references in any architecture (`nm -u -arch all`,
  `otool -arch all`);
- a binary imports Swift symbols, which the audit does not model.

The audit cannot see an API resolved through `dlsym` or a class looked up by
name and messaged through a selector other than `standardUserDefaults` or
`initWithSuiteName:`.

When an upstream bump makes the check fail, find the new call sites, choose
the reason that describes them, and update `DECLARATIONS` and this page
together. Do not add a category only to make the check pass.
