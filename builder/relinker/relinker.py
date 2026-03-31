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
_lib_cache = {}

def _parse_all_obj_sections(objdump_output, obj_basename):
    """Parse objdump -h output to collect all sections from all objects
    matching obj_basename in the archive. Handles duplicate object names
    and archive members stored with subdirectory paths."""
    sections = set()
    current_obj_matches = False
    for line in objdump_output.splitlines():
        if ': ' in line and 'file format ' in line:
            obj_name = line.split(':', 1)[0].strip()
            # Strip directory prefix — archive members can be stored as
            # e.g. "port/esp32c2/rtc_clk.c.o"
            obj_name = obj_name.rsplit('/', 1)[-1]
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

def _get_lib_info(lib, lib_path):
    """Return (raw_output, sections_infos) for a library archive, cached."""
    if lib_path in _lib_cache:
        return _lib_cache[lib_path]
    _ensure_entity_db()
    new_env = os.environ.copy()
    new_env['LC_ALL'] = 'C'
    raw_output = subprocess.check_output([espidf_objdump, '-h', lib_path], env=new_env).decode()
    dump = StringIO(raw_output)
    dump.name = lib
    sections_infos = EntityDB()
    sections_infos.add_sections_info(dump)
    _lib_cache[lib_path] = (raw_output, sections_infos)
    return raw_output, sections_infos

def lib_secs(lib, file, lib_path):
    raw_output, sections_infos = _get_lib_info(lib, lib_path)

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
        if '.iram1.' in l:
            secs.append(l)
        elif l.startswith('.'):
            # Pre-expanded section token from wildcard, pass through as-is
            secs.append(l)
        else:
            secs.append('.literal.%s'%(l,))
            secs.append('.text.%s'%(l, ))
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
            all_tokens = match.group(1).split()
            # Only keep whole-library tokens (no ':') — these are from the
            # original ldgen output.  Object-level tokens like
            # *lib:obj.* are relinker-generated and must not be used to
            # filter targets on subsequent runs.
            orig_tokens = [t for t in all_tokens if ':' not in t]
            self.libs_desc = ' '.join(orig_tokens)
            self.entries = {
                token.lstrip('*')
                for token in orig_tokens
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
        # Get all relevant sections (IRAM and text/literal)
        # Don't filter based on fsecs - we need ALL sections to avoid orphans
        self.secs = filter_secs(secs, ('.iram1.', '.text.', '.literal.'))
        self.isecs = strip_secs(self.secs, self.fsecs)

    def __str__(self):
        s = 'lib=%s\nfile=%s\nlib_path=%s\ndesc=%s\nsecs=%s\nfsecs=%s\nisecs=%s\n'%(\
            self.lib, self.file, self.lib_path, self.desc, self.secs, self.fsecs,\
            self.isecs)
        return s

def _is_iram_desc(l):
    """Check if a line contains an IRAM descriptor pattern.
    
    Recognizes both original ldgen patterns and relinker-generated patterns.
    """
    # Original ldgen pattern
    if '*(.iram1 .iram1.*)' in l:
        return True
    # Old relinker pattern (single line with both patterns)
    if ') .iram1 EXCLUDE_FILE(*' in l and ') .iram1.*)' in l:
        return True
    # Relinker-generated IRAM exclude patterns (single line - old format)
    if '*(EXCLUDE_FILE(' in l and ') .iram1.*)' in l and ') .iram1)' in l:
        return True
    # Relinker-generated IRAM exclude patterns (multi-line - new format)
    # First line: *(EXCLUDE_FILE(...) .iram1.*)
    if '*(EXCLUDE_FILE(' in l and ') .iram1.*)' in l:
        return True
    # Second line: *(EXCLUDE_FILE(...) .iram1)
    if '*(EXCLUDE_FILE(' in l and ') .iram1)' in l and '.iram1.*)' not in l:
        return True
    return False


def _is_relinker_iram_include(l):
    """Detect relinker-generated IRAM include lines (object-specific sections).
    
    These typically look like: *libname:objname.*(.iram1.xxx)
    Also detects leftover catch-all patterns like *(.iram1.*) / *(.iram1).
    """
    if not l.strip():
        return False
    stripped = l.strip()
    # Object-specific pattern: *libname:objname.*(.iram1.xxx)
    if stripped.startswith('*') and ':' in stripped and '.*(' in stripped and '.iram1.' in stripped:
        return True
    # Catch-all patterns from previous runs: *(.iram1.*) or *(.iram1)
    if stripped == '*(.iram1.*)' or stripped == '*(.iram1)':
        return True
    return False


def _is_relinker_flash_include(l):
    """Detect relinker-generated flash include lines.
    
    These typically look like: *libname:objname.*(.literal.xxx .text.xxx)
    or *libname:objname.*(.iram1.xxx) when func2sect passes through .iram1 sections.
    """
    if not l.strip():
        return False
    stripped = l.strip()
    # Check for pattern like: *libname:objname.*(.literal.xxx .text.xxx .iram1.xxx)
    if stripped.startswith('*') and ':' in stripped and '.*(' in stripped:
        if '.literal.' in stripped or '.text.' in stripped or '.iram1.' in stripped:
            return True
    return False


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
        desc_flash_fsecs = dict()
        desc_isecs = dict()

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

            # Merge flash fsecs per descriptor to avoid duplicates
            if len(t.fsecs) > 0:
                if t.desc not in desc_flash_fsecs:
                    desc_flash_fsecs[t.desc] = set()
                desc_flash_fsecs[t.desc].update(t.fsecs)

            # Merge all isecs per descriptor for replacement logic
            if len(t.isecs) > 0:
                if t.desc not in desc_isecs:
                    desc_isecs[t.desc] = set()
                desc_isecs[t.desc].update(t.isecs)

        for desc, isecs in desc_iram1_isecs.items():
            sorted_isecs = sorted(isecs)
            iram1_include.append('    %s(%s)'%(desc, ' '.join(sorted_isecs)))

        for desc, fsecs in desc_flash_fsecs.items():
            sorted_fsecs = sorted(fsecs)
            flash_include.append('    %s(%s)'%(desc, ' '.join(sorted_fsecs)))

        # Check if filtering left no surviving targets
        if not iram1_exclude and not iram1_include and not flash_include:
            self._no_relink = True
            return

        # Store merged per-descriptor maps as instance variables for _replace_func
        self.desc_iram1_isecs = desc_iram1_isecs
        self.desc_flash_fsecs = desc_flash_fsecs
        self.desc_isecs = desc_isecs
        
        # Build descriptor-to-library mapping for EXCLUDE_FILE logic
        self.desc_to_lib = {}
        for t in self.targets:
            if t.desc not in self.desc_to_lib:
                self.desc_to_lib[t.desc] = t.lib

        exclude_tokens = ' '.join(
            token
            for token in (self.filter.add().strip(), ' '.join(iram1_exclude).strip())
            if token
        )
        self.iram1_exclude = (
            '    *(EXCLUDE_FILE(%s) .iram1.*)\n'
            '    *(EXCLUDE_FILE(%s) .iram1)'
        ) % (exclude_tokens, exclude_tokens) if exclude_tokens else ''
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
            elif _is_iram_desc(l):
                if iram_start:
                    # Replace the IRAM descriptor and skip any following relinker IRAM includes
                    block = '\n'.join(
                        part for part in (self.iram1_exclude, self.iram1_include) if part
                    )
                    lines[i] = '%s\n' % block
                    in_relinker_iram_block = True
                    # Look ahead and remove old relinker IRAM include lines
                    j = i + 1
                    # Also remove the second line of the EXCLUDE_FILE pattern if it exists
                    if j < len(lines) and _is_iram_desc(lines[j]):
                        lines.pop(j)
                    # Remove relinker IRAM include lines
                    while j < len(lines) and _is_relinker_iram_include(lines[j]):
                        lines.pop(j)
                    in_relinker_iram_block = False
            elif '(.stub .gnu.warning' in l or l.strip() == '*(.stub)':
                if not flash_done:
                    # Remove any existing relinker flash block before this line
                    j = i - 1
                    while j >= 0 and (_is_relinker_flash_include(lines[j]) or not lines[j].strip()):
                        if _is_relinker_flash_include(lines[j]):
                            lines.pop(j)
                            i -= 1
                            j -= 1
                        elif not lines[j].strip():
                            # Remove empty lines that are part of the relinker block
                            if j > 0 and _is_relinker_flash_include(lines[j - 1]):
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
        # Use merged per-descriptor maps instead of iterating targets
        # Iterate over union of descriptors to handle cases where descriptors
        # moved completely to flash (in desc_flash_fsecs but not in desc_isecs)
        for desc in set(self.desc_isecs) | set(self.desc_flash_fsecs):
            if desc in l:
                S = '.literal .literal.* .text .text.*'
                if S in l:
                    isecs = self.desc_isecs.get(desc, set())
                    return l.replace(S, ' '.join(sorted(isecs))) if isecs else ' '
                
                fsecs = self.desc_flash_fsecs.get(desc, set())
                S = '%s(%s)'%(desc, ' '.join(sorted(fsecs)))
                if S in l:
                    return ' '

                replaced = False
                for s in fsecs:
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
        
        # Handle EXCLUDE_FILE logic using desc_to_lib mapping
        for desc, lib in self.desc_to_lib.items():
            index = '*%s:(EXCLUDE_FILE'%(lib)
            if index in l and desc not in l:
                # Collect all descriptors for this library
                for m_desc, m_lib in self.desc_to_lib.items():
                    m_index = '*%s:(EXCLUDE_FILE'%(m_lib)
                    if m_index in l and m_desc not in l:
                        l = l.replace('EXCLUDE_FILE(', 'EXCLUDE_FILE(%s '%(m_desc))
                        m_isecs = self.desc_isecs.get(m_desc, set())
                        if len(m_isecs) > 0:
                            l += '\n    %s(%s)'%(m_desc, ' '.join(sorted(m_isecs)))
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
        required=True,
        type=str)

    argparser.add_argument(
        '--output', '-o',
        help='Output linker script',
        required=True,
        type=str)

    argparser.add_argument(
        '--library', '-l',
        help='Library description directory',
        required=True,
        type=str)

    argparser.add_argument(
        '--object', '-b',
        help='Object description file',
        required=True,
        type=str)

    argparser.add_argument(
        '--function', '-f',
        help='Function description file',
        required=True,
        type=str)

    argparser.add_argument(
        '--sdkconfig', '-s',
        help='sdkconfig file',
        required=True,
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
