import os
import shutil
from pathlib import Path


def copy_idf_component_archives(lib_src, lib_dst):
    """Copy all .a archives from IDF component directories into lib_dst.

    Archives are collected recursively so nested component sub-build outputs are
    included. Duplicate archive basenames are kept with numeric suffixes
    (for example, libfoo.a, libfoo_2.a, ...). Raises FileNotFoundError when
    lib_src does not exist or is not a directory.
    """
    lib_src = Path(lib_src)
    if not lib_src.is_dir():
        raise FileNotFoundError(
            f"IDF library source directory does not exist or is not a directory: {lib_src}"
        )

    copied_names = {}
    for folder in sorted(lib_src.iterdir()):
        if not folder.is_dir():
            continue

        # topdown=True lets the in-place dirs.sort() below control traversal
        # order so duplicate suffix assignment stays deterministic.
        for root, dirs, files in os.walk(folder, topdown=True):
            dirs.sort()
            files.sort()
            for filename in files:
                if not filename.endswith(".a"):
                    continue

                copied_names[filename] = copied_names.get(filename, 0) + 1
                dst_name = (
                    filename
                    if copied_names[filename] == 1
                    else f"{filename[:-2]}_{copied_names[filename]}.a"
                )
                shutil.copyfile(str(Path(root) / filename), str(Path(lib_dst) / dst_name))
