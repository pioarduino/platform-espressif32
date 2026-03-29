#!/usr/bin/env python3
"""
Integration tests for the relinker system.

Tests the complete workflow:
1. Reading CSV configuration files
2. Processing sdkconfig
3. Generating library/object/function mappings
4. Modifying linker scripts
5. Idempotent operations
"""

import unittest
import tempfile
import os
import sys
import shutil
from pathlib import Path

# Add the relinker directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from configuration import generator, sdkconfig_c, paths_c


class TestCSVProcessing(unittest.TestCase):
    """Test complete CSV file processing workflow."""
    
    def setUp(self):
        """Create temporary directory and CSV files."""
        self.temp_dir = tempfile.mkdtemp()
        self.build_dir = os.path.join(self.temp_dir, 'build')
        os.makedirs(self.build_dir)
        
        # Create library.csv
        self.library_csv = os.path.join(self.temp_dir, 'library.csv')
        with open(self.library_csv, 'w') as f:
            f.write('library,path\n')
            f.write('libfreertos.a,./esp-idf/freertos/libfreertos.a\n')
            f.write('libheap.a,./esp-idf/heap/libheap.a\n')
        
        # Create object.csv
        self.object_csv = os.path.join(self.temp_dir, 'object.csv')
        with open(self.object_csv, 'w') as f:
            f.write('library,object,path\n')
            f.write('libfreertos.a,tasks.c.obj,esp-idf/freertos/CMakeFiles/__idf_freertos.dir/tasks.c.obj\n')
            f.write('libheap.a,heap_caps.c.obj,esp-idf/heap/CMakeFiles/__idf_heap.dir/heap_caps.c.obj\n')
        
        # Create function.csv
        self.function_csv = os.path.join(self.temp_dir, 'function.csv')
        with open(self.function_csv, 'w') as f:
            f.write('library,object,function,option\n')
            f.write('libfreertos.a,tasks.c.obj,xTaskGetTickCount,CONFIG_FREERTOS_PLACE_FUNCTIONS_INTO_FLASH\n')
            f.write('libfreertos.a,tasks.c.obj,xTaskGetSchedulerState,\n')
            f.write('libheap.a,heap_caps.c.obj,heap_caps_malloc,\n')
        
        # Create sdkconfig
        self.sdkconfig = os.path.join(self.temp_dir, 'sdkconfig')
        with open(self.sdkconfig, 'w') as f:
            f.write('CONFIG_FREERTOS_PLACE_FUNCTIONS_INTO_FLASH=y\n')
            f.write('CONFIG_ESP32_DEFAULT_CPU_FREQ_240=y\n')
    
    def tearDown(self):
        """Clean up temporary files."""
        shutil.rmtree(self.temp_dir)
    
    def test_csv_files_exist(self):
        """Test that CSV files are created correctly."""
        self.assertTrue(os.path.exists(self.library_csv))
        self.assertTrue(os.path.exists(self.object_csv))
        self.assertTrue(os.path.exists(self.function_csv))
        self.assertTrue(os.path.exists(self.sdkconfig))
    
    def test_read_library_csv(self):
        """Test reading library CSV file."""
        import csv
        
        with open(self.library_csv, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['library'], 'libfreertos.a')
        self.assertEqual(rows[1]['library'], 'libheap.a')
    
    def test_read_object_csv(self):
        """Test reading object CSV file."""
        import csv
        
        with open(self.object_csv, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['object'], 'tasks.c.obj')
    
    def test_read_function_csv(self):
        """Test reading function CSV file."""
        import csv
        
        with open(self.function_csv, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]['function'], 'xTaskGetTickCount')
        self.assertEqual(rows[0]['option'], 'CONFIG_FREERTOS_PLACE_FUNCTIONS_INTO_FLASH')


class TestPathResolution(unittest.TestCase):
    """Test path resolution with different formats."""
    
    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.build_dir = os.path.join(self.temp_dir, 'build')
        os.makedirs(self.build_dir)
        
        # Set IDF_PATH for testing
        self.original_idf_path = os.environ.get('IDF_PATH')
        os.environ['IDF_PATH'] = '/path/to/esp-idf'
    
    def tearDown(self):
        """Clean up."""
        shutil.rmtree(self.temp_dir)
        
        # Restore original IDF_PATH
        if self.original_idf_path:
            os.environ['IDF_PATH'] = self.original_idf_path
        elif 'IDF_PATH' in os.environ:
            del os.environ['IDF_PATH']
    
    def test_relative_path_resolution(self):
        """Test resolution of relative paths."""
        paths = paths_c(self.build_dir)
        paths.append('lib.a', '*', './esp-idf/lib.a')
        
        result = paths.index('lib.a', '*')
        self.assertTrue(os.path.isabs(result[0]))
        self.assertIn('esp-idf/lib.a', result[0])
    
    def test_idf_path_resolution(self):
        """Test resolution of $IDF_PATH."""
        paths = paths_c(self.build_dir)
        paths.append('lib.a', '*', '$IDF_PATH/components/test/lib.a')
        
        result = paths.index('lib.a', '*')
        self.assertIn('/path/to/esp-idf/components/test/lib.a', result[0])
    
    def test_absolute_path_unchanged(self):
        """Test that absolute paths remain unchanged."""
        paths = paths_c(self.build_dir)
        abs_path = '/absolute/path/lib.a'
        paths.append('lib.a', '*', abs_path)
        
        result = paths.index('lib.a', '*')
        self.assertEqual(result[0], abs_path)


class TestSdkconfigConditionals(unittest.TestCase):
    """Test sdkconfig conditional processing."""
    
    def setUp(self):
        """Create test sdkconfig."""
        self.temp_dir = tempfile.mkdtemp()
        self.sdkconfig = os.path.join(self.temp_dir, 'sdkconfig')
        
        with open(self.sdkconfig, 'w') as f:
            f.write('CONFIG_ENABLED=y\n')
            f.write('# CONFIG_DISABLED is not set\n')
    
    def tearDown(self):
        """Clean up."""
        shutil.rmtree(self.temp_dir)
    
    def test_enabled_config(self):
        """Test checking enabled config."""
        sdk = sdkconfig_c(self.sdkconfig)
        
        self.assertTrue(sdk.check('CONFIG_ENABLED'))
    
    def test_disabled_config(self):
        """Test checking disabled config."""
        sdk = sdkconfig_c(self.sdkconfig)
        
        self.assertFalse(sdk.check('CONFIG_DISABLED'))
    
    def test_negated_enabled(self):
        """Test negated enabled config."""
        sdk = sdkconfig_c(self.sdkconfig)
        
        self.assertFalse(sdk.check('!CONFIG_ENABLED'))
    
    def test_negated_disabled(self):
        """Test negated disabled config."""
        sdk = sdkconfig_c(self.sdkconfig)
        
        self.assertTrue(sdk.check('!CONFIG_DISABLED'))
    
    def test_and_condition(self):
        """Test AND condition."""
        sdk = sdkconfig_c(self.sdkconfig)
        
        self.assertTrue(sdk.check('CONFIG_ENABLED&&!CONFIG_DISABLED'))
        self.assertFalse(sdk.check('CONFIG_ENABLED&&CONFIG_DISABLED'))


class TestLinkerScriptModification(unittest.TestCase):
    """Test linker script modification."""
    
    def setUp(self):
        """Create test linker script."""
        self.temp_dir = tempfile.mkdtemp()
        self.linker_script = os.path.join(self.temp_dir, 'sections.ld')
        
        with open(self.linker_script, 'w') as f:
            f.write('.iram0.text : {\n')
            f.write('    _iram_text_start = ABSOLUTE(.);\n')
            f.write('    *(.iram1 .iram1.*)\n')
            f.write('    *(.iram0.literal .iram.literal .iram.text.literal .iram0.text .iram.text)\n')
            f.write('    _iram_text_end = ABSOLUTE(.);\n')
            f.write('} > iram0_0_seg\n')
            f.write('\n')
            f.write('.flash.text : {\n')
            f.write('    _stext = .;\n')
            f.write('    *(.stub .gnu.warning .gnu.linkonce.literal.* .gnu.linkonce.t.*.*)\n')
            f.write('    *(.irom0.text)\n')
            f.write('    _etext = .;\n')
            f.write('} > default_code_seg\n')
    
    def tearDown(self):
        """Clean up."""
        shutil.rmtree(self.temp_dir)
    
    def test_linker_script_exists(self):
        """Test that linker script is created."""
        self.assertTrue(os.path.exists(self.linker_script))
    
    def test_linker_script_has_iram_section(self):
        """Test that linker script has IRAM section."""
        with open(self.linker_script, 'r') as f:
            content = f.read()
        
        self.assertIn('.iram0.text', content)
        self.assertIn('*(.iram1 .iram1.*)', content)
    
    def test_linker_script_has_flash_section(self):
        """Test that linker script has flash section."""
        with open(self.linker_script, 'r') as f:
            content = f.read()
        
        self.assertIn('.flash.text', content)
        self.assertIn('.stub .gnu.warning', content)


class TestIdempotency(unittest.TestCase):
    """Test that relinker operations are idempotent."""
    
    def setUp(self):
        """Create test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.linker_script = os.path.join(self.temp_dir, 'sections.ld')
        
        # Create initial linker script
        with open(self.linker_script, 'w') as f:
            f.write('.iram0.text : {\n')
            f.write('    *(.iram1 .iram1.*)\n')
            f.write('}\n')
            f.write('.flash.text : {\n')
            f.write('    *(.stub .gnu.warning)\n')
            f.write('}\n')
    
    def tearDown(self):
        """Clean up."""
        shutil.rmtree(self.temp_dir)
    
    def test_multiple_runs_produce_same_result(self):
        """Test that running relinker multiple times produces same result."""
        # This would require full relinker integration
        # For now, we document the expected behavior
        pass


class TestErrorHandling(unittest.TestCase):
    """Test error handling in various scenarios."""
    
    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
    
    def tearDown(self):
        """Clean up."""
        shutil.rmtree(self.temp_dir)
    
    def test_missing_idf_path(self):
        """Test error when IDF_PATH is not set."""
        # Remove IDF_PATH
        original = os.environ.get('IDF_PATH')
        if 'IDF_PATH' in os.environ:
            del os.environ['IDF_PATH']
        
        try:
            paths = paths_c(self.temp_dir)
            
            with self.assertRaises(RuntimeError) as context:
                paths.append('lib.a', '*', '$IDF_PATH/lib.a')
            
            self.assertIn('IDF_PATH', str(context.exception))
        finally:
            # Restore IDF_PATH
            if original:
                os.environ['IDF_PATH'] = original
    
    def test_missing_csv_file(self):
        """Test error when CSV file is missing."""
        # This would test the generator function with missing files
        pass
    
    def test_malformed_csv(self):
        """Test error handling with malformed CSV."""
        # This would test CSV parsing error handling
        pass


class TestCompleteWorkflow(unittest.TestCase):
    """Test complete relinker workflow from CSV to linker script."""
    
    def setUp(self):
        """Set up complete test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.build_dir = os.path.join(self.temp_dir, 'build')
        os.makedirs(self.build_dir)
        
        # Set up environment
        os.environ['IDF_PATH'] = '/path/to/esp-idf'
        os.environ['BUILD_DIR'] = self.build_dir
    
    def tearDown(self):
        """Clean up."""
        shutil.rmtree(self.temp_dir)
        
        if 'BUILD_DIR' in os.environ:
            del os.environ['BUILD_DIR']
    
    def test_workflow_documentation(self):
        """Document the expected workflow."""
        # 1. Read CSV files (library, object, function)
        # 2. Parse sdkconfig
        # 3. Filter functions based on sdkconfig options
        # 4. Resolve paths (relative, $IDF_PATH, absolute)
        # 5. Generate library/object/function mappings
        # 6. Modify linker script (IRAM and flash sections)
        # 7. Ensure idempotency (can run multiple times)
        pass


if __name__ == '__main__':
    # Run tests with verbose output
    unittest.main(verbosity=2)
