#!/usr/bin/env python3
#
# SPDX-FileCopyrightText: 2022-2023 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0


import argparse
import csv
import os
import subprocess
import sys
import re
from io import StringIO

OPT_MIN_LEN = 7

espidf_objdump = None
espidf_missing_function_info = True

class sdkconfig_c:
    def __init__(self, path):
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()
        config = dict()
        for line in lines:
            if len(line) > OPT_MIN_LEN and line[0] != '#':
                mo = re.match( r'(.*)=(.*)', line, re.M|re.I)
                if mo:
                    config[mo.group(1)]=mo.group(2).replace('"', '')
        self.config = config
    
    def index(self, i):
        return self.config[i]
    
    def check(self, options):
        options = options.replace(' ', '')
        if '&&' in options:
            for i in options.split('&&'):
                i = i.strip()
                if not i:  # Malformed expression (e.g. "CONFIG_A&&" or "&&CONFIG_A")
                    return False
                if i[0] == '!':
                    i = i[1:]
                    if not i:  # Malformed negation token (bare '!')
                        return False
                    if i in self.config:
                        return False
                else:
                    if i not in self.config:
                        return False
        else:
            i = options.strip()  # Remove any whitespace
            if not i:  # Handle empty string
                return True  # Empty option is considered valid
            if i[0] == '!':
                i = i[1:]
                if not i:  # Malformed negation token (bare '!')
                    return False
                if i in self.config:
                    return False
            else:
                if i not in self.config:
                    return False
        return True

class object_c:
    def read_dump_info(self, paths):
        new_env = os.environ.copy()
        new_env['LC_ALL'] = 'C'
        dumps = list()
        for path in paths:
            if not os.path.isfile(path):
                if espidf_missing_function_info:
                    print('Warning: object file not found, skipping: %s' % path)
                    continue
                raise RuntimeError('Object file not found: %s' % path)
            try:
                dump = StringIO(subprocess.check_output([espidf_objdump, '-t', path], env=new_env).decode())
                dumps.append(dump.readlines())
            except subprocess.CalledProcessError as e:
                raise RuntimeError('cmd:%s result:%s'%(e.cmd, e.returncode)) from e
        return dumps

    def get_func_section(self, dumps, func):
        for dump in dumps:
            for l in dump:
                if ' %s'%(func) in l and '*UND*' not in l:
                    m = re.match(r'(\S*)\s*([glw])\s*([F|O])\s*(\S*)\s*(\S*)\s*(\S*)\s*', l, re.M|re.I)
                    if m is not None and m[6] == func:
                        return m[4].replace('.text.', '')
        if espidf_missing_function_info:
            print('%s failed to find section'%(func))
            return None
        else:
            raise RuntimeError('%s failed to find section'%(func))

    def __init__(self, name, paths, library):
        self.name = name
        self.library = library
        self.funcs = dict()
        self.paths = paths
        self.dumps = self.read_dump_info(paths)
    
    def append(self, func):
        section = self.get_func_section(self.dumps, func)
        if section is None:
            return False
        self.funcs[func] = section
        return True
    
    def functions(self):
        nlist = list()
        for i in self.funcs:
            nlist.append(i)
        return nlist
    
    def sections(self):
        nlist = list()
        for i in self.funcs:
            nlist.append(self.funcs[i])
        return nlist

class library_c:
    def __init__(self, name, path):
        self.name = name
        self.path = path
        self.objs = dict()

    def append(self, obj, path, func):
        if obj in self.objs:
            self.objs[obj].append(func)
            return

        candidate = object_c(obj, path, self.name)
        if candidate.append(func):
            self.objs[obj] = candidate

class libraries_c:
    def __init__(self):
        self.libs = dict()

    def append(self, lib, lib_path, obj, obj_path, func):
        if lib not in self.libs:
            self.libs[lib] = library_c(lib, lib_path)
        self.libs[lib].append(obj, obj_path, func)
    
    def dump(self):
        for libname in self.libs:
            lib = self.libs[libname]
            for objname in lib.objs:
                obj = lib.objs[objname]
                print('%s, %s, %s, %s'%(libname, objname, obj.path, obj.funcs))

class paths_c:
    def __init__(self, build_dir=None):
        self.paths = dict()
        self.build_dir = build_dir or os.environ.get('BUILD_DIR')
    
    def append(self, lib, obj, path):
        if '$IDF_PATH' in path:
            idf_path = os.environ.get('IDF_PATH')
            if not idf_path:
                raise RuntimeError(
                    "Path '%s' references $IDF_PATH but IDF_PATH environment variable is not set" % path
                )
            path = path.replace('$IDF_PATH', idf_path)
        
        # Normalize relative paths to absolute paths based on build directory
        if not os.path.isabs(path) and self.build_dir:
            path = os.path.normpath(os.path.join(self.build_dir, path))

        if lib not in self.paths:
            self.paths[lib] = dict()
        if obj not in self.paths[lib]:
            self.paths[lib][obj] = list()
        self.paths[lib][obj].append(path)
    
    def index(self, lib, obj):
        if lib not in self.paths:
            return None
        if obj in self.paths[lib]:
            return self.paths[lib][obj]
        if '*' in self.paths[lib]:
            return self.paths[lib]['*']
        return None

def generator(library_file, object_file, function_file, sdkconfig_file, missing_function_info, objdump='riscv32-esp-elf-objdump', build_dir=None):
    global espidf_objdump, espidf_missing_function_info
    espidf_objdump = objdump
    espidf_missing_function_info = missing_function_info

    sdkconfig = sdkconfig_c(sdkconfig_file)
    
    # Determine build directory: use provided build_dir, or infer from library_file location
    if build_dir is None:
        build_dir = os.environ.get('BUILD_DIR')
        if build_dir is None:
            # Infer from library_file path - CSV files are typically in the build directory
            build_dir = os.path.dirname(os.path.abspath(library_file))

    lib_paths = paths_c(build_dir)
    with open(library_file, 'r') as f:
        for p in csv.DictReader(f):
            lib_paths.append(p['library'], '*', p['path'])

    obj_paths = paths_c(build_dir)
    with open(object_file, 'r') as f:
        for p in csv.DictReader(f):
            obj_paths.append(p['library'], p['object'], p['path'])

    libraries = libraries_c()
    with open(function_file, 'r') as f:
        for d in csv.DictReader(f):
            option = (d.get('option') or '').strip()
            if option and not sdkconfig.check(option):
                print('skip %s(%s)' % (d['function'], option))
                continue
            lib_path = lib_paths.index(d['library'], '*')
            obj_path = obj_paths.index(d['library'], d['object'])
            if not lib_path:
                raise RuntimeError(
                    "Library '%s' not found in library CSV for function '%s'" 
                    % (d['library'], d['function'])
                )
            if not obj_path:
                obj_path = lib_path
            libraries.append(d['library'], lib_path[0], d['object'], obj_path, d['function'])
    return libraries

def main():
    argparser = argparse.ArgumentParser(description='Libraries management')

    argparser.add_argument(
        '--library', '-l',
        help='Library description file',
        type=str)

    argparser.add_argument(
        '--object', '-b',
        help='Object description file',
        type=str)

    argparser.add_argument(
        '--function', '-f',
        help='Function description file',
        type=str)

    argparser.add_argument(
        '--sdkconfig', '-s',
        help='sdkconfig file',
        type=str)

    argparser.add_argument(
        '--objdump',
        help='GCC objdump command',
        default='riscv32-esp-elf-objdump',
        type=str)

    argparser.add_argument(
        '--missing_function_info',
        help='Print missing function info instead of raising an error',
        action='store_true')

    args = argparser.parse_args()

    libraries = generator(
        args.library,
        args.object,
        args.function,
        args.sdkconfig,
        args.missing_function_info,
        objdump=args.objdump,
    )
    # libraries.dump()

if __name__ == '__main__':
    main()