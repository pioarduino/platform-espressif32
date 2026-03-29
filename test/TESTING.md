# Relinker Test Suite

Comprehensive test suite for the ESP32 PlatformIO Relinker.

## Overview

The test suite consists of four main components:

1. **Unit Tests** (`test_configuration.py`) - Tests for configuration.py
2. **Unit Tests** (`test_relinker.py`) - Tests for relinker.py
3. **Integration Tests** (`test_integration.py`) - End-to-end workflow tests
4. **Functionality Tests** (`test_relinker_functionality.py`) - Comprehensive feature validation

All tests are located in the `test/` directory in the repository root.

## Running Tests

### Run All Tests

```bash
cd test
python3 run_tests.py
```

Or from the repository root:

```bash
python3 test/run_tests.py
```

### Run Functionality Tests

```bash
cd test
python3 test_relinker_functionality.py
```

### Run Specific Test Module

```bash
cd test

# Run only configuration tests
python3 -m unittest test_configuration

# Run only relinker tests
python3 -m unittest test_relinker

# Run only integration tests
python3 -m unittest test_integration
```

### Run Individual Test Class

```bash
cd test

# Run specific test class
python3 -m unittest test_configuration.TestSdkconfigC

# Run specific test method
python3 -m unittest test_configuration.TestSdkconfigC.test_check_simple_present
```

### Run with Verbose Output

```bash
cd test
python3 -m unittest discover -v
```

## Test Coverage

### test_configuration.py

Tests for `configuration.py` module:

#### TestSdkconfigC
- ✓ Configuration file parsing
- ✓ Simple config checking (present/missing)
- ✓ Negation handling (!CONFIG_X)
- ✓ AND conditions (CONFIG_A&&CONFIG_B)
- ✓ Empty string handling
- ✓ Malformed negation detection (bare !)
- ✓ Whitespace handling

#### TestPathsC
- ✓ Relative path normalization
- ✓ Absolute path handling
- ✓ $IDF_PATH variable expansion
- ✓ Missing IDF_PATH error handling
- ✓ Wildcard object matching
- ✓ Missing library/object handling

#### TestObjectC
- ✓ Object creation and function appending
- ✓ Return value on missing sections

#### TestLibraryC
- ✓ Library initialization
- ✓ Object management

#### TestLibrariesC
- ✓ Library collection management

#### TestPathNormalization
- ✓ ./ prefix handling
- ✓ No prefix handling
- ✓ Multiple dots in filenames

### test_relinker.py

Tests for `relinker.py` module:

#### TestFunc2Sect
- ✓ Simple function to section conversion
- ✓ Multiple function handling
- ✓ IRAM function handling

#### TestFilterSecs
- ✓ Section filtering with patterns
- ✓ No match scenarios

#### TestStripSecs
- ✓ Section removal
- ✓ Sorted output

#### TestFilterC
- ✓ EXCLUDE_FILE pattern parsing
- ✓ Library:object pattern matching
- ✓ Non-matching patterns
- ✓ Original descriptor retrieval

#### TestRelinkIdempotency
- ✓ Original pattern recognition
- ✓ Relinker-generated pattern recognition

#### TestSourceNameHandling
- ✓ .obj extension handling
- ✓ C++ file handling
- ✓ Assembly file handling
- ✓ Non-.obj file handling
- ✓ rsplit fallback logic
- ✓ Multiple dots in filenames

#### TestLinkerScriptPatterns
- ✓ Original IRAM pattern recognition
- ✓ EXCLUDE_FILE pattern recognition
- ✓ Relinker IRAM include pattern
- ✓ Relinker flash include pattern

### test_integration.py

Integration tests for complete workflows:

#### TestCSVProcessing
- ✓ CSV file creation
- ✓ Library CSV reading
- ✓ Object CSV reading
- ✓ Function CSV reading

#### TestPathResolution
- ✓ Relative path resolution
- ✓ $IDF_PATH resolution
- ✓ Absolute path handling

#### TestSdkconfigConditionals
- ✓ Enabled config checking
- ✓ Disabled config checking
- ✓ Negated conditions
- ✓ AND conditions

#### TestLinkerScriptModification
- ✓ Linker script creation
- ✓ IRAM section presence
- ✓ Flash section presence

#### TestIdempotency
- ✓ Multiple run consistency

#### TestErrorHandling
- ✓ Missing IDF_PATH error
- ✓ Missing CSV file handling
- ✓ Malformed CSV handling

#### TestCompleteWorkflow
- ✓ End-to-end workflow documentation

## Test Requirements

### Python Version
- Python 3.10 or higher

### Dependencies
- No external dependencies required (uses only Python standard library)
- Tests use `unittest` framework (built-in)
- Temporary files managed with `tempfile` module

### Environment Variables

Some tests require environment variables:

- `IDF_PATH` - Path to ESP-IDF framework (set automatically in tests)
- `BUILD_DIR` - Build directory (set automatically in tests)

## Writing New Tests

### Test Structure

```python
import unittest
import tempfile
import os

class TestNewFeature(unittest.TestCase):
    """Test description."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
    
    def tearDown(self):
        """Clean up after tests."""
        import shutil
        shutil.rmtree(self.temp_dir)
    
    def test_feature(self):
        """Test specific feature."""
        # Arrange
        expected = "value"
        
        # Act
        result = function_under_test()
        
        # Assert
        self.assertEqual(result, expected)
```

### Best Practices

1. **Isolation**: Each test should be independent
2. **Cleanup**: Always clean up temporary files in `tearDown()`
3. **Descriptive Names**: Use clear, descriptive test names
4. **Documentation**: Add docstrings to test classes and methods
5. **Assertions**: Use appropriate assertion methods
6. **Edge Cases**: Test boundary conditions and error cases

### Common Assertions

```python
# Equality
self.assertEqual(a, b)
self.assertNotEqual(a, b)

# Truth
self.assertTrue(x)
self.assertFalse(x)

# Membership
self.assertIn(item, container)
self.assertNotIn(item, container)

# Exceptions
with self.assertRaises(ExceptionType):
    function_that_raises()

# None
self.assertIsNone(x)
self.assertIsNotNone(x)
```

## Continuous Integration

### GitHub Actions Example

```yaml
name: Relinker Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v2
    
    - name: Set up Python
      uses: actions/setup-python@v2
      with:
        python-version: '3.10'
    
    - name: Run tests
      run: |
        cd test
        python3 run_tests.py
```

## Troubleshooting

### Tests Fail to Import Modules

Ensure you're running tests from the correct directory:

```bash
cd test
python3 run_tests.py
```

### Permission Errors

Ensure test files are executable:

```bash
chmod +x run_tests.py
chmod +x test_*.py
```

### Temporary File Cleanup Issues

If tests leave temporary files, manually clean up:

```bash
# Manually clean up test temp directories if needed
# Note: Tests should clean up automatically in tearDown()
# Only use this if tests were interrupted
rm -rf /tmp/tmp*relinker*
```

## Possible Future Improvements

- [ ] Add code coverage reporting (coverage.py)
- [ ] Add performance benchmarks
- [ ] Add mock objdump for complete object_c testing
- [ ] Add end-to-end relinker execution tests
- [ ] Add regression tests for known issues
- [ ] Add property-based testing (hypothesis)

## License

Same as the main project (Apache 2.0).
