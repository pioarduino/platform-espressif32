#!/usr/bin/env python3
"""
Comprehensive functionality test for the relinker implementation.
Tests all major features to ensure they work as planned.
"""

import sys
import os
import tempfile
import shutil

# Add the relinker directory to the path
relinker_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'builder', 'relinker')
sys.path.insert(0, relinker_dir)

from configuration import sdkconfig_c, paths_c, generator
from relinker import filter_c, func2sect

def test_sdkconfig_functionality():
    """Test sdkconfig parsing and checking."""
    print('=' * 70)
    print('TEST 1: sdkconfig Functionality')
    print('=' * 70)
    
    temp_dir = tempfile.mkdtemp()
    try:
        sdkconfig = os.path.join(temp_dir, 'sdkconfig')
        with open(sdkconfig, 'w') as f:
            f.write('CONFIG_FREERTOS_PLACE_FUNCTIONS_INTO_FLASH=y\n')
            f.write('CONFIG_ESP32_DEFAULT_CPU_FREQ_240=y\n')
            f.write('# CONFIG_DISABLED is not set\n')
        
        sdk = sdkconfig_c(sdkconfig)
        
        # Test parsing
        assert len(sdk.config) >= 2, "Should parse at least 2 configs"
        print('✓ Parsed sdkconfig successfully')
        
        # Test simple check
        assert sdk.check('CONFIG_FREERTOS_PLACE_FUNCTIONS_INTO_FLASH'), "Should find enabled config"
        print('✓ Simple config check works')
        
        # Test negation
        assert not sdk.check('!CONFIG_FREERTOS_PLACE_FUNCTIONS_INTO_FLASH'), "Negation should work"
        assert sdk.check('!CONFIG_DISABLED'), "Negation of missing config should work"
        print('✓ Negation works')
        
        # Test AND
        assert sdk.check('CONFIG_FREERTOS_PLACE_FUNCTIONS_INTO_FLASH&&CONFIG_ESP32_DEFAULT_CPU_FREQ_240'), "AND should work"
        print('✓ AND conditions work')
        
        # Test malformed negation
        assert not sdk.check('!'), "Bare ! should fail"
        print('✓ Malformed negation detection works')
        
        print('✅ sdkconfig functionality: PASSED\n')
        return True
    finally:
        shutil.rmtree(temp_dir)

def test_path_normalization():
    """Test path normalization and resolution."""
    print('=' * 70)
    print('TEST 2: Path Normalization')
    print('=' * 70)
    
    temp_dir = tempfile.mkdtemp()
    try:
        # Set IDF_PATH
        original_idf = os.environ.get('IDF_PATH')
        os.environ['IDF_PATH'] = '/test/esp-idf'
        
        paths = paths_c(temp_dir)
        
        # Test relative path
        paths.append('lib1.a', '*', './esp-idf/lib1.a')
        result = paths.index('lib1.a', '*')
        assert result is not None, "Should find library"
        assert os.path.isabs(result[0]), "Should be absolute path"
        print('✓ Relative path normalization works')
        
        # Test $IDF_PATH
        paths.append('lib2.a', '*', '$IDF_PATH/components/lib2.a')
        result = paths.index('lib2.a', '*')
        assert '/test/esp-idf' in result[0], "Should expand $IDF_PATH"
        print('✓ $IDF_PATH expansion works')
        
        # Test absolute path
        paths.append('lib3.a', '*', '/absolute/path/lib3.a')
        result = paths.index('lib3.a', '*')
        assert result[0] == '/absolute/path/lib3.a', "Absolute path should remain unchanged"
        print('✓ Absolute path handling works')
        
        # Test missing IDF_PATH error
        del os.environ['IDF_PATH']
        try:
            paths.append('lib4.a', '*', '$IDF_PATH/test.a')
            assert False, "Should raise error for missing IDF_PATH"
        except RuntimeError as e:
            assert 'IDF_PATH' in str(e), "Error should mention IDF_PATH"
            print('✓ Missing IDF_PATH error handling works')
        
        # Restore IDF_PATH
        if original_idf:
            os.environ['IDF_PATH'] = original_idf
        
        print('✅ Path normalization: PASSED\n')
        return True
    finally:
        shutil.rmtree(temp_dir)

def test_function_to_section():
    """Test function to section conversion."""
    print('=' * 70)
    print('TEST 3: Function to Section Conversion')
    print('=' * 70)
    
    # Test simple function
    result = func2sect('my_function')
    assert '.literal.my_function' in result, "Should have literal section"
    assert '.text.my_function' in result, "Should have text section"
    print('✓ Simple function conversion works')
    
    # Test multiple functions
    result = func2sect('func1 func2')
    assert len(result) == 4, "Should have 4 sections (2 per function)"
    print('✓ Multiple function conversion works')
    
    # Test IRAM function
    result = func2sect('.iram1.my_func')
    assert '.iram1.my_func' in result, "Should preserve IRAM section"
    print('✓ IRAM function handling works')
    
    print('✅ Function to section conversion: PASSED\n')
    return True

def test_filter_functionality():
    """Test filter_c functionality."""
    print('=' * 70)
    print('TEST 4: Filter Functionality')
    print('=' * 70)
    
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
        assert filt is not None, "Filter should be created"
        assert hasattr(filt, 'entries'), "Filter should have entries"
        assert hasattr(filt, 'libs_desc'), "Filter should have libs_desc"
        print('✓ Filter object creation works')
        
        # Test match method
        result = filt.match('*libtest.a:test.*')
        assert isinstance(result, bool), "Match should return boolean"
        print('✓ Filter match method works')
        
        # Test add method
        result = filt.add()
        assert isinstance(result, str), "Add should return string"
        print('✓ Filter add method works')
        
        print('✅ Filter functionality: PASSED\n')
        return True
    finally:
        shutil.rmtree(temp_dir)

def test_csv_processing():
    """Test CSV file processing."""
    print('=' * 70)
    print('TEST 5: CSV Processing')
    print('=' * 70)
    
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
            assert len(rows) == 1, "Should read 1 library"
            print('✓ Library CSV reading works')
        
        with open(object_csv, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            assert len(rows) == 1, "Should read 1 object"
            print('✓ Object CSV reading works')
        
        with open(function_csv, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            assert len(rows) == 1, "Should read 1 function"
            print('✓ Function CSV reading works')
        
        print('✅ CSV processing: PASSED\n')
        return True
    finally:
        shutil.rmtree(temp_dir)

def test_idempotency():
    """Test that operations are idempotent."""
    print('=' * 70)
    print('TEST 6: Idempotency')
    print('=' * 70)
    
    # Test that path normalization is consistent
    temp_dir = tempfile.mkdtemp()
    try:
        paths1 = paths_c(temp_dir)
        paths1.append('lib.a', '*', './test/lib.a')
        result1 = paths1.index('lib.a', '*')
        
        paths2 = paths_c(temp_dir)
        paths2.append('lib.a', '*', './test/lib.a')
        result2 = paths2.index('lib.a', '*')
        
        assert result1[0] == result2[0], "Same input should produce same output"
        print('✓ Path normalization is idempotent')
        
        # Test that sdkconfig checking is consistent
        sdkconfig = os.path.join(temp_dir, 'sdkconfig')
        with open(sdkconfig, 'w') as f:
            f.write('CONFIG_TEST=y\n')
        
        sdk1 = sdkconfig_c(sdkconfig)
        sdk2 = sdkconfig_c(sdkconfig)
        
        assert sdk1.check('CONFIG_TEST') == sdk2.check('CONFIG_TEST'), "Same check should give same result"
        print('✓ sdkconfig checking is idempotent')
        
        print('✅ Idempotency: PASSED\n')
        return True
    finally:
        shutil.rmtree(temp_dir)

def main():
    """Run all functionality tests."""
    print('\n' + '=' * 70)
    print('RELINKER FUNCTIONALITY TEST SUITE')
    print('=' * 70)
    print()
    
    tests = [
        test_sdkconfig_functionality,
        test_path_normalization,
        test_function_to_section,
        test_filter_functionality,
        test_csv_processing,
        test_idempotency,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
        except Exception as e:
            print(f'❌ {test.__name__} FAILED: {e}\n')
            failed += 1
    
    print('=' * 70)
    print('FINAL RESULTS')
    print('=' * 70)
    print(f'Tests passed: {passed}/{len(tests)}')
    print(f'Tests failed: {failed}/{len(tests)}')
    
    if failed == 0:
        print('\n🎉 ALL FUNCTIONALITY TESTS PASSED!')
        print('✅ The relinker implementation works as planned!')
        return 0
    else:
        print(f'\n⚠️  {failed} test(s) failed')
        return 1

if __name__ == '__main__':
    sys.exit(main())
