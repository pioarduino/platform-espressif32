# Test Suite for platform-espressif32

This directory contains comprehensive unit tests for the ESP32 platform implementation.

## Test Structure

The test suite is organized into the following modules:

### Python Module Tests

1. **test_builder_main.py** - Tests for `builder/main.py`
   - Partition table parsing
   - Filesystem builders (LittleFS, SPIFFS, FatFS)
   - Upload preparation
   - Size calculations
   - Board configuration

2. **test_penv_setup.py** - Tests for `builder/penv_setup.py`
   - Python virtual environment setup
   - Dependency management
   - Internet connectivity checks
   - esptool installation
   - Certificate configuration

3. **test_filter_exception_decoder.py** - Tests for `monitor/filter_exception_decoder.py`
   - ESP32 exception backtrace decoding
   - Address pattern matching
   - ROM ELF integration
   - Xtensa and RISC-V exception handling
   - Context-aware processing

4. **test_platform.py** - Tests for `platform.py`
   - Platform configuration
   - Package management
   - Tool installation
   - Board configuration
   - Framework setup

### Configuration Tests

5. **test_json_schemas.py** - JSON schema validation tests
   - Board configuration files validation
   - platform.json structure validation
   - Consistency checks across configurations

## Running Tests

### Run All Tests
```bash
python tests/run_all_tests.py
```

### Run Specific Test Module
```bash
python -m unittest tests.test_json_schemas -v
python -m unittest tests.test_penv_setup -v
python -m unittest tests.test_builder_main -v
python -m unittest tests.test_filter_exception_decoder -v
python -m unittest tests.test_platform -v
```

### Run Specific Test Class
```bash
python -m unittest tests.test_json_schemas.TestBoardJsonSchema -v
```

### Run Specific Test Method
```bash
python -m unittest tests.test_json_schemas.TestBoardJsonSchema.test_board_required_fields -v
```

## Test Coverage

The test suite covers:

- **Functional Testing**: Core functionality of builders, parsers, and decoders
- **Schema Validation**: JSON configuration file structure and consistency
- **Edge Cases**: Error handling, boundary conditions, and malformed inputs
- **Integration**: Module interactions and data flow
- **Regression**: Tests to prevent known issues from reoccurring

## Key Test Features

### Mocking Strategy
Tests use extensive mocking to:
- Isolate units under test
- Avoid external dependencies (SCons, PlatformIO modules)
- Simulate various system configurations
- Test error conditions

### Test Categories

1. **Unit Tests**: Test individual functions and methods in isolation
2. **Integration Tests**: Test interactions between modules
3. **Validation Tests**: Verify data structure correctness
4. **Regression Tests**: Prevent reintroduction of bugs

## Adding New Tests

When adding new tests, follow these guidelines:

1. **Organization**: Group related tests in test classes
2. **Naming**: Use descriptive test names starting with `test_`
3. **Documentation**: Add docstrings explaining what is tested
4. **Independence**: Each test should be independent and not rely on others
5. **Coverage**: Test both success and failure cases
6. **Assertions**: Use specific assertions (assertEqual, assertIn, etc.)

### Example Test Structure

```python
class TestNewFeature(unittest.TestCase):
    """Test new feature functionality."""

    def setUp(self):
        """Set up test fixtures."""
        # Initialize test data
        pass

    def tearDown(self):
        """Clean up after tests."""
        # Clean up resources
        pass

    def test_basic_functionality(self):
        """Test basic feature operation."""
        # Arrange
        # Act
        # Assert
        pass

    def test_error_handling(self):
        """Test error cases."""
        # Test failure scenarios
        pass

    def test_edge_cases(self):
        """Test boundary conditions."""
        # Test edge cases
        pass
```

## Test Requirements

Tests are designed to run with Python's built-in `unittest` framework, minimizing external dependencies:

- Python 3.10+
- No additional test framework dependencies required
- Mock objects from `unittest.mock`

## Continuous Integration

These tests are designed to be run in CI/CD pipelines. They:
- Run quickly (< 5 seconds for full suite)
- Don't require network access (except for internet check tests which are mocked)
- Don't require special permissions
- Provide clear failure messages

## Troubleshooting

### Import Errors
If you encounter import errors, ensure:
- You're running tests from the project root
- Python path includes parent directory
- All required modules are mocked

### Test Failures
When tests fail:
1. Read the failure message carefully
2. Check if recent code changes affect the test
3. Verify test assumptions are still valid
4. Update tests if behavior intentionally changed

## Contributing

When contributing code changes:
1. Add tests for new functionality
2. Update existing tests if behavior changes
3. Ensure all tests pass before submitting
4. Aim for high test coverage (>80%)
5. Document complex test scenarios