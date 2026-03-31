#!/usr/bin/env python3
"""
Unit tests for builder/relinker/configuration.py

Tests cover:
- sdkconfig_c: Configuration parsing and checking
- paths_c: Path management and normalization
- object_c: Object file handling
- library_c: Library management
- libraries_c: Library collection
"""

import unittest
from unittest import mock
import tempfile
import os
import sys
from pathlib import Path

# Add the relinker directory to the path
relinker_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'builder', 'relinker')
sys.path.insert(0, relinker_dir)

from configuration import sdkconfig_c, paths_c, object_c, library_c, libraries_c


class TestSdkconfigC(unittest.TestCase):
    """Test sdkconfig_c class for configuration parsing and validation."""
    
    def setUp(self):
        """Create a temporary sdkconfig file for testing."""
        self.temp_dir = tempfile.mkdtemp()
        self.sdkconfig_path = os.path.join(self.temp_dir, 'sdkconfig')
        
        with open(self.sdkconfig_path, 'w') as f:
            f.write('# Test sdkconfig\n')
            f.write('CONFIG_FREERTOS_PLACE_FUNCTIONS_INTO_FLASH=y\n')
            f.write('CONFIG_ESP32_DEFAULT_CPU_FREQ_240=y\n')
            f.write('# CONFIG_SOME_DISABLED is not set\n')
            f.write('CONFIG_EMPTY_VALUE=\n')
    
    def tearDown(self):
        """Clean up temporary files."""
        import shutil
        shutil.rmtree(self.temp_dir)
    
    def test_parse_sdkconfig(self):
        """Test parsing of sdkconfig file."""
        sdk = sdkconfig_c(self.sdkconfig_path)
        
        self.assertIn('CONFIG_FREERTOS_PLACE_FUNCTIONS_INTO_FLASH', sdk.config)
        self.assertEqual(sdk.config['CONFIG_FREERTOS_PLACE_FUNCTIONS_INTO_FLASH'], 'y')
        self.assertIn('CONFIG_ESP32_DEFAULT_CPU_FREQ_240', sdk.config)
    
    def test_index_method(self):
        """Test index method for retrieving config values."""
        sdk = sdkconfig_c(self.sdkconfig_path)
        
        self.assertEqual(sdk.index('CONFIG_FREERTOS_PLACE_FUNCTIONS_INTO_FLASH'), 'y')
    
    def test_check_simple_present(self):
        """Test check method with simple present config."""
        sdk = sdkconfig_c(self.sdkconfig_path)
        
        self.assertTrue(sdk.check('CONFIG_FREERTOS_PLACE_FUNCTIONS_INTO_FLASH'))
    
    def test_check_simple_missing(self):
        """Test check method with simple missing config."""
        sdk = sdkconfig_c(self.sdkconfig_path)
        
        self.assertFalse(sdk.check('CONFIG_NONEXISTENT'))
    
    def test_check_negation_present(self):
        """Test check method with negated present config."""
        sdk = sdkconfig_c(self.sdkconfig_path)
        
        self.assertFalse(sdk.check('!CONFIG_FREERTOS_PLACE_FUNCTIONS_INTO_FLASH'))
    
    def test_check_negation_missing(self):
        """Test check method with negated missing config."""
        sdk = sdkconfig_c(self.sdkconfig_path)
        
        self.assertTrue(sdk.check('!CONFIG_NONEXISTENT'))
    
    def test_check_and_both_present(self):
        """Test check method with AND of two present configs."""
        sdk = sdkconfig_c(self.sdkconfig_path)
        
        self.assertTrue(sdk.check('CONFIG_FREERTOS_PLACE_FUNCTIONS_INTO_FLASH&&CONFIG_ESP32_DEFAULT_CPU_FREQ_240'))
    
    def test_check_and_one_missing(self):
        """Test check method with AND where one is missing."""
        sdk = sdkconfig_c(self.sdkconfig_path)
        
        self.assertFalse(sdk.check('CONFIG_FREERTOS_PLACE_FUNCTIONS_INTO_FLASH&&CONFIG_NONEXISTENT'))
    
    def test_check_empty_string(self):
        """Test check method with empty string."""
        sdk = sdkconfig_c(self.sdkconfig_path)
        
        self.assertTrue(sdk.check(''))
    
    def test_check_malformed_negation(self):
        """Test check method with malformed negation (bare !)."""
        sdk = sdkconfig_c(self.sdkconfig_path)
        
        self.assertFalse(sdk.check('!'))
        self.assertFalse(sdk.check('CONFIG_A&&!'))
        self.assertFalse(sdk.check('!&&CONFIG_A'))
    
    def test_check_with_spaces(self):
        """Test check method handles spaces correctly."""
        sdk = sdkconfig_c(self.sdkconfig_path)
        
        self.assertTrue(sdk.check('CONFIG_FREERTOS_PLACE_FUNCTIONS_INTO_FLASH && CONFIG_ESP32_DEFAULT_CPU_FREQ_240'))


class TestPathsC(unittest.TestCase):
    """Test paths_c class for path management."""
    
    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.build_dir = os.path.join(self.temp_dir, 'build')
        os.makedirs(self.build_dir)
    
    def tearDown(self):
        """Clean up temporary files."""
        import shutil
        shutil.rmtree(self.temp_dir)
    
    def test_append_relative_path(self):
        """Test appending relative paths."""
        paths = paths_c(self.build_dir)
        paths.append('libtest.a', '*', './esp-idf/test/libtest.a')
        
        result = paths.index('libtest.a', '*')
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 1)
        self.assertTrue(os.path.isabs(result[0]))
        self.assertIn(os.path.normpath('esp-idf/test/libtest.a'), os.path.normpath(result[0]))
    
    def test_append_absolute_path(self):
        """Test appending absolute paths."""
        paths = paths_c(self.build_dir)
        abs_path = '/absolute/path/libtest.a'
        paths.append('libtest.a', '*', abs_path)
        
        result = paths.index('libtest.a', '*')
        self.assertIsNotNone(result)
        self.assertEqual(result[0], abs_path)
    
    def test_append_idf_path(self):
        """Test appending paths with $IDF_PATH."""
        original_idf = os.environ.get('IDF_PATH')
        os.environ['IDF_PATH'] = '/path/to/esp-idf'
        self.addCleanup(lambda: os.environ.update({'IDF_PATH': original_idf}) if original_idf else os.environ.pop('IDF_PATH', None))
        
        paths = paths_c(self.build_dir)
        paths.append('libtest.a', '*', '$IDF_PATH/components/test/libtest.a')
        
        result = paths.index('libtest.a', '*')
        self.assertIsNotNone(result)
        expected = os.path.normpath('/path/to/esp-idf/components/test/libtest.a')
        self.assertEqual(os.path.normpath(result[0]), expected)
    
    def test_append_idf_path_not_set(self):
        """Test appending paths with $IDF_PATH when not set."""
        # Save and remove IDF_PATH if set
        original_idf = os.environ.get('IDF_PATH')
        if original_idf is not None:
            del os.environ['IDF_PATH']
        self.addCleanup(lambda: os.environ.update({'IDF_PATH': original_idf}) if original_idf else None)
        
        paths = paths_c(self.build_dir)
        
        with self.assertRaises(RuntimeError) as context:
            paths.append('libtest.a', '*', '$IDF_PATH/components/test/libtest.a')
        
        self.assertIn('IDF_PATH', str(context.exception))
        self.assertIn('not set', str(context.exception))
    
    def test_index_wildcard(self):
        """Test index method with wildcard object."""
        paths = paths_c(self.build_dir)
        paths.append('libtest.a', '*', './libtest.a')
        
        result = paths.index('libtest.a', '*')
        self.assertIsNotNone(result)
    
    def test_index_missing_library(self):
        """Test index method with missing library."""
        paths = paths_c(self.build_dir)
        
        result = paths.index('nonexistent.a', '*')
        self.assertIsNone(result)
    
    def test_index_missing_object(self):
        """Test index method with missing object."""
        paths = paths_c(self.build_dir)
        paths.append('libtest.a', 'obj1.obj', './obj1.obj')
        
        result = paths.index('libtest.a', 'obj2.obj')
        self.assertIsNone(result)


class TestObjectC(unittest.TestCase):
    """Test object_c class for object file handling."""
    
    def test_append_returns_false_on_missing_section(self):
        """Test that append returns False when section is not found."""
        # Mock read_dump_info to return non-empty list so self.dumps is truthy
        # This forces the code to reach the "missing section" branch
        with mock.patch.object(object_c, 'read_dump_info', return_value=[['mock dump data']]), \
             mock.patch.object(object_c, 'get_func_section', return_value=None):
            obj = object_c('test.c.obj', [], 'libtest.a')
            result = obj.append('nonexistent_function')
        self.assertFalse(result)


class TestLibraryC(unittest.TestCase):
    """Test library_c class for library management."""
    
    def test_init(self):
        """Test library initialization."""
        lib = library_c('libtest.a', '/path/to/libtest.a')
        
        self.assertEqual(lib.name, 'libtest.a')
        self.assertEqual(lib.path, '/path/to/libtest.a')
        self.assertEqual(len(lib.objs), 0)
    
    def test_append_creates_object(self):
        """Test that append creates object if it doesn't exist."""
        lib = library_c('libtest.a', '/path/to/libtest.a')
        
        # Create a mock object with non-empty dumps
        obj_name = 'test.c.obj'
        obj_paths = []
        func_name = 'test_function'
        
        # Mock read_dump_info to return non-empty list (simulating successful objdump)
        mock_dumps = [['mock dump line']]
        
        with mock.patch.object(object_c, 'read_dump_info', return_value=mock_dumps), \
             mock.patch.object(object_c, 'get_func_section', return_value='test_section'):
            lib.append(obj_name, obj_paths, func_name)

        self.assertIn(obj_name, lib.objs)
        self.assertEqual(lib.objs[obj_name].funcs[func_name], 'test_section')


class TestLibrariesC(unittest.TestCase):
    """Test libraries_c class for library collection."""
    
    def test_init(self):
        """Test libraries initialization."""
        libs = libraries_c()
        
        self.assertEqual(len(libs.libs), 0)


class TestPathNormalization(unittest.TestCase):
    """Test path normalization edge cases."""
    
    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.build_dir = os.path.join(self.temp_dir, 'build')
        os.makedirs(self.build_dir)
    
    def tearDown(self):
        """Clean up temporary files."""
        import shutil
        shutil.rmtree(self.temp_dir)
    
    def test_normalize_dot_slash_prefix(self):
        """Test normalization of paths with ./ prefix."""
        paths = paths_c(self.build_dir)
        paths.append('lib.a', '*', './esp-idf/lib.a')
        
        result = paths.index('lib.a', '*')
        self.assertTrue(os.path.isabs(result[0]))
    
    def test_normalize_no_prefix(self):
        """Test normalization of paths without prefix."""
        paths = paths_c(self.build_dir)
        paths.append('lib.a', '*', 'esp-idf/lib.a')
        
        result = paths.index('lib.a', '*')
        self.assertTrue(os.path.isabs(result[0]))
    
    def test_normalize_multiple_dots(self):
        """Test normalization of paths with multiple dots."""
        paths = paths_c(self.build_dir)
        paths.append('lib.a', '*', './my.file.c.obj')
        
        result = paths.index('lib.a', '*')
        self.assertIn('my.file.c.obj', result[0])


if __name__ == '__main__':
    unittest.main()
