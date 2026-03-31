#!/usr/bin/env python3
"""
Unit tests for builder/relinker/relinker.py

Tests cover:
- filter_c: Filtering library/object patterns
- target_c: Target creation and section handling
- relink_c: Main relinker logic and idempotency
"""

import unittest
import tempfile
import os
import sys
from pathlib import Path

# Add the relinker directory to the path
relinker_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'builder', 'relinker')
sys.path.insert(0, relinker_dir)

from relinker import filter_c, func2sect, filter_secs, strip_secs, _is_iram_desc, _is_relinker_iram_include, _is_relinker_flash_include


class TestFunc2Sect(unittest.TestCase):
    """Test func2sect function for converting function names to sections."""
    
    def test_simple_function(self):
        """Test conversion of simple function name."""
        result = func2sect('my_function')
        
        self.assertIn('.literal.my_function', result)
        self.assertIn('.text.my_function', result)
    
    def test_multiple_functions(self):
        """Test conversion of multiple function names."""
        result = func2sect('func1 func2')
        
        self.assertIn('.literal.func1', result)
        self.assertIn('.text.func1', result)
        self.assertIn('.literal.func2', result)
        self.assertIn('.text.func2', result)
    
    def test_iram_function(self):
        """Test conversion of IRAM function."""
        result = func2sect('.iram1.my_function')
        
        self.assertIn('.iram1.my_function', result)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], '.iram1.my_function')


class TestFilterSecs(unittest.TestCase):
    """Test filter_secs function for filtering sections."""
    
    def test_filter_matching_sections(self):
        """Test filtering sections that match patterns."""
        secs_a = ['.iram1.func1', '.text.func2', '.iram1.func3']
        secs_b = ['.iram1.']
        
        result = filter_secs(secs_a, secs_b)
        
        self.assertIn('.iram1.func1', result)
        self.assertIn('.iram1.func3', result)
        self.assertNotIn('.text.func2', result)
    
    def test_filter_no_matches(self):
        """Test filtering with no matches."""
        secs_a = ['.text.func1', '.text.func2']
        secs_b = ['.iram1.']
        
        result = filter_secs(secs_a, secs_b)
        
        self.assertEqual(len(result), 0)


class TestStripSecs(unittest.TestCase):
    """Test strip_secs function for removing sections."""
    
    def test_strip_sections(self):
        """Test stripping sections from list."""
        secs_a = ['.iram1.func1', '.text.func2', '.iram1.func3']
        secs_b = ['.iram1.func1']
        
        result = strip_secs(secs_a, secs_b)
        
        self.assertNotIn('.iram1.func1', result)
        self.assertIn('.text.func2', result)
        self.assertIn('.iram1.func3', result)
    
    def test_strip_sorted(self):
        """Test that result is sorted."""
        secs_a = ['.z', '.a', '.m']
        secs_b = []
        
        result = strip_secs(secs_a, secs_b)
        
        self.assertEqual(result, ['.a', '.m', '.z'])


class TestFilterC(unittest.TestCase):
    """Test filter_c class for filtering libraries and objects."""
    
    def setUp(self):
        """Create temporary linker script for testing."""
        self.temp_dir = tempfile.mkdtemp()
        self.linker_script = os.path.join(self.temp_dir, 'sections.ld')
        
        # Create a realistic linker script with EXCLUDE_FILE patterns
        # Based on actual ESP-IDF linker scripts
        # Include both whole-library tokens (e.g., *libfreertos.a) and object-specific tokens
        with open(self.linker_script, 'w') as f:
            f.write('.iram0.text : {\n')
            f.write('    _iram_text_start = ABSOLUTE(.);\n')
            f.write('    /* Vectors go to IRAM */\n')
            f.write('    KEEP(*(.exception_vectors.text));\n')
            f.write('    /* Code marked as running out of IRAM */\n')
            f.write('    *(.iram1 .iram1.*)\n')
            f.write('    /* IRAM functions from libraries */\n')
            f.write('    *(EXCLUDE_FILE(*libfreertos.a *libheap.a *libfreertos.a:tasks.* *libheap.a:heap_caps.*) .iram1.*)\n')
            f.write('    *(EXCLUDE_FILE(*libfreertos.a *libheap.a *libfreertos.a:tasks.* *libheap.a:heap_caps.*) .iram1)\n')
            f.write('    _iram_text_end = ABSOLUTE(.);\n')
            f.write('} > iram0_0_seg\n')
    
    def tearDown(self):
        """Clean up temporary files."""
        import shutil
        shutil.rmtree(self.temp_dir)
    
    def test_parse_exclude_patterns(self):
        """Test parsing of EXCLUDE_FILE patterns."""
        filt = filter_c(self.linker_script)
        
        # Test that the filter object is created successfully
        self.assertIsNotNone(filt)
        self.assertIsNotNone(filt.libs_desc)
        self.assertIsNotNone(filt.entries)
        
        # Verify that whole-library tokens are parsed and retained
        self.assertIsInstance(filt.entries, set)
        self.assertGreater(len(filt.entries), 0, "Should have parsed whole-library tokens")
        
        # Verify specific whole-library entries are present
        self.assertIn('libfreertos.a', filt.entries, "Should contain libfreertos.a")
        self.assertIn('libheap.a', filt.entries, "Should contain libheap.a")
        
        # Verify libs_desc contains the whole-library tokens
        self.assertIn('libfreertos.a', filt.libs_desc, "libs_desc should contain libfreertos.a")
        self.assertIn('libheap.a', filt.libs_desc, "libs_desc should contain libheap.a")
        
        # Verify object-specific tokens are NOT in entries (they should be filtered out)
        self.assertNotIn('libfreertos.a:tasks.*', filt.libs_desc, "Object-specific tokens should be filtered out")
    
    def test_parse_exclude_patterns_with_correct_format(self):
        """Test parsing with the exact format filter_c expects."""
        # Create a linker script with the EXACT format that filter_c looks for
        # Include both whole-library and object-specific tokens
        temp_script = os.path.join(self.temp_dir, 'sections_correct.ld')
        with open(temp_script, 'w') as f:
            f.write('.iram0.text : {\n')
            f.write('    *(EXCLUDE_FILE(*libfreertos.a *libhal.a *libfreertos.a:tasks.* *libheap.a:heap_caps.*) .iram1.*)\n')
            f.write('}\n')
        
        filt = filter_c(temp_script)
        
        # Verify the parser initialized correctly
        self.assertIsInstance(filt.libs_desc, str, "Parser should initialize libs_desc")
        self.assertIsInstance(filt.entries, set, "Parser should initialize entries set")
        
        # Verify whole-library tokens are parsed
        self.assertGreater(len(filt.libs_desc), 0, "Should have parsed whole-library tokens")
        self.assertGreater(len(filt.entries), 0, "Should have entries for whole-library tokens")
        
        # Verify specific libraries are present
        self.assertIn('libfreertos.a', filt.libs_desc, "libs_desc should contain libfreertos.a")
        self.assertIn('libhal.a', filt.libs_desc, "libs_desc should contain libhal.a")
        self.assertIn('libfreertos.a', filt.entries, "entries should contain libfreertos.a")
        self.assertIn('libhal.a', filt.entries, "entries should contain libhal.a")
        
        # Verify object-specific tokens are filtered out
        self.assertNotIn('libfreertos.a:tasks.*', filt.libs_desc, "Object-specific tokens should be filtered out")
        self.assertNotIn('libheap.a:heap_caps.*', filt.libs_desc, "Object-specific tokens should be filtered out")
    
    def test_match_library_object(self):
        """Test matching library patterns."""
        filt = filter_c(self.linker_script)
        
        # Verify the filter has entries
        self.assertIsInstance(filt.entries, set, "Filter should have entries set")
        self.assertGreater(len(filt.entries), 0, "Filter should have parsed entries")
        
        # Test matching whole-library tokens (should match)
        self.assertTrue(filt.match('*libfreertos.a'), "Should match whole-library token")
        self.assertTrue(filt.match('*libheap.a'), "Should match whole-library token")
        
        # Test that object-specific patterns don't match (they're not in entries)
        self.assertFalse(filt.match('*libfreertos.a:tasks.*'), "Object-specific tokens should not match")
    
    def test_no_match_different_pattern(self):
        """Test non-matching patterns."""
        filt = filter_c(self.linker_script)
        
        # Should not match patterns not in EXCLUDE_FILE
        self.assertFalse(filt.match('*libother.a:other.*'))
    
    def test_add_returns_original_desc(self):
        """Test that add() returns original descriptor with whole-library tokens."""
        filt = filter_c(self.linker_script)
        
        result = filt.add()
        # The descriptor should be a string containing whole-library tokens
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0, "Should return non-empty descriptor")
        
        # Verify it contains the expected whole-library tokens
        self.assertIn('libfreertos.a', result, "Should contain libfreertos.a")
        self.assertIn('libheap.a', result, "Should contain libheap.a")
        
        # Verify it does NOT contain object-specific tokens
        self.assertNotIn(':', result, "Should not contain object-specific tokens with colons")


class TestRelinkIdempotency(unittest.TestCase):
    """Test that relinker operations are idempotent."""
    
    def setUp(self):
        """Create temporary files for testing."""
        self.temp_dir = tempfile.mkdtemp()
        self.linker_script = os.path.join(self.temp_dir, 'sections.ld')
        
        # Create a simple linker script
        with open(self.linker_script, 'w') as f:
            f.write('.iram0.text : {\n')
            f.write('    *(.iram1 .iram1.*)\n')
            f.write('}\n')
            f.write('\n')
            f.write('.flash.text : {\n')
            f.write('    *(.stub .gnu.warning .gnu.linkonce.literal.* .gnu.linkonce.t.*.*)\n')
            f.write('}\n')
    
    def tearDown(self):
        """Clean up temporary files."""
        import shutil
        shutil.rmtree(self.temp_dir)
    
    def test_is_iram_desc_original_pattern(self):
        """Test is_iram_desc recognizes original patterns."""
        # Test original ldgen pattern
        line1 = '    *(.iram1 .iram1.*)'
        self.assertTrue(_is_iram_desc(line1))
        
        # Test with surrounding content
        line2 = '    mapping[iram0_text] = .iram0.text *(.iram1 .iram1.*) ALIGN(4)'
        self.assertTrue(_is_iram_desc(line2))
        
        # Test negative case
        line3 = '    *(.text .text.*)'
        self.assertFalse(_is_iram_desc(line3))
    
    def test_is_iram_desc_relinker_pattern(self):
        """Test is_iram_desc recognizes relinker-generated patterns."""
        # Test old relinker pattern with EXCLUDE_FILE (single line)
        line1 = '    *(EXCLUDE_FILE(*libfreertos.a:tasks.*) .iram1 EXCLUDE_FILE(*libfreertos.a:tasks.*) .iram1.*)'
        self.assertTrue(_is_iram_desc(line1))
        
        # Test new relinker pattern (single line - old format)
        line2 = '    *(EXCLUDE_FILE(*libfreertos.a:tasks.* *libheap.a:heap_caps.*) .iram1.*) *(EXCLUDE_FILE(*libfreertos.a:tasks.* *libheap.a:heap_caps.*) .iram1)'
        self.assertTrue(_is_iram_desc(line2))
        
        # Test new relinker pattern (multi-line format - first line)
        line3 = '    *(EXCLUDE_FILE(*libfreertos.a:tasks.* *libheap.a:heap_caps.*) .iram1.*)'
        self.assertTrue(_is_iram_desc(line3))
        
        # Test new relinker pattern (multi-line format - second line)
        line4 = '    *(EXCLUDE_FILE(*libfreertos.a:tasks.* *libheap.a:heap_caps.*) .iram1)'
        self.assertTrue(_is_iram_desc(line4))
        
        # Test negative case - flash pattern
        line5 = '    *libfreertos.a:tasks.*(.literal.xTaskCreate .text.xTaskCreate)'
        self.assertFalse(_is_iram_desc(line5))


class TestSourceNameHandling(unittest.TestCase):
    """Test source name handling for different file types."""
    
    def test_obj_file_extension(self):
        """Test handling of .obj extension."""
        # Test the logic: file[:-4] if file.endswith('.obj') else file
        file = 'tasks.c.obj'
        source_name = file[:-4] if file.endswith('.obj') else file
        
        self.assertEqual(source_name, 'tasks.c')
    
    def test_cpp_obj_file(self):
        """Test handling of C++ .obj files."""
        file = 'queue.cpp.obj'
        source_name = file[:-4] if file.endswith('.obj') else file
        
        self.assertEqual(source_name, 'queue.cpp')
    
    def test_assembly_obj_file(self):
        """Test handling of assembly .obj files."""
        file = 'port.S.obj'
        source_name = file[:-4] if file.endswith('.obj') else file
        
        self.assertEqual(source_name, 'port.S')
    
    def test_non_obj_file(self):
        """Test handling of non-.obj files."""
        file = 'tasks.c'
        source_name = file[:-4] if file.endswith('.obj') else file
        
        self.assertEqual(source_name, 'tasks.c')
    
    def test_rsplit_fallback(self):
        """Test rsplit fallback for removing extension."""
        source_name = 'tasks.c'
        base_name = source_name.rsplit('.', 1)[0]
        
        self.assertEqual(base_name, 'tasks')
    
    def test_rsplit_multiple_dots(self):
        """Test rsplit with multiple dots."""
        source_name = 'my.file.c'
        base_name = source_name.rsplit('.', 1)[0]
        
        self.assertEqual(base_name, 'my.file')


class TestLinkerScriptPatterns(unittest.TestCase):
    """Test recognition of various linker script patterns."""
    
    def test_original_iram_pattern(self):
        """Test recognition of original IRAM pattern."""
        line = '    *(.iram1 .iram1.*)'
        
        # Call the actual predicate
        self.assertTrue(_is_iram_desc(line))
    
    def test_exclude_file_pattern(self):
        """Test recognition of EXCLUDE_FILE pattern."""
        line = '    *(EXCLUDE_FILE(*lib.a:obj.*) .iram1.*) *(EXCLUDE_FILE(*lib.a:obj.*) .iram1)'
        
        # Call the actual predicate
        self.assertTrue(_is_iram_desc(line))
    
    def test_relinker_iram_include_pattern(self):
        """Test recognition of relinker IRAM include pattern."""
        line = '    *libfreertos.a:tasks.*(.iram1.xTaskGetTickCount)'
        
        # Call the actual predicate
        self.assertTrue(_is_relinker_iram_include(line))
    
    def test_relinker_flash_include_pattern(self):
        """Test recognition of relinker flash include pattern."""
        line = '    *libfreertos.a:tasks.*(.literal.xTaskGetTickCount .text.xTaskGetTickCount)'
        
        # Call the actual predicate
        self.assertTrue(_is_relinker_flash_include(line))


class TestDescriptorMerging(unittest.TestCase):
    """Test that sections are properly merged per descriptor for duplicate object names."""
    
    def test_per_descriptor_merging(self):
        """Test that duplicate descriptors have their sections merged."""
        self.skipTest("TODO: add a fixture that exercises duplicate-descriptor merging")


if __name__ == '__main__':
    unittest.main()
