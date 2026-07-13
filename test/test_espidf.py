#!/usr/bin/env python3

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


builder_dir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "builder"
)
sys.path.insert(0, builder_dir)

from espidf_libs import copy_idf_component_archives


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


if __name__ == "__main__":
    unittest.main()
