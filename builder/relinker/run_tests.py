#!/usr/bin/env python3
"""
Test runner for relinker tests.

Runs all unit and integration tests and provides a summary.
"""

import sys
import unittest
import os

# Add the relinker directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def run_all_tests():
    """Run all test suites."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Discover and add all tests
    print("=" * 70)
    print("RELINKER TEST SUITE")
    print("=" * 70)
    print()
    
    # Add unit tests
    print("Loading unit tests...")
    try:
        import test_configuration
        configuration_tests = loader.loadTestsFromModule(test_configuration)
        suite.addTests(configuration_tests)
        print(f"  ✓ Loaded {configuration_tests.countTestCases()} tests from test_configuration")
    except Exception as e:
        print(f"  ✗ Failed to load test_configuration: {e}")
    
    try:
        import test_relinker
        relinker_tests = loader.loadTestsFromModule(test_relinker)
        suite.addTests(relinker_tests)
        print(f"  ✓ Loaded {relinker_tests.countTestCases()} tests from test_relinker")
    except Exception as e:
        print(f"  ✗ Failed to load test_relinker: {e}")
    
    # Add integration tests
    print("Loading integration tests...")
    try:
        import test_integration
        integration_tests = loader.loadTestsFromModule(test_integration)
        suite.addTests(integration_tests)
        print(f"  ✓ Loaded {integration_tests.countTestCases()} tests from test_integration")
    except Exception as e:
        print(f"  ✗ Failed to load test_integration: {e}")
    
    print()
    print(f"Total tests to run: {suite.countTestCases()}")
    print("=" * 70)
    print()
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Print summary
    print()
    print("=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    print(f"Tests run: {result.testsRun}")
    print(f"Successes: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")
    print("=" * 70)
    
    # Return exit code
    return 0 if result.wasSuccessful() else 1


def run_specific_test(test_module):
    """Run a specific test module."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    print(f"Running tests from {test_module}...")
    print("=" * 70)
    
    try:
        module = __import__(test_module)
        tests = loader.loadTestsFromModule(module)
        suite.addTests(tests)
        
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)
        
        return 0 if result.wasSuccessful() else 1
    except Exception as e:
        print(f"Error loading test module: {e}")
        return 1


if __name__ == '__main__':
    if len(sys.argv) > 1:
        # Run specific test module
        test_module = sys.argv[1]
        sys.exit(run_specific_test(test_module))
    else:
        # Run all tests
        sys.exit(run_all_tests())
