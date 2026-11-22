#!/usr/bin/env python3
"""Build and verify version-pinned native static libraries on their target OS."""
import argparse
import hashlib
import json
import os
import platform
import struct
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = {
    "win-x64": ("skia", "harfbuzz", "angle"),
    "win-arm64": ("skia", "harfbuzz", "angle"),
    "linux-x64": ("skia", "harfbuzz"),
    "linux-arm64": ("skia", "harfbuzz"),
    "osx-arm64": ("skia", "harfbuzz", "avalonia"),
    "osx-x64": ("skia", "harfbuzz", "avalonia"),
}


def run(*arguments, cwd=None, capture=False, env=None):
    arguments = [str(arg) for arg in arguments]
    print("+", subprocess.list2cmdline(arguments), flush=True)
    # Resolve depot_tools' Windows batch entry points explicitly.
    if os.name == "nt" and Path(arguments[0]).suffix == "":
        arguments[0] = shutil.which(arguments[0]) or arguments[0]
    return subprocess.run(arguments, cwd=cwd, check=True, text=True, env=env,
                          stdout=subprocess.PIPE if capture else None).stdout


def checkout(source, directory):
    if not re.fullmatch(r"[0-9a-f]{40}", source["revision"]):
        raise ValueError("Source revisions must be immutable commit hashes")
    directory.mkdir(parents=True, exist_ok=True)
    if not (directory / ".git").exists():
        run("git", "init", directory)
        run("git", "remote", "add", "origin", source["repository"], cwd=directory)
    current = subprocess.run(["git", "rev-parse", "HEAD"], cwd=directory,
                             capture_output=True, text=True)
    if current.returncode or current.stdout.strip() != source["revision"]:
        run("git", "fetch", "--depth", "1", "origin", source["revision"], cwd=directory)
        run("git", "checkout", "--detach", "FETCH_HEAD", cwd=directory)
    return directory


def skia_arguments(rid, versions):
    values = {
        "target_os": {"win": "win", "linux": "linux", "osx": "mac"}[rid.split("-")[0]],
        "target_cpu": rid.split("-")[1],
        "is_official_build": True,
        "is_static_skiasharp": True,
        "skia_enable_tools": False,
        "skia_enable_gpu": True,
        "skia_enable_pdf": False,
        "skia_enable_skottie": False,
        "skia_use_angle": False,
        "skia_use_dng_sdk": False,
        "skia_use_icu": False,
        "skia_use_piex": False,
        "skia_use_sfntly": False,
        "skia_use_vulkan": False,
        "skia_use_system_expat": False,
        "skia_use_system_libjpeg_turbo": False,
        "skia_use_system_libpng": False,
        "skia_use_system_libwebp": False,
        "skia_use_system_zlib": False,
    }
    if rid.startswith("win-"):
        values.update(clang_win=Path(os.environ.get("LLVM_ROOT", "C:/Program Files/LLVM")).as_posix(),
                      clang_win_version=versions["llvm_arm64" if rid.endswith("-arm64") else "llvm"]["version"].split(".")[0],
                      extra_cflags=["/MT", "/EHsc"],
                      skia_enable_fontmgr_win_gdi=False, skia_use_xps=False)
    else:
        values.update(cc="clang", cxx="clang++", skia_use_system_freetype2=False)
        if rid.startswith("osx-"):
            values.update(skia_use_metal=True, min_macos_version=versions["macos_deployment_target"],
                          extra_cflags=[f'-mmacosx-version-min={versions["macos_deployment_target"]}'])
    return values


def write_gn(path, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(f"{key} = {json.dumps(value)}" for key, value in values.items()) + "\n",
                    encoding="utf-8")


def copy_library(source, destination):
    if not source.is_file():
        raise FileNotFoundError(source)
    with source.open("rb") as handle:
        if handle.read(8) != b"!<arch>\n":
            raise ValueError(f"Expected a self-contained static archive: {source}")
    shutil.copy2(source, destination / source.name)


def verify_archive_architecture(path, rid):
    data = path.read_bytes()
    if data[:8] != b"!<arch>\n":
        raise ValueError(f"Invalid static archive: {path}")
    architectures = set()
    position = 8
    while position < len(data):
        header = data[position:position + 60]
        if len(header) != 60 or header[58:60] != b"`\n":
            raise ValueError(f"Invalid archive member header: {path}")
        name = header[:16].decode("ascii").strip()
        size = int(header[48:58])
        member = data[position + 60:position + 60 + size]
        position += 60 + size + size % 2
        if name in {"/", "//", "/SYM64/"}:
            continue
        if name.startswith("#1/"):
            length = int(name[3:])
            name = member[:length].rstrip(b"\0").decode("utf-8")
            member = member[length:]
        if name.startswith("__.SYMDEF"):
            continue
        if member.startswith(b"\x7fELF"):
            machine = struct.unpack_from("<H", member, 18)[0]
            architecture = {62: "x64", 183: "arm64"}.get(machine)
        elif member[:4] == b"\xcf\xfa\xed\xfe":
            machine = struct.unpack_from("<I", member, 4)[0]
            architecture = {0x1000007: "x64", 0x100000c: "arm64"}.get(machine)
        else:
            offset = 6 if member[:4] == b"\0\0\xff\xff" else 0
            machine = struct.unpack_from("<H", member, offset)[0]
            architecture = {0x8664: "x64", 0xaa64: "arm64"}.get(machine)
        if architecture is None:
            raise ValueError(f"Unknown object architecture: {path}/{name}")
        architectures.add(architecture)
    if architectures != {rid.split("-")[1]}:
        raise ValueError(f"Static library architecture mismatch: {path}: {architectures}, expected {rid}")


def expose_metal_entry_points(path):
    # Avalonia 的 Metal 后端通过 dlsym 查找这两个入口，静态归档中也需保留公开可见性。
    data = bytearray(path.read_bytes())
    expected = {b"_gr_direct_context_make_metal_with_options", b"_gr_backendrendertarget_new_metal"}
    found = set()
    changed = False
    position = 8
    if data[:8] != b"!<arch>\n":
        raise ValueError(f"Invalid static archive: {path}")
    while position + 60 <= len(data):
        header = data[position:position + 60]
        size = int(header[48:58])
        name = bytes(header[:16]).decode("ascii").strip()
        start = position + 60
        position += 60 + size + size % 2
        if name.startswith("#1/"):
            start += int(name[3:])
        if data[start:start + 4] != b"\xcf\xfa\xed\xfe":
            continue
        offset = start + 32
        for _ in range(struct.unpack_from("<I", data, start + 16)[0]):
            command, length = struct.unpack_from("<II", data, offset)
            if command == 2:
                symoff, count, stroff, strsize = struct.unpack_from("<IIII", data, offset + 8)
                for number in range(count):
                    entry = start + symoff + number * 16
                    index, kind = struct.unpack_from("<IB", data, entry)
                    label_start = start + stroff + index
                    label_end = data.find(b"\0", label_start, start + stroff + strsize)
                    label = bytes(data[label_start:label_end])
                    if label in expected and kind & 0x0e == 0x0e:
                        found.add(label)
                        if kind & 0x10:
                            data[entry + 4] = kind & ~0x10
                            changed = True
            offset += length
    if found != expected:
        raise ValueError(f"Missing static Metal entry points in {path}: {expected - found}")
    if changed:
        path.write_bytes(data)
    return changed


def macos_cpp_toolchain():
    compiler = run("xcrun", "--sdk", "macosx", "--find", "clang++", capture=True).strip()
    sdk = run("xcrun", "--sdk", "macosx", "--show-sdk-path", capture=True).strip()
    return compiler, sdk


def gn_link_metadata(gn, build_dir, label, source):
    result = {}
    for kind in ("libs", "frameworks"):
        raw = run(gn, "desc", build_dir, label, kind,
                  "--all", "--format=json", cwd=source, capture=True)
        # GN writes build-argument warnings to stdout before its JSON document.
        start = re.search(r"(?m)^[ \t]*\{", raw)
        if start is None:
            raise ValueError(f"GN did not provide JSON {kind} metadata: {raw[:500]}")
        if raw[:start.start()].strip():
            print(raw[:start.start()], end="", flush=True)
        data = json.loads(raw[start.start():])
        if isinstance(data, dict):
            values = [item[kind] for item in data.values() if isinstance(item, dict) and kind in item]
            data = [value for group in values for value in group]
        if not isinstance(data, list) or any(not isinstance(value, str) for value in data):
            raise ValueError(f"Unexpected GN {kind} metadata")
        result[kind] = data
    return result


def patch_macos_skia(source, deployment_target):
    patches = (
        (source / "third_party/externals/zlib/zutil.h",
         b"#if defined(MACOS) || defined(TARGET_OS_MAC)",
         b"#if (defined(MACOS) || defined(TARGET_OS_MAC)) && !defined(__APPLE__)"),
        (source / "third_party/externals/libpng/pngpriv.h",
         b"defined(THINK_C) || defined(__SC__) || defined(TARGET_OS_MAC)",
         b"defined(THINK_C) || defined(__SC__) || (defined(TARGET_OS_MAC) && !defined(__APPLE__))"),
        (source / "gn/BUILD.gn", b'"arm64-apple-macos11"',
         f'"arm64-apple-macos{deployment_target}"'.encode("ascii")),
    )
    for path, old, new in patches:
        data = path.read_bytes()
        if old in data:
            path.write_bytes(data.replace(old, new))
        elif new not in data:
            raise ValueError(f"The macOS compatibility patch does not match {path}")


def patch_skia_headers(source):
    path = source / "src/utils/SkParseColor.cpp"
    data = path.read_bytes()
    if b"#include <iterator>" not in data:
        marker = b'#include "include/utils/SkParse.h"'
        if data.count(marker) != 1:
            raise ValueError("The SkParseColor include patch does not match this revision")
        newline = b"\r\n" if b"\r\n" in data else b"\n"
        data = data.replace(marker, marker + newline + b"#include <algorithm>" + newline + b"#include <iterator>")
        path.write_bytes(data)


def build_skia(rid, versions, work, output, jobs):
    source = checkout(versions["skia"], work / "skia")
    run(sys.executable, "tools/git-sync-deps", cwd=source)
    patch_skia_headers(source)
    if rid.startswith("osx-"):
        patch_macos_skia(source, versions["macos_deployment_target"])
    if rid == "linux-arm64":
        # 旧版下载脚本只有 x64 GN；在 ARM64 上从固定源码构建宿主工具。
        gn_source = checkout(versions["gn"], work / "gn")
        # GN 用初始标签和提交历史生成版本头文件。
        if run("git", "rev-parse", "--is-shallow-repository", cwd=gn_source, capture=True).strip() == "true":
            run("git", "fetch", "--unshallow", "origin", versions["gn"]["revision"], cwd=gn_source)
        run("git", "fetch", "origin", "tag", "initial-commit", cwd=gn_source)
        gn_output = gn_source / "out"
        environment = dict(os.environ, CXX="clang++", CXXFLAGS="-include cstdint -include limits")
        run(sys.executable, "build/gen.py", cwd=gn_source, env=environment)
        run("ninja", "-C", gn_output, "-j", jobs, cwd=gn_source)
        gn = gn_output / "gn"
    else:
        run(sys.executable, "bin/fetch-gn", cwd=source)
        gn = source / "bin" / ("gn.exe" if rid.startswith("win-") else "gn")
    build_dir = source / "out" / rid
    write_gn(build_dir / "args.gn", skia_arguments(rid, versions))
    run(gn, "gen", build_dir, f"--script-executable={sys.executable}", cwd=source)
    run("ninja", "-C", build_dir, "-j", jobs, "skia", "SkiaSharp", cwd=source)
    filenames = ("skia.lib", "SkiaSharp.lib") if rid.startswith("win-") else ("libskia.a", "libSkiaSharp.a")
    for filename in filenames:
        copy_library(build_dir / filename, output)
    if rid.startswith("osx-"):
        expose_metal_entry_points(output / "libskia.a")
    return gn_link_metadata(gn, build_dir, "//:SkiaSharp", source)


def build_harfbuzz(rid, versions, work, output, jobs):
    source = checkout(versions["harfbuzz"], work / "harfbuzz")
    include = [source / "src", ROOT / "native/harfbuzz"]
    defines = ["HAVE_CONFIG_OVERRIDE_H", "HAVE_OT", "HB_NO_FALLBACK_SHAPE"]
    unit = source / "src/harfbuzz-subset.cc"
    if rid.startswith("win-"):
        obj = work / "harfbuzz.obj"
        run("cl", "/nologo", "/c", "/O2", "/MT", "/EHsc", "/std:c++17", "/bigobj", "/Gy", "/Gw",
            *(f"/I{path}" for path in include), *(f"/D{value}" for value in defines),
            f"/Fo{obj}", unit)
        run("lib", "/nologo", f'/OUT:{output / "libHarfBuzzSharp.lib"}', obj)
    else:
        obj = work / "harfbuzz.o"
        compiler, flags = "clang++", []
        if rid.startswith("osx-"):
            compiler, sdk = macos_cpp_toolchain()
            flags = ["-isysroot", sdk, "-mmacosx-version-min=" + versions["macos_deployment_target"], "-arch", "arm64" if rid.endswith("-arm64") else "x86_64"]
        run(compiler, "-c", "-O2", "-std=c++17", "-fPIC", "-fvisibility=hidden",
            "-fno-exceptions", "-fno-rtti", *flags,
            *(f"-I{path}" for path in include), *(f"-D{value}" for value in defines), unit, "-o", obj)
        run("ar", "rcs", output / "libHarfBuzzSharp.a", obj)
    return {"libs": [], "frameworks": []}


def patch_angle(source):
    build_file = source / "BUILD.gn"
    text = build_file.read_text(encoding="utf-8")
    marker = 'angle_static_library("libGLESv2_static") {\n'
    if 'angle_static_library("libANGLE_static")' not in text:
        if text.count(marker) != 1:
            raise ValueError("The ANGLE aggregate-library patch does not match this revision")
        text = text.replace(marker, 'angle_static_library("libANGLE_static") {\n'
                            '  complete_static_lib = true\n  public_deps = [ ":libANGLE" ]\n}\n\n'
                            + marker + '  complete_static_lib = true\n')
        build_file.write_text(text, encoding="utf-8")
    deps_file = source / "DEPS"
    deps = deps_file.read_text(encoding="utf-8")
    # These disabled backends and development tools are not used by the Windows build.
    for name in ("catapult", "dawn", "llvm/src", "SwiftShader", "VK-GL-CTS/src"):
        pattern = r"(?ms)^  'third_party/" + re.escape(name) + r"': \{.*?^  \},\n"
        deps = re.sub(pattern, "", deps)
    deps_file.write_text(deps, encoding="utf-8")


def patch_angle_arm64_toolset(source, visual_studio):
    redist = Path(visual_studio) / "VC/Redist/MSVC"
    candidates = sorted(redist.glob("*/arm64/Microsoft.VC*.CRT"),
                        key=lambda path: tuple(int(part) for part in path.parents[1].name.split(".")),
                        reverse=True)
    runtime = next((path for path in candidates if (path / "msvcp140.dll").is_file()), None)
    if runtime is None:
        raise ValueError(f"No ARM64 Visual C++ runtime found under {redist}")
    toolset = runtime.name.split(".")[1]
    script = source / "build/vs_toolchain.py"
    original = script.read_bytes()
    # 保留 Chromium 的构建逻辑，仅根据实际安装目录修正新版 VS 的运行库族名。
    updated, count = re.subn(rb"('2022': ')VC\d+(',)",
                             lambda match: match[1] + toolset.encode("ascii") + match[2], original)
    if count != 1:
        raise ValueError("The Chromium ARM64 runtime-toolset patch does not match this revision")
    if updated != original:
        script.write_bytes(updated)
    print(f"ANGLE ARM64 runtime toolset: {toolset}", flush=True)


def build_angle(rid, versions, work, output, jobs):
    depot = checkout(versions["depot_tools"], work / "depot_tools")
    source = checkout(versions["angle"], work / "angle")
    patch_angle(source)
    original_path = os.environ["PATH"]
    os.environ["PATH"] = str(depot) + os.pathsep + original_path
    os.environ.update(DEPOT_TOOLS_WIN_TOOLCHAIN="0", DEPOT_TOOLS_UPDATE="0")
    try:
        run(sys.executable, "scripts/bootstrap.py", cwd=source)
        run("gclient", "sync", "-f", "-D", "-R", cwd=source)
    finally:
        os.environ["PATH"] = original_path
    if rid == "win-arm64" and os.environ.get("VSINSTALLDIR"):
        # 固定版本的 Chromium 构建脚本通过显式路径使用 runner 上的新版 VS。
        os.environ["GYP_MSVS_OVERRIDE_PATH"] = os.environ["VSINSTALLDIR"]
        os.environ["GYP_MSVS_VERSION"] = "2022"
        os.environ["vs2022_install"] = os.environ["VSINSTALLDIR"]
        patch_angle_arm64_toolset(source, os.environ["VSINSTALLDIR"])
    build_dir = source / "out" / rid
    args = dict(is_official_build=False, is_component_build=False, is_clang=False, is_debug=False,
                angle_is_msvc=True, symbol_level=0, use_custom_libcxx=False, use_lld=False,
                use_thin_lto=False, chrome_pgo_phase=False, angle_build_tests=False,
                build_angle_deqp_tests=False, angle_enable_swiftshader=False,
                angle_enable_wgpu=False, angle_enable_vulkan=False, target_cpu=rid.split("-")[1])
    write_gn(build_dir / "args.gn", args)
    gn = source / "buildtools/win/gn.exe"
    run(gn, "gen", build_dir, f"--script-executable={sys.executable}", cwd=source)
    run("ninja", "-C", build_dir, "-j", jobs, "libANGLE_static", "libGLESv2_static", cwd=source)
    for filename in ("libANGLE_static.lib", "libGLESv2_static.lib"):
        copy_library(build_dir / "obj" / filename, output)
    return {"libs": ["synchronization.lib", "gdi32.lib", "dxgi.lib", "d3d9.lib", "dxguid.lib",
                      "user32.lib", "advapi32.lib"], "frameworks": []}


def build_avalonia(rid, versions, work, output, jobs):
    source = checkout(versions["avalonia"], work / "avalonia")
    run("git", "submodule", "update", "--init", "--depth", "1", cwd=source)
    run("dotnet", "run", "--project", ROOT / "native/headers/headers.csproj",
        "--configuration", "Release", "--", source / "src/Avalonia.Native/avn.idl",
        source / "native/Avalonia.Native/inc/avalonia-native.h", cwd=ROOT)
    project = source / "native/Avalonia.Native/src/OSX/Avalonia.Native.OSX.xcodeproj"
    build_dir = work / "avalonia-native-out"
    run("xcodebuild", "-project", project, "-target", "Avalonia.Native.OSX", "-configuration", "Release",
        "-jobs", jobs, "ARCHS=" + ("arm64" if rid.endswith("-arm64") else "x86_64"), "ONLY_ACTIVE_ARCH=YES", "MACH_O_TYPE=staticlib",
        "EXECUTABLE_EXTENSION=a", "EXECUTABLE_NAME=libAvaloniaNative.a",
        "CODE_SIGNING_ALLOWED=NO",
        "GCC_GENERATE_DEBUGGING_SYMBOLS=NO", "CLANG_ENABLE_MODULE_DEBUGGING=NO",
        "MACOSX_DEPLOYMENT_TARGET=" + versions["macos_deployment_target"],
        "CONFIGURATION_BUILD_DIR=" + str(build_dir))
    copy_library(build_dir / "libAvaloniaNative.a", output)
    return {"libs": ["objc", "c++"], "frameworks": ["AppKit", "Foundation", "Carbon", "QuartzCore",
            "IOSurface", "OpenGL", "Metal", "CoreGraphics", "UniformTypeIdentifiers"]}


def verify(rid, components, output, metadata, versions, work):
    defines = ["VERIFY_" + component.upper() for component in components]
    libraries = sorted(output.glob("*.lib" if rid.startswith("win-") else "*.a"))
    for library in libraries:
        verify_archive_architecture(library, rid)
    libs = list(dict.fromkeys(lib for item in metadata.values() for lib in item["libs"]))
    frameworks = list(dict.fromkeys(f for item in metadata.values() for f in item["frameworks"]))
    executable = work / ("native-smoke.exe" if rid.startswith("win-") else "native-smoke")
    if rid.startswith("win-"):
        run("cl", "/nologo", "/O2", "/MT", "/EHsc", *("/D" + value for value in defines),
            ROOT / "native/smoke.cpp", f"/Fo{work / 'native-smoke.obj'}", f"/Fe{executable}",
            "/link", *libraries, *libs, "ole32.lib", "oleaut32.lib", "user32.lib", "gdi32.lib",
            "advapi32.lib", "shell32.lib", "ws2_32.lib", "bcrypt.lib", "opengl32.lib")
        dependencies = run("dumpbin", "/dependents", executable, capture=True)
    else:
        link = []
        for lib in libs:
            link.append(lib if lib.startswith(("-", "/")) else "-l" + lib)
        for framework in frameworks:
            link.extend(("-framework", framework.removesuffix(".framework")))
        if rid.startswith("linux-"):
            link = ["-Wl,--start-group", *libraries, "-Wl,--end-group", *link,
                    "-static-libstdc++", "-static-libgcc", "-ldl", "-lpthread"]
            compiler = "g++"
        else:
            compiler, sdk = macos_cpp_toolchain()
            link = [*libraries, *link, "-Wl,-ObjC", "-lc++", "-arch", "arm64" if rid.endswith("-arm64") else "x86_64",
                    "-isysroot", sdk, "-mmacosx-version-min=" + versions["macos_deployment_target"]]
        run(compiler, "-O2", "-std=c++17", *("-D" + value for value in defines), ROOT / "native/smoke.cpp",
            "-o", executable, *link)
        dependencies = run("readelf", "-d", executable, capture=True) if rid.startswith("linux-") else run("otool", "-L", executable, capture=True)
    for name in ("libSkiaSharp.so", "libSkiaSharp.dylib", "libSkiaSharp.dll", "libHarfBuzzSharp.so",
                 "libHarfBuzzSharp.dylib", "libHarfBuzzSharp.dll", "libAvaloniaNative.dylib", "av_libglesv2.dll"):
        if name.lower() in dependencies.lower():
            raise RuntimeError(f"Smoke executable unexpectedly depends on {name}")
    result = run(executable, cwd=work, capture=True)
    if "Native static libraries verified." not in result:
        raise RuntimeError("Native smoke test did not report success")
    print(result, flush=True)


def file_hash(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def install_macos_support(stage):
    expose_metal_entry_points(stage / "lib/libskia.a")
    support = stage / "build"
    support.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for name in ("StaticSkia.targets", "StaticSkiaLoader.c"):
        shutil.copy2(ROOT / "native/macos" / name, support / name)
        hashes["build/" + name] = file_hash(support / name)
    return hashes


def package(rid, components, versions, output, metadata, archive, work):
    support_hashes = install_macos_support(output.parent) if rid.startswith("osx-") and "skia" in components else {}
    for library in output.iterdir():
        with library.open("rb") as handle:
            copy_check = handle.read(8)
        if copy_check != b"!<arch>\n":
            raise ValueError(f"Invalid archive: {library}")
    licenses = output.parent / "licenses"
    if "harfbuzz" in components:
        config_license = licenses / "harfbuzz-config" / "LICENSE.skia"
        config_license.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "native/harfbuzz/LICENSE.skia", config_license)
    for component in components:
        source = work / component
        for directory, directories, filenames in os.walk(source):
            directories[:] = [name for name in directories if name not in {".git", "out"}]
            for filename in filenames:
                if not filename.upper().startswith(("LICENSE", "COPYING", "COPYRIGHT", "NOTICE")):
                    continue
                path = Path(directory) / filename
                if not path.is_file():
                    continue
                destination = licenses / component / path.relative_to(source)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
    manifest = {"rid": rid, "components": {name: versions[name] for name in components},
                "link": metadata, "macos_deployment_target": versions["macos_deployment_target"] if rid.startswith("osx-") else None}
    files = {path.name: file_hash(path) for path in output.iterdir()}
    manifest["sha256"] = files
    if support_hashes:
        manifest["support_sha256"] = support_hashes
    manifest["build"] = {"script_sha256": file_hash(Path(__file__)), "python": sys.version,
                         "msvc": os.environ.get("VCToolsVersion"),
                         "windows_sdk": os.environ.get("WindowsSDKVersion")}
    (output.parent / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(output.parent.rglob("*")):
            if path.is_file():
                bundle.write(path, path.relative_to(output.parent))
    print("Packaged:", archive)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rid", choices=COMPONENTS, required=True)
    parser.add_argument("--component", choices=("all", "skia", "harfbuzz", "angle", "avalonia"), default="all")
    parser.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1))
    parser.add_argument("--plan", action="store_true", help="Print the selected sources without downloading or compiling")
    args = parser.parse_args()
    if args.component != "all" and args.component not in COMPONENTS[args.rid]:
        parser.error("The selected component is not used on this platform")
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    versions = json.loads((ROOT / "config/versions.json").read_text(encoding="utf-8"))
    components = COMPONENTS[args.rid] if args.component == "all" else (args.component,)
    if args.plan:
        print(json.dumps({"rid": args.rid, "sources": {name: versions[name] for name in components}}, indent=2))
        return
    system = {"win32": "win", "linux": "linux", "darwin": "osx"}.get(sys.platform)
    machine = (os.environ.get("PROCESSOR_ARCHITEW6432") or platform.machine()).lower()
    architecture = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(machine)
    host = f"{system}-{architecture}"
    if args.rid != host:
        parser.error("Build on the target OS; cross-compilation is not configured")
    work = ROOT / ".build" / args.rid
    stage = ROOT / "artifacts" / f"{args.rid}-{args.component}"
    output = stage / "lib"
    if stage.exists() and any(path.is_file() for path in stage.rglob("*")):
        parser.error(f"Output already exists; move it aside before a fresh build: {stage}")
    work.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    metadata = {}
    for component in components:
        metadata[component] = globals()["build_" + component](args.rid, versions, work, output, args.jobs)
    verify(args.rid, components, output, metadata, versions, work)
    archive = stage.parent / f"avalonia-native-{args.rid}-{args.component}.zip"
    package(args.rid, components, versions, output, metadata, archive, work)


if __name__ == "__main__":
    main()
