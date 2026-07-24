#!/usr/bin/env python3

import ast
import functools
import shutil
import tempfile
import unittest
from pathlib import Path


@functools.lru_cache(maxsize=1)
def _load_copy_idf_component_archives():
    """Load the helper without importing espidf.py's SCons/PlatformIO side effects."""
    espidf_path = Path(__file__).resolve().parent.parent / "builder" / "frameworks" / "espidf.py"
    module_ast = ast.parse(espidf_path.read_text(encoding="utf8"), filename=str(espidf_path))
    try:
        function_def = next(
            node
            for node in module_ast.body
            if isinstance(node, ast.FunctionDef) and node.name == "copy_idf_component_archives"
        )
    except StopIteration as exc:
        raise AssertionError(
            "copy_idf_component_archives not found in builder/frameworks/espidf.py"
        ) from exc
    isolated_module = ast.Module(body=[function_def], type_ignores=[])
    # Keep this namespace synchronized with copy_idf_component_archives import
    # requirements (currently os, shutil, and Path), or this isolated loader
    # will fail when the helper gains new module-level dependencies.
    namespace = {"os": __import__("os"), "shutil": shutil, "Path": Path}
    exec(compile(isolated_module, filename=str(espidf_path), mode="exec"), namespace)
    return namespace["copy_idf_component_archives"]


copy_idf_component_archives = _load_copy_idf_component_archives()


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
