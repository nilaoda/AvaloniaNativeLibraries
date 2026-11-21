# AvaloniaNativeLibraries

Version-pinned native static libraries for Avalonia NativeAOT applications.

| Workflow | Target | Components |
| --- | --- | --- |
| Build Windows x64 | Windows x64 | SkiaSharp 2.88.9, HarfBuzzSharp 8.3.1.1, ANGLE chromium/7151 |
| Build Linux x64 | Ubuntu 24.04, x64 | SkiaSharp 2.88.9, HarfBuzzSharp 8.3.1.1 |
| Build macOS arm64 | macOS 14+, arm64 | SkiaSharp 2.88.9, HarfBuzzSharp 8.3.1.1, Avalonia.Native 11.3.12 |

Run each workflow independently from Actions. Select `all` or a single component
to build. Workflows upload their own ZIP artifacts and do not publish releases.

Source revisions are defined in `config/versions.json`. HarfBuzzSharp 8.3.1.1
uses HarfBuzz 8.3.1; its native implementation is built from the same upstream
commit recorded in SkiaSharp 3.119.0's dependency manifest.

Each ZIP contains static archives in `lib/`, source/license information, a
`manifest.json` with source revisions, library SHA-256 checksums and required
system link dependencies. System frameworks and graphics drivers remain
provided by the target OS; Linux's fontconfig dependency is also recorded.

The build links and runs a small native executable against the selected
libraries, checks versions and initialization, and checks its dynamic imports.
This does not replace application-level NativeAOT, GUI or GPU playback testing.
Application integration and GUI verification remain separate steps.

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
