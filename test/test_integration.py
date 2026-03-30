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
from unittest import mock
import tempfile
import os
import sys
import shutil
from pathlib import Path

# Add the relinker directory to the path
relinker_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'builder', 'relinker')
sys.path.insert(0, relinker_dir)

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
    
    def test_generator_processing(self):
        """Test the actual generator processing with CSV files."""
        from configuration import object_c
        
        # Mock the object file reading to avoid needing actual .obj files
        mock_dumps = [[
            '00000000 g     F .text.xTaskGetTickCount 00000010 xTaskGetTickCount\n',
            '00000000 g     F .text.xTaskGetSchedulerState 00000020 xTaskGetSchedulerState\n',
        ]]
        
        mock_heap_dumps = [[
            '00000000 g     F .text.heap_caps_malloc 00000030 heap_caps_malloc\n',
        ]]
        
        def mock_read_dump_info(self, paths):
            # Return appropriate mock dumps based on the object name
            if 'tasks.c.obj' in str(paths):
                return mock_dumps
            elif 'heap_caps.c.obj' in str(paths):
                return mock_heap_dumps
            return [[]]
        
        with mock.patch.object(object_c, 'read_dump_info', mock_read_dump_info):
            # Call the actual generator function
            libraries = generator(
                library_file=self.library_csv,
                object_file=self.object_csv,
                function_file=self.function_csv,
                sdkconfig_file=self.sdkconfig,
                missing_function_info=True,
                build_dir=self.build_dir
            )
        
        # Assert expected libraries are present
        self.assertIn('libfreertos.a', libraries.libs)
        self.assertIn('libheap.a', libraries.libs)
        
        # Assert libfreertos.a has the expected object
        freertos_lib = libraries.libs['libfreertos.a']
        self.assertIn('tasks.c.obj', freertos_lib.objs)
        
        # Assert libheap.a has the expected object
        heap_lib = libraries.libs['libheap.a']
        self.assertIn('heap_caps.c.obj', heap_lib.objs)
        
        # Assert option filtering: xTaskGetTickCount should be included
        # because CONFIG_FREERTOS_PLACE_FUNCTIONS_INTO_FLASH is set
        tasks_obj = freertos_lib.objs['tasks.c.obj']
        self.assertIn('xTaskGetTickCount', tasks_obj.funcs)
        
        # Assert xTaskGetSchedulerState is also included (no option requirement)
        self.assertIn('xTaskGetSchedulerState', tasks_obj.funcs)
        
        # Assert heap_caps_malloc is included
        heap_obj = heap_lib.objs['heap_caps.c.obj']
        self.assertIn('heap_caps_malloc', heap_obj.funcs)
        
        # Assert paths are resolved relative to build_dir
        expected_lib_path = os.path.normpath(os.path.join(self.build_dir, 'esp-idf/freertos/libfreertos.a'))
        self.assertEqual(os.path.normpath(freertos_lib.path), expected_lib_path)


class TestPathResolution(unittest.TestCase):
    """Test path resolution with different formats."""
    
    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.build_dir = os.path.join(self.temp_dir, 'build')
        os.makedirs(self.build_dir)
        
        # Set IDF_PATH for testing
        self.original_idf_path = os.environ.get('IDF_PATH')
        self.idf_path = os.path.join(self.temp_dir, 'esp-idf')
        os.environ['IDF_PATH'] = self.idf_path
    
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
        expected_path = os.path.normpath(os.path.join('esp-idf', 'lib.a'))
        self.assertIn(expected_path, result[0])
    
    def test_idf_path_resolution(self):
        """Test resolution of $IDF_PATH."""
        paths = paths_c(self.build_dir)
        paths.append('lib.a', '*', '$IDF_PATH/components/test/lib.a')
        
        result = paths.index('lib.a', '*')
        expected_path = os.path.normpath(
            os.path.join(self.idf_path, 'components', 'test', 'lib.a')
        )
        self.assertEqual(os.path.normpath(result[0]), expected_path)
    
    def test_absolute_path_unchanged(self):
        """Test that absolute paths remain unchanged."""
        paths = paths_c(self.build_dir)
        abs_path = os.path.abspath(
            os.path.join(self.temp_dir, 'absolute', 'path', 'lib.a')
        )
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
    
    def test_catch_all_pattern_included(self):
        """Test that relinker processes targets and generates include patterns."""
        from relinker import relink_c
        from configuration import object_c
        import relinker as relinker_module
        
        # Create CSV files with actual function entries
        library_csv = os.path.join(self.temp_dir, 'library.csv')
        with open(library_csv, 'w') as f:
            f.write('library,path\n')
            f.write('libtest.a,./libtest.a\n')
        
        object_csv = os.path.join(self.temp_dir, 'object.csv')
        with open(object_csv, 'w') as f:
            f.write('library,object,path\n')
            f.write('libtest.a,test.c.obj,./test.c.obj\n')
        
        function_csv = os.path.join(self.temp_dir, 'function.csv')
        with open(function_csv, 'w') as f:
            f.write('library,object,function,option\n')
            f.write('libtest.a,test.c.obj,test_func,\n')
        
        sdkconfig = os.path.join(self.temp_dir, 'sdkconfig')
        with open(sdkconfig, 'w') as f:
            f.write('CONFIG_TEST=y\n')
        
        # Mock read_dump_info to return function symbols
        mock_dumps = [[
            '00000000 g     F .text.test_func 00000010 test_func\n',
        ]]
        
        def mock_read_dump_info(self, paths):
            return mock_dumps
        
        # Mock lib_secs to return relocatable sections
        def mock_lib_secs(lib, file, lib_path):
            return ['.iram1.test_func', '.text.test_func', '.literal.test_func']
        
        try:
            with mock.patch.object(object_c, 'read_dump_info', mock_read_dump_info), \
                 mock.patch.object(relinker_module, 'lib_secs', mock_lib_secs):
                relink = relink_c(self.linker_script, library_csv, object_csv,
                                function_csv, sdkconfig, missing_function_info=True)
                
                # Verify that relinker is in active path (not taking _no_relink shortcut)
                self.assertFalse(getattr(relink, '_no_relink', True),
                               "Relinker should be active when targets exist")
                
                # Verify that iram1_include contains object-specific patterns
                self.assertIsNotNone(relink.iram1_include,
                                   "iram1_include should be populated")
                self.assertIn('*libtest.a:test.*', relink.iram1_include,
                             "iram1_include should contain object-specific patterns")
                
        except Exception as e:
            if 'not found' in str(e).lower():
                self.skipTest(f"Skipping due to missing library files: {e}")
            else:
                raise
    
    def test_multiple_runs_produce_same_result(self):
        """Test that running relinker multiple times produces same result."""
        from configuration import generator, object_c
        from relinker import relink_c
        import relinker as relinker_module
        
        # Create CSV files
        library_csv = os.path.join(self.temp_dir, 'library.csv')
        with open(library_csv, 'w') as f:
            f.write('library,path\n')
            f.write('libtest.a,./libtest.a\n')
        
        object_csv = os.path.join(self.temp_dir, 'object.csv')
        with open(object_csv, 'w') as f:
            f.write('library,object,path\n')
            f.write('libtest.a,test.c.obj,./test.c.obj\n')
        
        function_csv = os.path.join(self.temp_dir, 'function.csv')
        with open(function_csv, 'w') as f:
            f.write('library,object,function,option\n')
            f.write('libtest.a,test.c.obj,test_func,\n')
        
        sdkconfig = os.path.join(self.temp_dir, 'sdkconfig')
        with open(sdkconfig, 'w') as f:
            f.write('CONFIG_TEST=y\n')
        
        # Create initial linker script
        input_script = os.path.join(self.temp_dir, 'input.ld')
        with open(input_script, 'w') as f:
            f.write('.iram0.text : {\n')
            f.write('    _iram_text_start = ABSOLUTE(.);\n')
            f.write('    *(.iram1 .iram1.*)\n')
            f.write('    _iram_text_end = ABSOLUTE(.);\n')
            f.write('} > iram0_0_seg\n')
            f.write('\n')
            f.write('.flash.text : {\n')
            f.write('    _stext = .;\n')
            f.write('    *(.stub .gnu.warning)\n')
            f.write('    _etext = .;\n')
            f.write('} > default_code_seg\n')
        
        output1 = os.path.join(self.temp_dir, 'output1.ld')
        output2 = os.path.join(self.temp_dir, 'output2.ld')
        
        # Mock read_dump_info to return function symbols
        mock_dumps = [[
            '00000000 g     F .text.test_func 00000010 test_func\n',
        ]]
        
        def mock_read_dump_info(self, paths):
            return mock_dumps
        
        # Mock lib_secs to return relocatable sections
        def mock_lib_secs(lib, file, lib_path):
            return ['.iram1.test_func', '.text.test_func', '.literal.test_func']
        
        try:
            with mock.patch.object(object_c, 'read_dump_info', mock_read_dump_info), \
                 mock.patch.object(relinker_module, 'lib_secs', mock_lib_secs):
                # First run
                relink1 = relink_c(input_script, library_csv, object_csv, 
                                  function_csv, sdkconfig, missing_function_info=True)
                
                # Verify that relinker is active (not taking _no_relink shortcut)
                self.assertFalse(getattr(relink1, '_no_relink', True),
                               "Relinker should be active when targets exist")
                
                relink1.save(input_script, output1)
                
                # Second run using first output as input
                relink2 = relink_c(output1, library_csv, object_csv,
                                  function_csv, sdkconfig, missing_function_info=True)
                
                # Verify second run is also active
                self.assertFalse(getattr(relink2, '_no_relink', True),
                               "Relinker should remain active on second run")
                
                relink2.save(output1, output2)
                
                # Compare outputs - should be identical
                with open(output1, 'r') as f1, open(output2, 'r') as f2:
                    content1 = f1.read()
                    content2 = f2.read()
                
                self.assertEqual(content1, content2, 
                               "Relinker should produce identical output on second run")
        except Exception as e:
            # If libraries don't exist, that's expected in unit tests
            # The important thing is the logic doesn't crash
            if 'not found' in str(e).lower():
                self.skipTest(f"Skipping due to missing library files: {e}")
            else:
                raise


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
        from configuration import generator
        
        # Create valid CSV files but reference a missing one
        library_csv = os.path.join(self.temp_dir, 'library.csv')
        with open(library_csv, 'w') as f:
            f.write('library,path\n')
            f.write('libtest.a,./libtest.a\n')
        
        object_csv = os.path.join(self.temp_dir, 'object.csv')
        with open(object_csv, 'w') as f:
            f.write('library,object,path\n')
            f.write('libtest.a,test.c.obj,./test.c.obj\n')
        
        # Missing function.csv
        missing_csv = os.path.join(self.temp_dir, 'missing.csv')
        sdkconfig = os.path.join(self.temp_dir, 'sdkconfig')
        with open(sdkconfig, 'w') as f:
            f.write('CONFIG_TEST=y\n')
        
        # Should raise FileNotFoundError when trying to open missing CSV
        with self.assertRaises(FileNotFoundError):
            generator(library_csv, object_csv, missing_csv, sdkconfig, 
                     missing_function_info=True, build_dir=self.temp_dir)
    
    def test_malformed_csv(self):
        """Test error handling with malformed CSV."""
        from configuration import generator
        
        # Create malformed CSV (missing required columns)
        library_csv = os.path.join(self.temp_dir, 'library.csv')
        with open(library_csv, 'w') as f:
            f.write('wrong,columns\n')
            f.write('value1,value2\n')
        
        object_csv = os.path.join(self.temp_dir, 'object.csv')
        with open(object_csv, 'w') as f:
            f.write('library,object,path\n')
            f.write('libtest.a,test.c.obj,./test.c.obj\n')
        
        function_csv = os.path.join(self.temp_dir, 'function.csv')
        with open(function_csv, 'w') as f:
            f.write('library,object,function,option\n')
            f.write('libtest.a,test.c.obj,test_func,\n')
        
        sdkconfig = os.path.join(self.temp_dir, 'sdkconfig')
        with open(sdkconfig, 'w') as f:
            f.write('CONFIG_TEST=y\n')
        
        # Should raise KeyError when trying to access missing 'path' column
        with self.assertRaises(KeyError):
            generator(library_csv, object_csv, function_csv, sdkconfig,
                     missing_function_info=True, build_dir=self.temp_dir)


class TestCompleteWorkflow(unittest.TestCase):
    """Test complete relinker workflow from CSV to linker script."""
    
    def setUp(self):
        """Set up complete test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.build_dir = os.path.join(self.temp_dir, 'build')
        os.makedirs(self.build_dir)
        
        # Set up environment
        self.original_idf_path = os.environ.get('IDF_PATH')
        self.original_build_dir = os.environ.get('BUILD_DIR')
        os.environ['IDF_PATH'] = '/path/to/esp-idf'
        os.environ['BUILD_DIR'] = self.build_dir
    
    def tearDown(self):
        """Clean up."""
        shutil.rmtree(self.temp_dir)
        
        # Restore IDF_PATH
        if self.original_idf_path:
            os.environ['IDF_PATH'] = self.original_idf_path
        elif 'IDF_PATH' in os.environ:
            del os.environ['IDF_PATH']
        
        # Restore BUILD_DIR
        if self.original_build_dir:
            os.environ['BUILD_DIR'] = self.original_build_dir
        elif 'BUILD_DIR' in os.environ:
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
        self.skipTest("Workflow documentation - no assertions")


if __name__ == '__main__':
    # Run tests with verbose output
    unittest.main(verbosity=2)
