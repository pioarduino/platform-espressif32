import os
import shutil
from pathlib import Path


def copy_idf_component_archives(lib_src, lib_dst):
    lib_src = Path(lib_src)
    if not lib_src.is_dir():
        raise FileNotFoundError("IDF library source directory does not exist: %s" % lib_src)

    copied_names = {}
    for folder in sorted(lib_src.iterdir()):
        if not folder.is_dir():
            continue

        for root, dirs, files in os.walk(folder):
            dirs.sort()
            files.sort()
            for filename in files:
                if not filename.endswith(".a"):
                    continue

                copied_names[filename] = copied_names.get(filename, 0) + 1
                basename = filename.rsplit(".a", 1)[0]
                dst_name = (
                    filename
                    if copied_names[filename] == 1
                    else "%s_%d.a" % (basename, copied_names[filename])
                )
                shutil.copyfile(str(Path(root) / filename), str(Path(lib_dst) / dst_name))
