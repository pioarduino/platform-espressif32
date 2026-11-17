#!/usr/bin/env python3

import ast
import functools
import re
import shutil
import tempfile
import unittest
from pathlib import Path


ARCHIVE_COPY_FUNCTIONS = (
    "read_link_library_names",
    "resolve_link_library_name",
    "copy_idf_component_archives",
)


@functools.lru_cache(maxsize=1)
def _load_archive_copy_namespace():
    """Load the helpers without importing espidf.py's SCons/PlatformIO side effects."""
    espidf_path = Path(__file__).resolve().parent.parent / "builder" / "frameworks" / "espidf.py"
    module_ast = ast.parse(espidf_path.read_text(encoding="utf8"), filename=str(espidf_path))
    function_defs = [
        node
        for node in module_ast.body
        if isinstance(node, ast.FunctionDef) and node.name in ARCHIVE_COPY_FUNCTIONS
    ]
    missing = set(ARCHIVE_COPY_FUNCTIONS) - {node.name for node in function_defs}
    if missing:
        raise AssertionError(
            f"{', '.join(sorted(missing))} not found in builder/frameworks/espidf.py"
        )
    isolated_module = ast.Module(body=function_defs, type_ignores=[])
    # Keep this namespace synchronized with the helpers' import requirements
    # (currently os, re, shutil, and Path), or this isolated loader will fail
    # when they gain new module-level dependencies.
    namespace = {"os": __import__("os"), "re": re, "shutil": shutil, "Path": Path}
    exec(compile(isolated_module, filename=str(espidf_path), mode="exec"), namespace)
    return namespace


_namespace = _load_archive_copy_namespace()
read_link_library_names = _namespace["read_link_library_names"]
copy_idf_component_archives = _namespace["copy_idf_component_archives"]


class TestEspIdfArchiveCopy(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.lib_src = self.temp_dir / "esp-idf"
        self.lib_dst = self.temp_dir / "lib"
        self.lib_dst.mkdir()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def _write_file(self, relative_path, content):
        path = self.lib_src / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def _write_build_script(self, link_names):
        """Write a pioarduino-build.py stub whose LIBS list carries link_names."""
        path = self.temp_dir / "pioarduino-build.py"
        entries = ", ".join(f'"-l{name}"' for name in link_names)
        path.write_text(f"env.Append(\n    LIBS=[\n        {entries}\n    ]\n)\n")
        return path

    def test_copies_nested_archives_and_suffixes_duplicates(self):
        self._write_file("mbedtls/libmbedtls.a", "top-level")
        self._write_file("mbedtls/mbedtls/library/libmbedtls.a", "nested")
        self._write_file("mbedtls/mbedtls/3rdparty/p256-m/libp256m.a", "p256")
        self._write_file("mbedtls/readme.txt", "ignore")

        copy_idf_component_archives(str(self.lib_src), str(self.lib_dst))

        self.assertEqual(
            sorted(path.name for path in self.lib_dst.iterdir()),
            ["libmbedtls.a", "libmbedtls_2.a", "libp256m.a"],
        )
        self.assertEqual((self.lib_dst / "libmbedtls.a").read_text(), "top-level")
        self.assertEqual((self.lib_dst / "libmbedtls_2.a").read_text(), "nested")

    def test_orders_component_duplicates_deterministically(self):
        self._write_file("z_component/libsame.a", "z")
        self._write_file("a_component/libsame.a", "a")

        copy_idf_component_archives(str(self.lib_src), str(self.lib_dst))

        self.assertEqual((self.lib_dst / "libsame.a").read_text(), "a")
        self.assertEqual((self.lib_dst / "libsame_2.a").read_text(), "z")

    def test_renames_archives_onto_the_linked_names(self):
        self._write_file("esp_driver_sdm/libesp_driver_sdm.a", "sdm")
        self._write_file("esp_driver_sdmmc/libesp_driver_sdmmc.a", "sdmmc")
        self._write_file("espressif__rmaker_common/libespressif__rmaker_common.a", "rmaker")
        self._write_file("espressif__fb_gfx/libespressif__fb_gfx.a", "fb_gfx")

        copy_idf_component_archives(
            str(self.lib_src),
            str(self.lib_dst),
            str(self._write_build_script(
                [
                    "esp_driver_sdm_2",
                    "esp_driver_sdmmc",
                    "espressif__rmaker_common_2",
                    "espressif__rmaker_common_events",
                    "fb_gfx",
                ]
            )),
        )

        self.assertEqual(
            sorted(path.name for path in self.lib_dst.iterdir()),
            [
                "libesp_driver_sdm_2.a",
                "libesp_driver_sdmmc.a",
                "libespressif__rmaker_common_2.a",
                "libfb_gfx.a",
            ],
        )
        self.assertEqual((self.lib_dst / "libesp_driver_sdm_2.a").read_text(), "sdm")
        self.assertEqual((self.lib_dst / "libfb_gfx.a").read_text(), "fb_gfx")

    def test_keeps_duplicate_suffixes_that_the_link_line_carries(self):
        self._write_file("mbedtls/libmbedtls.a", "top-level")
        self._write_file("mbedtls/mbedtls/library/libmbedtls.a", "nested")

        copy_idf_component_archives(
            str(self.lib_src),
            str(self.lib_dst),
            str(self._write_build_script(["mbedtls", "mbedtls_2"])),
        )

        self.assertEqual((self.lib_dst / "libmbedtls.a").read_text(), "top-level")
        self.assertEqual((self.lib_dst / "libmbedtls_2.a").read_text(), "nested")

    def test_resolves_a_stripped_prefix_that_also_carries_a_suffix(self):
        # A component local to copy-libs.sh loses its espressif__ prefix, and
        # one whose name is a substring of an earlier entry gains a _2 suffix.
        # Both apply to the same component when it is local and collided there,
        # leaving the link line carrying only the stripped, suffixed name.
        self._write_file("espressif__fb_gfx/libespressif__fb_gfx.a", "fb_gfx")

        copy_idf_component_archives(
            str(self.lib_src),
            str(self.lib_dst),
            str(self._write_build_script(["fb_gfx_2", "fb_gfx_extra"])),
        )

        self.assertEqual(
            [path.name for path in self.lib_dst.iterdir()], ["libfb_gfx_2.a"]
        )
        self.assertEqual((self.lib_dst / "libfb_gfx_2.a").read_text(), "fb_gfx")

    def test_never_hands_out_one_link_name_to_two_archives(self):
        # The managed component resolves to "fb_gfx" by dropping its prefix,
        # which is also the plain name of the local one. Both archives have to
        # survive: whichever claims the name first keeps it, and the other is
        # kept under a free name rather than overwriting it.
        self._write_file("espressif__fb_gfx/libespressif__fb_gfx.a", "managed")
        self._write_file("fb_gfx/libfb_gfx.a", "local")

        copy_idf_component_archives(
            str(self.lib_src),
            str(self.lib_dst),
            str(self._write_build_script(["fb_gfx"])),
        )

        self.assertEqual(
            sorted(path.name for path in self.lib_dst.iterdir()),
            ["libfb_gfx.a", "libfb_gfx_2.a"],
        )
        self.assertEqual((self.lib_dst / "libfb_gfx.a").read_text(), "managed")
        self.assertEqual((self.lib_dst / "libfb_gfx_2.a").read_text(), "local")

    def test_keeps_plain_names_for_absent_link_names(self):
        self._write_file("component/libunlisted.a", "unlisted")

        copy_idf_component_archives(
            str(self.lib_src),
            str(self.lib_dst),
            str(self._write_build_script(["something_else"])),
        )

        self.assertEqual((self.lib_dst / "libunlisted.a").read_text(), "unlisted")

    def test_reads_no_link_names_from_a_missing_build_script(self):
        self.assertEqual(read_link_library_names(None), set())
        self.assertEqual(read_link_library_names(str(self.temp_dir / "absent.py")), set())

    def test_reads_only_quoted_link_names(self):
        build_script = self._write_build_script(["esp_driver_sdm_2", "mbedtls"])
        build_script.write_text(
            build_script.read_text() + "\n# -lnot_a_link_name in a comment\n"
        )

        self.assertEqual(
            read_link_library_names(str(build_script)), {"esp_driver_sdm_2", "mbedtls"}
        )

    def test_raises_for_missing_source_directory(self):
        missing_src = self.temp_dir / "missing"

        with self.assertRaises(FileNotFoundError) as ctx:
            copy_idf_component_archives(str(missing_src), str(self.lib_dst))

        self.assertIn("does not exist or is not a directory", str(ctx.exception))

    def test_raises_for_missing_destination_directory(self):
        missing_dst = self.temp_dir / "missing-lib"
        self._write_file("component/libtest.a", "test")

        with self.assertRaises(FileNotFoundError) as ctx:
            copy_idf_component_archives(str(self.lib_src), str(missing_dst))

        self.assertIn("destination directory", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
