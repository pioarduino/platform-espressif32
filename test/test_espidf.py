#!/usr/bin/env python3

import ast
import os
import shutil
import tempfile
import unittest
from pathlib import Path


def _load_copy_helper():
    repo_dir = Path(__file__).resolve().parent.parent
    espidf_path = repo_dir / "builder" / "frameworks" / "espidf.py"
    module = ast.parse(espidf_path.read_text())
    helper = next(
        node for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "_copy_idf_component_archives"
    )
    namespace = {"os": os, "shutil": shutil, "Path": Path}
    exec(compile(ast.Module(body=[helper], type_ignores=[]), str(espidf_path), "exec"), namespace)
    return namespace["_copy_idf_component_archives"]


class TestEspIdfArchiveCopy(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.lib_src = self.temp_dir / "esp-idf"
        self.lib_dst = self.temp_dir / "lib"
        self.lib_dst.mkdir()
        self.copy_helper = _load_copy_helper()

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

        self.copy_helper(str(self.lib_src), str(self.lib_dst))

        self.assertEqual(
            sorted(path.name for path in self.lib_dst.iterdir()),
            ["libmbedtls.a", "libmbedtls_2.a", "libp256m.a"],
        )
        self.assertEqual((self.lib_dst / "libmbedtls.a").read_text(), "top-level")
        self.assertEqual((self.lib_dst / "libmbedtls_2.a").read_text(), "nested")

    def test_orders_component_duplicates_deterministically(self):
        self._write_file("z_component/libsame.a", "z")
        self._write_file("a_component/libsame.a", "a")

        self.copy_helper(str(self.lib_src), str(self.lib_dst))

        self.assertEqual((self.lib_dst / "libsame.a").read_text(), "a")
        self.assertEqual((self.lib_dst / "libsame_2.a").read_text(), "z")


if __name__ == "__main__":
    unittest.main()
