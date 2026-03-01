#!/usr/bin/env python3
"""
Test runner for all unit tests.

Runs all test modules and provides a summary.
"""
import sys
import unittest
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def run_all_tests():
    """Run all tests and return results."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Discover all tests in the tests directory
    test_dir = Path(__file__).parent
    discovered_tests = loader.discover(str(test_dir), pattern='test_*.py')
    suite.addTests(discovered_tests)

    # Run tests with verbose output
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Return exit code based on results
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(run_all_tests())