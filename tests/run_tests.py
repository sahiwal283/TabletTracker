#!/usr/bin/env python
"""
Test runner for TabletTracker
"""
import unittest
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Allow tests when TABLETTRACKER_SELF_HOSTED is set in the shell (Docker / CI).
os.environ.setdefault("SKIP_ZOHO_SERVICE_CHECK", "1")

if __name__ == '__main__':
    # Discover and run all tests
    loader = unittest.TestLoader()
    start_dir = 'tests'
    suite = loader.discover(start_dir, pattern='test_*.py')
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Exit with error code if tests failed
    sys.exit(not result.wasSuccessful())

