import importlib.util
import json
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
            if rid == "win-x64":
                self.assertNotIn("skia_use_system_freetype2", arguments)
            else:
                self.assertFalse(arguments["skia_use_system_freetype2"])
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
