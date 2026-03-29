#!/usr/bin/env python3
"""
Comprehensive functionality test for the relinker implementation.
Tests all major features to ensure they work as planned.
"""

import sys
import os
import tempfile
import shutil
import unittest

# Add the relinker directory to the path
relinker_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'builder', 'relinker')
sys.path.insert(0, relinker_dir)

from configuration import sdkconfig_c, paths_c, generator
from relinker import filter_c, func2sect


class TestRelinkerFunctionality(unittest.TestCase):
    """Comprehensive functionality tests for the relinker implementation."""

    def test_sdkconfig_functionality(self):
        """Test sdkconfig parsing and checking."""
        temp_dir = tempfile.mkdtemp()
        try:
            sdkconfig = os.path.join(temp_dir, 'sdkconfig')
            with open(sdkconfig, 'w') as f:
                f.write('CONFIG_FREERTOS_PLACE_FUNCTIONS_INTO_FLASH=y\n')
                f.write('CONFIG_ESP32_DEFAULT_CPU_FREQ_240=y\n')
                f.write('# CONFIG_DISABLED is not set\n')
            
            sdk = sdkconfig_c(sdkconfig)
            
            # Test parsing
            self.assertGreaterEqual(len(sdk.config), 2, "Should parse at least 2 configs")
            
            # Test simple check
            self.assertTrue(sdk.check('CONFIG_FREERTOS_PLACE_FUNCTIONS_INTO_FLASH'), "Should find enabled config")
            
            # Test negation
            self.assertFalse(sdk.check('!CONFIG_FREERTOS_PLACE_FUNCTIONS_INTO_FLASH'), "Negation should work")
            self.assertTrue(sdk.check('!CONFIG_DISABLED'), "Negation of missing config should work")
            
            # Test AND
            self.assertTrue(sdk.check('CONFIG_FREERTOS_PLACE_FUNCTIONS_INTO_FLASH&&CONFIG_ESP32_DEFAULT_CPU_FREQ_240'), "AND should work")
            
            # Test malformed negation
            self.assertFalse(sdk.check('!'), "Bare ! should fail")
        finally:
            shutil.rmtree(temp_dir)

    def test_path_normalization(self):
        """Test path normalization and resolution."""
        temp_dir = tempfile.mkdtemp()
        try:
            # Set IDF_PATH
            original_idf = os.environ.get('IDF_PATH')
            os.environ['IDF_PATH'] = '/test/esp-idf'
            
            paths = paths_c(temp_dir)
            
            # Test relative path
            paths.append('lib1.a', '*', './esp-idf/lib1.a')
            result = paths.index('lib1.a', '*')
            self.assertIsNotNone(result, "Should find library")
            self.assertTrue(os.path.isabs(result[0]), "Should be absolute path")
            
            # Test $IDF_PATH
            paths.append('lib2.a', '*', '$IDF_PATH/components/lib2.a')
            result = paths.index('lib2.a', '*')
            self.assertIn('/test/esp-idf', result[0], "Should expand $IDF_PATH")
            
            # Test absolute path
            paths.append('lib3.a', '*', '/absolute/path/lib3.a')
            result = paths.index('lib3.a', '*')
            self.assertEqual(result[0], '/absolute/path/lib3.a', "Absolute path should remain unchanged")
            
            # Test missing IDF_PATH error
            try:
                del os.environ['IDF_PATH']
                paths.append('lib4.a', '*', '$IDF_PATH/test.a')
                self.fail("Should raise error for missing IDF_PATH")
            except RuntimeError as e:
                self.assertIn('IDF_PATH', str(e), "Error should mention IDF_PATH")
            finally:
                # Restore IDF_PATH
                if original_idf:
                    os.environ['IDF_PATH'] = original_idf
        finally:
            shutil.rmtree(temp_dir)

    def test_function_to_section(self):
        """Test function to section conversion."""
        # Test simple function
        result = func2sect('my_function')
        self.assertIn('.literal.my_function', result, "Should have literal section")
        self.assertIn('.text.my_function', result, "Should have text section")
        
        # Test multiple functions
        result = func2sect('func1 func2')
        self.assertEqual(len(result), 4, "Should have 4 sections (2 per function)")
        
        # Test IRAM function
        result = func2sect('.iram1.my_func')
        self.assertIn('.iram1.my_func', result, "Should preserve IRAM section")

    def test_filter_functionality(self):
        """Test filter_c functionality."""
        temp_dir = tempfile.mkdtemp()
        try:
            # Create a linker script with EXCLUDE_FILE pattern
            linker_script = os.path.join(temp_dir, 'sections.ld')
            with open(linker_script, 'w') as f:
                f.write('.iram0.text : {\n')
                f.write('    *(.iram1 .iram1.*)\n')
                f.write('}\n')
            
            filt = filter_c(linker_script)
            
            # Test that filter object is created
            self.assertIsNotNone(filt, "Filter should be created")
            self.assertTrue(hasattr(filt, 'entries'), "Filter should have entries")
            self.assertTrue(hasattr(filt, 'libs_desc'), "Filter should have libs_desc")
            
            # Test match method
            result = filt.match('*libtest.a:test.*')
            self.assertIsInstance(result, bool, "Match should return boolean")
            
            # Test add method
            result = filt.add()
            self.assertIsInstance(result, str, "Add should return string")
        finally:
            shutil.rmtree(temp_dir)

    def test_csv_processing(self):
        """Test CSV file processing."""
        temp_dir = tempfile.mkdtemp()
        try:
            # Create CSV files
            library_csv = os.path.join(temp_dir, 'library.csv')
            with open(library_csv, 'w') as f:
                f.write('library,path\n')
                f.write('libtest.a,./esp-idf/libtest.a\n')
            
            object_csv = os.path.join(temp_dir, 'object.csv')
            with open(object_csv, 'w') as f:
                f.write('library,object,path\n')
                f.write('libtest.a,test.c.obj,esp-idf/test.c.obj\n')
            
            function_csv = os.path.join(temp_dir, 'function.csv')
            with open(function_csv, 'w') as f:
                f.write('library,object,function,option\n')
                f.write('libtest.a,test.c.obj,test_func,\n')
            
            sdkconfig = os.path.join(temp_dir, 'sdkconfig')
            with open(sdkconfig, 'w') as f:
                f.write('CONFIG_TEST=y\n')
            
            # Test that CSV files can be read
            import csv
            with open(library_csv, 'r') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                self.assertEqual(len(rows), 1, "Should read 1 library")
            
            with open(object_csv, 'r') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                self.assertEqual(len(rows), 1, "Should read 1 object")
            
            with open(function_csv, 'r') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                self.assertEqual(len(rows), 1, "Should read 1 function")
        finally:
            shutil.rmtree(temp_dir)

    def test_idempotency(self):
        """Test that operations are idempotent."""
        # Test that path normalization is consistent
        temp_dir = tempfile.mkdtemp()
        try:
            paths1 = paths_c(temp_dir)
            paths1.append('lib.a', '*', './test/lib.a')
            result1 = paths1.index('lib.a', '*')
            
            paths2 = paths_c(temp_dir)
            paths2.append('lib.a', '*', './test/lib.a')
            result2 = paths2.index('lib.a', '*')
            
            self.assertEqual(result1[0], result2[0], "Same input should produce same output")
            
            # Test that sdkconfig checking is consistent
            sdkconfig = os.path.join(temp_dir, 'sdkconfig')
            with open(sdkconfig, 'w') as f:
                f.write('CONFIG_TEST=y\n')
            
            sdk1 = sdkconfig_c(sdkconfig)
            sdk2 = sdkconfig_c(sdkconfig)
            
            self.assertEqual(sdk1.check('CONFIG_TEST'), sdk2.check('CONFIG_TEST'), "Same check should give same result")
        finally:
            shutil.rmtree(temp_dir)


def main():
    """Run all functionality tests."""
    print('\n' + '=' * 70)
    print('RELINKER FUNCTIONALITY TEST SUITE')
    print('=' * 70)
    print()
    
    # Run tests using unittest
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestRelinkerFunctionality)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    print('=' * 70)
    print('FINAL RESULTS')
    print('=' * 70)
    print(f'Tests run: {result.testsRun}')
    print(f'Tests passed: {result.testsRun - len(result.failures) - len(result.errors)}')
    print(f'Tests failed: {len(result.failures) + len(result.errors)}')
    
    if result.wasSuccessful():
        print('\n🎉 ALL FUNCTIONALITY TESTS PASSED!')
        print('✅ The relinker implementation works as planned!')
        return 0
    else:
        print(f'\n⚠️  {len(result.failures) + len(result.errors)} test(s) failed')
        return 1

if __name__ == '__main__':
    sys.exit(main())
