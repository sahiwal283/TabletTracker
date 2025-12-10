"""
Test database operations and migrations
"""
import unittest
import os
from config import Config
from app.models.database import check_db_initialized


class TestDatabase(unittest.TestCase):
    """Test database functionality"""
    
    def test_database_exists(self):
        """Test that database file exists"""
        self.assertTrue(os.path.exists(Config.DATABASE_PATH))
    
    def test_database_initialized(self):
        """Test that database has Alembic version table"""
        self.assertTrue(check_db_initialized())
    
    def test_database_path(self):
        """Test database path is in database/ directory"""
        self.assertIn('database', Config.DATABASE_PATH)
        self.assertTrue(Config.DATABASE_PATH.endswith('tablet_counter.db'))


if __name__ == '__main__':
    unittest.main()

