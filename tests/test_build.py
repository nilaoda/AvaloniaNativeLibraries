import importlib.util
import json
import struct
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("native_build", ROOT / "scripts/build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class BuildConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.versions = json.loads((ROOT / "config/versions.json").read_text())

    def test_platform_components_and_source_revisions_are_fixed(self):
        self.assertNotIn("angle", build.COMPONENTS["linux-x64"])
        self.assertIn("avalonia", build.COMPONENTS["osx-arm64"])
        for name in ("skia", "harfbuzz", "angle", "avalonia", "depot_tools"):
            self.assertRegex(self.versions[name]["revision"], r"^[0-9a-f]{40}$")
        self.assertEqual("2.88.9", self.versions["skia"]["version"])
        self.assertEqual("8.3.1.1", self.versions["harfbuzz"]["binding_version"])

    def test_static_skia_keeps_gpu_and_platform_compatibility(self):
        for rid in build.COMPONENTS:
            arguments = build.skia_arguments(rid, self.versions)
            self.assertTrue(arguments["is_static_skiasharp"])
            self.assertTrue(arguments["skia_enable_gpu"])
            if rid.startswith("win-"):
                self.assertNotIn("skia_use_system_freetype2", arguments)
            else:
                self.assertFalse(arguments["skia_use_system_freetype2"])
        for rid in build.COMPONENTS:
            self.assertEqual(rid.split("-")[1], build.skia_arguments(rid, self.versions)["target_cpu"])
        mac = build.skia_arguments("osx-arm64", self.versions)
        self.assertEqual("arm64", mac["target_cpu"])
        self.assertEqual("14.0", mac["min_macos_version"])
        self.assertIn("/MT", build.skia_arguments("win-x64", self.versions)["extra_cflags"])

    def test_angle_patch_is_idempotent_and_keeps_required_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / "BUILD.gn").write_text('angle_static_library("libGLESv2_static") {\n}\n')
            (source / "DEPS").write_text("deps = {\n  'third_party/dawn': {\n    'url': 'unused',\n  },\n  'required': 'keep',\n}\n")
            build.patch_angle(source)
            first = (source / "BUILD.gn").read_bytes(), (source / "DEPS").read_bytes()
            build.patch_angle(source)
            self.assertEqual(first, ((source / "BUILD.gn").read_bytes(), (source / "DEPS").read_bytes()))
            self.assertIn(b'complete_static_lib = true', first[0])
            self.assertNotIn(b'third_party/dawn', first[1])
            self.assertIn(b"'required': 'keep'", first[1])

    def test_angle_input_layout_key_has_no_implicit_padding(self):
        header = ("#include <array>\n#include <map>\n\n"
                  "struct PackedAttributeLayout\n{\n"
                  "    PackedAttributeLayout();\n"
                  "    PackedAttributeLayout(const PackedAttributeLayout &other);\n\n"
                  "    bool operator==(const PackedAttributeLayout &other) const;\n\n"
                  "    uint32_t numAttributes;\n"
                  "    gl::AttribArray<uint64_t> attributeData;\n"
                  "};\n")
        unit = ("}  // anonymous namespace\n\n"
                "PackedAttributeLayout::PackedAttributeLayout() : numAttributes(0), attributeData({}) {}\n\n"
                "PackedAttributeLayout::PackedAttributeLayout(const PackedAttributeLayout &other) = default;\n\n"
                "void PackedAttributeLayout::addAttributeData()\n")
        for newline in (b"\n", b"\r\n"):
            with tempfile.TemporaryDirectory() as directory:
                source = Path(directory)
                folder = source / "src/libANGLE/renderer/d3d/d3d11"
                folder.mkdir(parents=True)
                (folder / "InputLayoutCache.h").write_bytes(header.encode().replace(b"\n", newline))
                (folder / "InputLayoutCache.cpp").write_bytes(unit.encode().replace(b"\n", newline))
                build.patch_angle_input_layout_key(source)
                first = (folder / "InputLayoutCache.h").read_bytes(), (folder / "InputLayoutCache.cpp").read_bytes()
                build.patch_angle_input_layout_key(source)
                self.assertEqual(first, ((folder / "InputLayoutCache.h").read_bytes(),
                                         (folder / "InputLayoutCache.cpp").read_bytes()))
                self.assertIn(b"    uint32_t pad0                           = 0;" + newline, first[0])
                self.assertIn(b"#include <map>" + newline + b"#include <type_traits>" + newline, first[0])
                self.assertIn(b"static_assert(std::has_unique_object_representations_v<PackedAttributeLayout>,", first[0])
                self.assertNotIn(b"PackedAttributeLayout();", first[0])
                self.assertNotIn(b"PackedAttributeLayout::PackedAttributeLayout(", first[1])
                self.assertIn(b"void PackedAttributeLayout::addAttributeData()", first[1])
                if newline == b"\r\n":
                    self.assertNotIn(b"\n", first[0].replace(b"\r\n", b""))

    def test_angle_input_layout_key_patch_rejects_other_revisions_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            folder = source / "src/libANGLE/renderer/d3d/d3d11"
            folder.mkdir(parents=True)
            header = b"struct PackedAttributeLayout\n{\n    uint32_t numAttributes;\n};\n"
            unit = b"PackedAttributeLayout::PackedAttributeLayout() : numAttributes(0) {}\n"
            (folder / "InputLayoutCache.h").write_bytes(header)
            (folder / "InputLayoutCache.cpp").write_bytes(unit)
            with self.assertRaises(ValueError):
                build.patch_angle_input_layout_key(source)
            self.assertEqual(header, (folder / "InputLayoutCache.h").read_bytes())
            self.assertEqual(unit, (folder / "InputLayoutCache.cpp").read_bytes())

    def test_angle_arm64_uses_installed_runtime_family(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            script = source / "build/vs_toolchain.py"
            script.parent.mkdir()
            script.write_bytes(b"MSVC_TOOLSET_VERSION = {\r\n    '2022': 'VC143',\r\n}\r\n")
            for version, family in (("14.9.1", "VC143"), ("14.52.37025", "VC145")):
                runtime = source / "VC/Redist/MSVC" / version / "arm64" / f"Microsoft.{family}.CRT"
                runtime.mkdir(parents=True)
                (runtime / "msvcp140.dll").touch()
            build.patch_angle_arm64_toolset(source, source)
            expected = b"MSVC_TOOLSET_VERSION = {\r\n    '2022': 'VC145',\r\n}\r\n"
            self.assertEqual(expected, script.read_bytes())
            build.patch_angle_arm64_toolset(source, source)
            self.assertEqual(expected, script.read_bytes())

    def test_archive_architecture_accepts_target_and_rejects_mixed_objects(self):
        def member(machine):
            body = machine.to_bytes(2, "little") + bytes(18)
            header = f"{'test.obj/':<16}{0:<12}{0:<6}{0:<6}{644:<8}{len(body):<10}`\n".encode()
            return header + body
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.lib"
            path.write_bytes(b"!<arch>\n" + member(0xaa64))
            build.verify_archive_architecture(path, "win-arm64")
            with self.assertRaises(ValueError):
                build.verify_archive_architecture(path, "win-x64")
            path.write_bytes(b"!<arch>\n" + member(0xaa64) + member(0x8664))
            with self.assertRaises(ValueError):
                build.verify_archive_architecture(path, "win-arm64")

    def test_metal_exports_only_change_the_two_selected_visibility_flags(self):
        names = [b"_gr_direct_context_make_metal_with_options", b"_gr_backendrendertarget_new_metal", b"_unrelated"]
        strings = b"\0"
        symbols = b""
        for name in names:
            symbols += struct.pack("<IBBHQ", len(strings), 0x1f, 1, 0, 0)
            strings += name + b"\0"
        obj = struct.pack("<8I", 0xfeedfacf, 0x100000c, 0, 1, 1, 24, 0, 0)
        obj += struct.pack("<6I", 2, 24, 56, len(names), 56 + len(symbols), len(strings))
        obj += symbols + strings
        header = f"{'test.o/':<16}{0:<12}{0:<6}{0:<6}{644:<8}{len(obj):<10}`\n".encode()
        original = b"!<arch>\n" + header + obj + (b"\n" if len(obj) % 2 else b"")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "libskia.a"
            path.write_bytes(original)
            self.assertTrue(build.expose_metal_entry_points(path))
            updated = path.read_bytes()
            self.assertEqual(2, sum(a != b for a, b in zip(original, updated)))
            self.assertFalse(build.expose_metal_entry_points(path))
            self.assertEqual(updated, path.read_bytes())

    def test_thin_archive_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "thin.a"
            source.write_bytes(b"!<thin>\n")
            with self.assertRaises(ValueError):
                build.copy_library(source, Path(directory))

    def test_macos_patch_preserves_line_endings_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            zutil = source / "third_party/externals/zlib/zutil.h"
            png = source / "third_party/externals/libpng/pngpriv.h"
            gn = source / "gn/BUILD.gn"
            zutil.parent.mkdir(parents=True)
            png.parent.mkdir(parents=True)
            gn.parent.mkdir(parents=True)
            zutil.write_bytes(b"#if defined(MACOS) || defined(TARGET_OS_MAC)\r\n#endif")
            png.write_bytes(b"defined(THINK_C) || defined(__SC__) || defined(TARGET_OS_MAC)\r\n")
            gn.write_bytes(b'cflags = [ "arm64-apple-macos11" ]\r\n')
            build.patch_macos_skia(source, "14.0")
            first = zutil.read_bytes(), gn.read_bytes()
            build.patch_macos_skia(source, "14.0")
            self.assertEqual(first, (zutil.read_bytes(), gn.read_bytes()))
            self.assertIn(b"&& !defined(__APPLE__)\r\n", first[0])
            self.assertTrue(first[0].endswith(b"#endif"))
            self.assertIn(b'"arm64-apple-macos14.0"', first[1])
            self.assertIn(b"(defined(TARGET_OS_MAC) && !defined(__APPLE__))\r\n", png.read_bytes())

    def test_skia_header_patch_is_idempotent_and_preserves_crlf(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            color = source / "src/utils/SkParseColor.cpp"
            color.parent.mkdir(parents=True)
            color.write_bytes(b'#include "include/utils/SkParse.h"\r\nvoid test();')
            build.patch_skia_headers(source)
            first = color.read_bytes()
            build.patch_skia_headers(source)
            self.assertEqual(first, color.read_bytes())
            self.assertIn(b"#include <algorithm>\r\n#include <iterator>\r\n", first)
            self.assertTrue(first.endswith(b"void test();"))

    def test_gn_metadata_accepts_warning_prefix_and_empty_frameworks(self):
        outputs = (
            'WARNING at build arg file: Build argument has no effect.\n\n'
            '{"//:SkiaSharp": {"libs": ["user32.lib"]}}',
            '{"//:SkiaSharp": {}}',
        )
        with patch.object(build, "run", side_effect=outputs):
            metadata = build.gn_link_metadata("gn", "out", "//:SkiaSharp", ROOT)
        self.assertEqual({"libs": ["user32.lib"], "frameworks": []}, metadata)

    def test_macos_objc_retention_is_forwarded_to_linker(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            with patch.object(build, "macos_cpp_toolchain", return_value=("clang++", "/sdk")), \
                    patch.object(build, "run", side_effect=(None, "app:\n", "Native static libraries verified.\n")) as command:
                build.verify("osx-arm64", ("skia",), work, {"skia": {"libs": [], "frameworks": []}},
                             self.versions, work)
            arguments = command.call_args_list[0].args
            self.assertIn("-Wl,-ObjC", arguments)
            self.assertNotIn("-ObjC", arguments)


if __name__ == "__main__":
    unittest.main()
