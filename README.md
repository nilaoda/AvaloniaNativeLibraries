# AvaloniaNativeLibraries

Version-pinned native static libraries for Avalonia desktop applications on
Windows, Linux and macOS.

Builds and packages SkiaSharp, HarfBuzzSharp, ANGLE and Avalonia.Native for
desktop NativeAOT applications. Each release records the exact dependency
versions, source revisions and supported targets.

## Compatibility

| Avalonia | SkiaSharp | HarfBuzzSharp | ANGLE | Status |
| --- | --- | --- | --- | --- |
| 11.3.12 | 2.88.9 | 8.3.1.1 | chromium/7151 (Windows) | Native builds and application NativeAOT checks passed on all three targets |
| 12 | To be selected | To be selected | To be selected | Planned |

The current SDK profile uses Avalonia.Native 11.3.12 on macOS. Match the
application's managed binding versions to the combination listed in its SDK
release. Additional Avalonia versions will be listed after their dependency
builds and application integration have been verified.

Source revisions are pinned in `config/versions.json`. HarfBuzzSharp 8.3.1.1
uses HarfBuzz 8.3.1.

## Platforms

| Workflow | Target | Components |
| --- | --- | --- |
| Build Windows x64 | Windows x64 | SkiaSharp, HarfBuzzSharp, ANGLE |
| Build Linux x64 | x64, built on Ubuntu 24.04 | SkiaSharp, HarfBuzzSharp |
| Build macOS arm64 | macOS 14+, arm64 | SkiaSharp, HarfBuzzSharp, Avalonia.Native |

Run each workflow independently from Actions. Select `all` or a single component
to build. Workflows upload their own ZIP artifacts and do not publish releases.

## Releases

Release tags identify the Avalonia version and build date, for example
`avalonia-11.3.12-20261122`.

Each platform ZIP includes static libraries, licenses and a `manifest.json`
with exact versions, source revisions, library checksums and system link
requirements. ZIP checksums are provided in `SHA256SUMS`.

Native build checks and application-level NativeAOT, GUI and GPU validation
are performed separately.

## Building

To inspect the build plan without downloading or compiling:

```sh
python scripts/build.py --rid linux-x64 --plan
```

To build locally, install Python 3.12, Ninja 1.13.0 and the platform toolchain,
then run on the target OS:

```sh
python scripts/build.py --rid linux-x64 --component all
```

Windows builds require an MSVC developer shell and LLVM 21.1.8. macOS builds
require Xcode and Rosetta for the Intel GN binary pinned by Skia m88. Generated
sources and build outputs live under `.build/` and `artifacts/` and are ignored
by Git. Before rebuilding the same target/component, move aside its previous
`artifacts/<rid>-<component>/` directory.

Build recipes draw on the public [SkiaSharp.Static](https://github.com/2ndlab/SkiaSharp.Static)
and [ANGLE.Static](https://github.com/2ndlab/ANGLE.Static) projects, upstream
[SkiaSharp](https://github.com/mono/SkiaSharp), [HarfBuzz](https://github.com/harfbuzz/harfbuzz),
[ANGLE](https://github.com/google/angle) and [Avalonia](https://github.com/AvaloniaUI/Avalonia).
