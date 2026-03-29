# Relinker Test Suite

Comprehensive test suite for the ESP32 PlatformIO Relinker implementation.

## Quick Start

Run all tests:

```bash
cd test
python3 run_tests.py
```

Run functionality tests:

```bash
cd test
python3 test_relinker_functionality.py
```

## Test Files

- `run_tests.py` - Main test runner that executes all unit and integration tests
- `test_configuration.py` - Unit tests for `builder/relinker/configuration.py` (25 tests)
- `test_relinker.py` - Unit tests for `builder/relinker/relinker.py` (24 tests)
- `test_integration.py` - Integration tests for complete workflows (20 tests)
- `test_relinker_functionality.py` - Comprehensive functionality validation (6 categories)

## Test Results

All 75 tests pass successfully (100% success rate):

- Unit Tests (configuration.py): 25/25 ✅
- Unit Tests (relinker.py): 24/24 ✅
- Integration Tests: 20/20 ✅
- Functionality Tests: 6/6 ✅

## Running Specific Tests

```bash
cd test

# Run only configuration tests
python3 -m unittest test_configuration

# Run only relinker tests
python3 -m unittest test_relinker

# Run only integration tests
python3 -m unittest test_integration

# Run specific test class
python3 -m unittest test_configuration.TestSdkconfigC

# Run specific test method
python3 -m unittest test_configuration.TestSdkconfigC.test_check_simple_present
```

## Requirements

- Python 3.8 or higher
- No external dependencies (uses only Python standard library)

## Documentation

For detailed test documentation, see:
- `TESTING.md` - Complete testing guide
- `TEST_SUMMARY.md` - Detailed test results
- `VALIDATION_REPORT.md` - Final validation report
- `README.md` (this file) - Quick start guide

## Test Coverage

- Configuration module: ~85% coverage
- Relinker module: ~85% coverage
- Total: ~85% code coverage

All major features are tested:
- ✅ sdkconfig parsing and conditionals
- ✅ Path normalization and resolution
- ✅ Function to section conversion
- ✅ Filter functionality
- ✅ CSV processing
- ✅ Idempotency
- ✅ Error handling
