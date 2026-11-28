# AvaloniaNativeLibraries

Version-pinned native static libraries for Avalonia desktop applications on
Windows, Linux and macOS.

Builds and packages SkiaSharp, HarfBuzzSharp, ANGLE and Avalonia.Native for
desktop NativeAOT applications. Each release records the exact dependency
versions, source revisions and supported targets.

## Compatibility

| Avalonia | SkiaSharp | HarfBuzzSharp | ANGLE | Status |
| --- | --- | --- | --- | --- |
| 11.3.23 | 2.88.9 | 8.3.1.1 | chromium/7151 (Windows) | Native builds and application NativeAOT checks passed on all six targets |
| 12 | To be selected | To be selected | To be selected | Planned |

The current SDK profile uses Avalonia.Native 11.3.23 on macOS. Match the
application's managed binding versions to the combination listed in its SDK
release. Additional Avalonia versions will be listed after their dependency
builds and application integration have been verified.

Source revisions are pinned in `config/versions.json`. HarfBuzzSharp 8.3.1.1
uses HarfBuzz 8.3.1.

## Platforms

| Workflow | Target | Components |
| --- | --- | --- |
| Build Windows | Windows x64 and ARM64 | SkiaSharp, HarfBuzzSharp, ANGLE |
| Build Linux | x64 and ARM64, built on Ubuntu 24.04 | SkiaSharp, HarfBuzzSharp |
| Build Linux musl | x64 and ARM64, built on Alpine 3.22.2 (musl 1.2.5) | SkiaSharp, HarfBuzzSharp; GPU enabled, ICU disabled |
| Build macOS | macOS 14+, arm64 and x64 | SkiaSharp, HarfBuzzSharp, Avalonia.Native |

Run each workflow independently from Actions. Select an architecture and `all` or a single component
to build. Workflows upload their own ZIP artifacts and do not publish releases.

## Releases

Release tags identify the Avalonia version and build date, for example
`avalonia-11.3.23-20261122`.

Each platform ZIP includes static libraries, licenses and a `manifest.json`
with exact versions, source revisions, library checksums and system link
requirements. macOS ZIPs also include `build/StaticSkia.targets`; import it
when statically linking Avalonia 11.3.23 to preserve the Metal rendering path.
ZIP checksums are provided in `SHA256SUMS`.

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

Linux musl builds use the pinned Alpine 3.22.2 image and Docker on a matching
architecture. For ARM64, use `linux/arm64` and `linux-musl-arm64`:

```sh
docker build --platform linux/amd64 -f tools/Dockerfile.musl -t avalonia-native-musl .
docker run --rm --platform linux/amd64 -v "$PWD:/src" -w /src avalonia-native-musl \
  python3 scripts/build.py --rid linux-musl-x64 --component all
```

The ZIP follows the other SDKs' `lib/`, `licenses/` and `manifest.json` layout.
Use `link.skia.libs` from the manifest when linking statically with a musl
compiler (for example, `clang++ -static-pie`). GPU APIs are enabled, but GPU
drivers and EGL runtimes are not bundled; physical GPU acceleration is not
validated. ICU is disabled. Fontconfig configuration and font files are runtime
inputs and are not included in the ZIP.

For other targets, build on the matching OS and CPU architecture.
Windows builds require an MSVC developer shell and LLVM 21.1.8 for x64 or
22.1.8 for ARM64. macOS builds require Xcode; ARM64 hosts also need Rosetta
for the pinned Intel GN.
Linux ARM64 builds compile the pinned GN source with the host toolchain. Generated
sources and build outputs live under `.build/` and `artifacts/` and are ignored
by Git. Before rebuilding the same target/component, move aside its previous
`artifacts/<rid>-<component>/` directory.

Build recipes draw on the public [SkiaSharp.Static](https://github.com/2ndlab/SkiaSharp.Static)
and [ANGLE.Static](https://github.com/2ndlab/ANGLE.Static) projects, upstream
[SkiaSharp](https://github.com/mono/SkiaSharp), [HarfBuzz](https://github.com/harfbuzz/harfbuzz),
[ANGLE](https://github.com/google/angle) and [Avalonia](https://github.com/AvaloniaUI/Avalonia).
