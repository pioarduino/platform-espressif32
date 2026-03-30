#!/usr/bin/env python3
#
# SPDX-FileCopyrightText: 2022-2023 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0


import logging
import argparse
import csv
import os
import subprocess
import sys
import re
from io import StringIO

# Support both standalone and PlatformIO-integrated usage
_script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _script_dir)
import configuration

# Resolve IDF_PATH for ldgen imports: prefer explicit --idf-path argument,
# then the IDF_PATH environment variable.
_idf_path = os.environ.get('IDF_PATH', '')
EntityDB = None

def _setup_ldgen_imports(idf_path=None):
    global _idf_path
    if idf_path:
        _idf_path = idf_path
        os.environ['IDF_PATH'] = idf_path
    if _idf_path:
        for p in [_idf_path + '/tools/ldgen', _idf_path + '/tools/ldgen/ldgen']:
            if p not in sys.path:
                sys.path.append(p)

def _ensure_entity_db():
    global EntityDB
    if EntityDB is None:
        _setup_ldgen_imports()
        from entity import EntityDB as _EntityDB
        EntityDB = _EntityDB

espidf_objdump = None

def _parse_all_obj_sections(objdump_output, obj_basename):
    """Parse objdump -h output to collect all sections from all objects
    matching obj_basename in the archive. Handles duplicate object names."""
    sections = set()
    current_obj_matches = False
    for line in objdump_output.splitlines():
        if ': ' in line and 'file format ' in line:
            obj_name = line.split(':', 1)[0].strip()
            base = obj_name[:-2] if obj_name.endswith('.o') else obj_name
            base = base[:-4] if base.endswith('.obj') else base
            current_obj_matches = (base == obj_basename or
                                   base.rsplit('.', 1)[0] == obj_basename)
        elif current_obj_matches:
            parts = line.split()
            if len(parts) >= 2:
                sec_name = parts[1]
                if sec_name.startswith(('.iram1.', '.text.', '.literal.')):
                    sections.add(sec_name)
    return sorted(sections)

def _object_desc_stem(name):
    stem = name[:-4] if name.endswith('.obj') else name
    return stem.rsplit('.', 1)[0]

def lib_secs(lib, file, lib_path):
    _ensure_entity_db()
    new_env = os.environ.copy()
    new_env['LC_ALL'] = 'C'
    raw_output = subprocess.check_output([espidf_objdump, '-h', lib_path], env=new_env).decode()
    dump = StringIO(raw_output)
    dump.name = lib

    sections_infos = EntityDB()
    sections_infos.add_sections_info(dump)

    source_name = file[:-4] if file.endswith('.obj') else file
    secs = sections_infos.get_sections(lib, source_name)
    if len(secs) == 0:
        secs = sections_infos.get_sections(lib, source_name.rsplit('.', 1)[0])
        if len(secs) == 0:
            raise ValueError('Failed to get sections from lib %s'%(lib_path))

    # Supplement with sections from all matching objects in the archive
    # to handle duplicate object names (e.g. arch-specific + generic efuse_hal.c.o)
    all_secs = _parse_all_obj_sections(raw_output, source_name)
    if all_secs:
        merged = set(secs) | set(all_secs)
        secs = sorted(merged)

    return secs

def filter_secs(secs_a, secs_b):
    new_secs = list()
    for s_a in secs_a:
        for s_b in secs_b:
            if s_b in s_a:
                new_secs.append(s_a)
    return new_secs

def strip_secs(secs_a, secs_b):
    secs = list(set(secs_a) - set(secs_b))
    secs.sort()
    return secs

def func2sect(func):
    if ' ' in func:
        func_l = func.split(' ')
    else:
        func_l = list()
        func_l.append(func)
    
    secs = list()
    for l in func_l:
        if '.iram1.' not in l:
            secs.append('.literal.%s'%(l,))
            secs.append('.text.%s'%(l, ))
        else:
            secs.append(l)
    return secs

class filter_c:
    def __init__(self, file):
        with open(file, 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()
        self.libs_desc = ''
        self.entries = set()
        for line in lines:
            match = re.search(
                r'EXCLUDE_FILE\(([^)]*)\)\s+\.iram1(?:\.\*)?\)',
                line,
            )
            if not match:
                continue
            self.libs_desc = match.group(1)
            self.entries = {
                token.lstrip('*')
                for token in self.libs_desc.split()
            }
            return
    
    def match(self, desc):
        if desc.lstrip('*') in self.entries:
            print('Remove %s' % desc)
            return True
        return False
    
    def add(self):
        return self.libs_desc

class target_c:
    def __init__(self, lib, lib_path, file, fsecs):
        self.lib   = lib
        self.file  = file

        self.lib_path  = lib_path
        self.fsecs = func2sect(fsecs)
        self.desc  = '*%s:%s.*' % (lib, _object_desc_stem(file))

        secs = lib_secs(lib, file, lib_path)
        if '.iram1.' in self.fsecs[0]:
            self.secs = filter_secs(secs, ('.iram1.', ))
        else:
            self.secs = filter_secs(secs, ('.iram1.', '.text.', '.literal.'))
        self.isecs = strip_secs(self.secs, self.fsecs)

    def __str__(self):
        s = 'lib=%s\nfile=%s\nlib_path=%s\ndesc=%s\nsecs=%s\nfsecs=%s\nisecs=%s\n'%(\
            self.lib, self.file, self.lib_path, self.desc, self.secs, self.fsecs,\
            self.isecs)
        return s

class relink_c:
    def __init__(self, input, library_file, object_file, function_file, sdkconfig_file, missing_function_info):
        self.filter = filter_c(input)
        
        # Infer build directory from input file path (typically $BUILD_DIR/sections.ld)
        build_dir = os.path.dirname(os.path.abspath(input))
        
        libraries = configuration.generator(
            library_file,
            object_file,
            function_file,
            sdkconfig_file,
            missing_function_info,
            espidf_objdump,
            build_dir=build_dir,
        )
        self.targets = list()
        for i in libraries.libs:
            lib = libraries.libs[i]

            for j in lib.objs:
                obj = lib.objs[j]
                desc = '*%s:%s.*' % (lib.name, _object_desc_stem(obj.name))
                if self.filter.match(desc):
                    continue
                self.targets.append(target_c(lib.name, lib.path, obj.name,
                                             ' '.join(obj.sections())))
        # for i in self.targets:
        #     print(i)
        self.__transform__()

    def __transform__(self):
        # Check if there are no targets to process
        if not self.targets:
            self._no_relink = True
            return
        
        iram1_exclude = list()
        iram1_include = list()
        flash_include = list()

        # Merge iram1 isecs for targets sharing the same desc to avoid orphans
        # when multiple object files in a library share the same base name
        desc_iram1_isecs = dict()

        for t in self.targets:
            secs = filter_secs(t.fsecs, ('.iram1.', ))
            if len(secs) > 0:
                if t.desc not in iram1_exclude:
                    iram1_exclude.append(t.desc)

            isecs = filter_secs(t.isecs, ('.iram1.', ))
            if len(isecs) > 0:
                if t.desc not in desc_iram1_isecs:
                    desc_iram1_isecs[t.desc] = set()
                desc_iram1_isecs[t.desc].update(isecs)

            secs = t.fsecs
            if len(secs) > 0:
                flash_include.append('    %s(%s)'%(t.desc, ' '.join(secs)))

        for desc, isecs in desc_iram1_isecs.items():
            sorted_isecs = sorted(isecs)
            iram1_include.append('    %s(%s)'%(desc, ' '.join(sorted_isecs)))

        # Check if filtering left no surviving targets
        if not iram1_exclude and not iram1_include and not flash_include:
            self._no_relink = True
            return

        self.iram1_exclude = '    *(EXCLUDE_FILE(%s %s) .iram1.*) *(EXCLUDE_FILE(%s %s) .iram1)' % \
                             (self.filter.add(), ' '.join(iram1_exclude), \
                              self.filter.add(), ' '.join(iram1_exclude))
        self.iram1_include = '\n'.join(iram1_include)
        self.flash_include = '\n'.join(flash_include)
        self._no_relink = False

        logging.debug('IRAM1 Exclude: %s'%(self.iram1_exclude))
        logging.debug('IRAM1 Include: %s'%(self.iram1_include))
        logging.debug('Flash Include: %s'%(self.flash_include))

    def __replace__(self, lines):
        # Skip rewriting if there are no targets
        if getattr(self, '_no_relink', False):
            return lines
        
        def is_iram_desc(l):
            # Recognize both original ldgen patterns and relinker-generated patterns
            if '*(.iram1 .iram1.*)' in l:
                return True
            if ') .iram1 EXCLUDE_FILE(*' in l and ') .iram1.*)' in l:
                return True
            # Recognize relinker-generated IRAM exclude patterns
            if '*(EXCLUDE_FILE(' in l and ') .iram1.*)' in l and ') .iram1)' in l:
                return True
            return False
        
        def is_relinker_iram_include(l):
            # Detect relinker-generated IRAM include lines (object-specific sections)
            # These typically look like: *libname:objname.*(section names)
            if not l.strip():
                return False
            stripped = l.strip()
            # Check for pattern like: *libname:objname.*(.iram1.xxx)
            if stripped.startswith('*') and ':' in stripped and '.*(' in stripped and '.iram1.' in stripped:
                return True
            return False
        
        def is_relinker_flash_include(l):
            # Detect relinker-generated flash include lines
            if not l.strip():
                return False
            stripped = l.strip()
            # Check for pattern like: *libname:objname.*(.literal.xxx .text.xxx)
            if stripped.startswith('*') and ':' in stripped and '.*(' in stripped:
                if '.literal.' in stripped or '.text.' in stripped:
                    return True
            return False

        iram_start = False
        flash_done = False
        in_relinker_iram_block = False
        in_relinker_flash_block = False

        i = 0
        while i < len(lines):
            l = lines[i]
            
            if '.iram0.text :' in l:
                logging.debug('start to process .iram0.text')
                iram_start = True
                in_relinker_iram_block = False
            elif '.dram0.data :' in l:
                logging.debug('end to process .iram0.text')
                iram_start = False
                in_relinker_iram_block = False
            elif is_iram_desc(l):
                if iram_start:
                    # Replace the IRAM descriptor and skip any following relinker IRAM includes
                    lines[i] = '%s\n%s\n' % (self.iram1_exclude, self.iram1_include)
                    in_relinker_iram_block = True
                    # Look ahead and remove old relinker IRAM include lines
                    j = i + 1
                    while j < len(lines) and is_relinker_iram_include(lines[j]):
                        lines.pop(j)
                    in_relinker_iram_block = False
            elif '(.stub .gnu.warning' in l or l.strip() == '*(.stub)':
                if not flash_done:
                    # Remove any existing relinker flash block before this line
                    j = i - 1
                    while j >= 0 and (is_relinker_flash_include(lines[j]) or not lines[j].strip()):
                        if is_relinker_flash_include(lines[j]):
                            lines.pop(j)
                            i -= 1
                            j -= 1
                        elif not lines[j].strip():
                            # Remove empty lines that are part of the relinker block
                            if j > 0 and is_relinker_flash_include(lines[j - 1]):
                                lines.pop(j)
                                i -= 1
                            j -= 1
                        else:
                            break
                    # Insert new flash block
                    lines[i] = '%s\n\n%s' % (self.flash_include, l)
                    flash_done = True
            elif self.flash_include in l:
                flash_done = True
            else:
                if iram_start and not in_relinker_iram_block:
                    new_l = self._replace_func(l)
                    if new_l:
                        lines[i] = new_l
            
            i += 1

        return lines

    def _replace_func(self, l):
        for t in self.targets:
            if t.desc in l:
                S = '.literal .literal.* .text .text.*'
                if S in l:
                    if len(t.isecs) > 0:
                        return l.replace(S, ' '.join(t.isecs))
                    else:
                        return ' '
                
                S = '%s(%s)'%(t.desc, ' '.join(t.fsecs))
                if S in l:
                    return ' '

                replaced = False
                for s in t.fsecs:
                    s2 = s + ' '
                    if s2 in l:
                        l = l.replace(s2, '')
                        replaced = True
                    s2 = s + ')'
                    if s2 in l:
                        l = l.replace(s2, ')')
                        replaced = True
                if '( )' in l or '()' in l:
                    return ' ' 
                if replaced:
                    return l
            else:
                index = '*%s:(EXCLUDE_FILE'%(t.lib)
                if index in l and _object_desc_stem(t.file) not in l:
                    for m in self.targets:
                        index = '*%s:(EXCLUDE_FILE'%(m.lib)
                        if index in l and _object_desc_stem(m.file) not in l:
                            l = l.replace('EXCLUDE_FILE(', 'EXCLUDE_FILE(%s '%(m.desc))
                            if len(m.isecs) > 0:
                                l += '\n    %s(%s)'%(m.desc, ' '.join(m.isecs))
                    return l

        return None

    def save(self, input, output):
        with open(input, 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()
        lines = self.__replace__(lines)
        with open(output, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

def main():
    argparser = argparse.ArgumentParser(description='Relinker script generator')

    argparser.add_argument(
        '--input', '-i',
        help='Linker template file',
        type=str)

    argparser.add_argument(
        '--output', '-o',
        help='Output linker script',
        type=str)

    argparser.add_argument(
        '--library', '-l',
        help='Library description directory',
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
        '--objdump', '-g',
        help='GCC objdump command',
        required=True,
        type=str)
    
    argparser.add_argument(
        '--debug', '-d',
        help='Debug level(option is \'debug\')',
        default='no',
        type=str)
    
    argparser.add_argument(
        '--missing_function_info',
        help='Print error information instead of throwing exception when missing function',
        action='store_true')

    argparser.add_argument(
        '--idf-path',
        help='Path to ESP-IDF framework directory',
        default=None,
        type=str)

    args = argparser.parse_args()

    if args.idf_path:
        _setup_ldgen_imports(args.idf_path)
    _ensure_entity_db()

    if args.debug == 'debug':
        logging.basicConfig(level=logging.DEBUG)

    logging.debug('input:    %s'%(args.input))
    logging.debug('output:   %s'%(args.output))
    logging.debug('library:  %s'%(args.library))
    logging.debug('object:   %s'%(args.object))
    logging.debug('function: %s'%(args.function))
    logging.debug('sdkconfig:%s'%(args.sdkconfig))
    logging.debug('objdump:  %s'%(args.objdump))
    logging.debug('debug:    %s'%(args.debug))
    logging.debug('missing_function_info: %s'%(args.missing_function_info))

    global espidf_objdump
    espidf_objdump = args.objdump

    relink = relink_c(args.input, args.library, args.object, args.function, args.sdkconfig, args.missing_function_info)
    relink.save(args.input, args.output)

def run_relinker(input_file, output_file, library_file, object_file, function_file,
                 sdkconfig_file, objdump, idf_path=None, missing_function_info=False,
                 debug=False):
    """API entry point for PlatformIO integration.

    Parameters mirror the CLI arguments so the relinker can be called
    directly from the build system without spawning a subprocess.
    """
    if idf_path:
        _setup_ldgen_imports(idf_path)
    _ensure_entity_db()

    if debug:
        logging.basicConfig(level=logging.DEBUG)

    global espidf_objdump
    espidf_objdump = objdump

    relink = relink_c(input_file, library_file, object_file, function_file,
                      sdkconfig_file, missing_function_info)
    relink.save(input_file, output_file)


if __name__ == '__main__':
    main()
