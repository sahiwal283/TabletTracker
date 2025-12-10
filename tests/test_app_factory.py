"""
Test application factory and configuration
"""
import unittest
from app import create_app
from config import Config


class TestAppFactory(unittest.TestCase):
    """Test the application factory pattern"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.app = create_app()
        self.client = self.app.test_client()
    
    def test_app_creation(self):
        """Test that app can be created"""
        self.assertIsNotNone(self.app)
        self.assertEqual(self.app.config['SECRET_KEY'], Config.SECRET_KEY)
    
    def test_blueprints_registered(self):
        """Test that all blueprints are registered"""
        blueprint_names = [bp.name for bp in self.app.blueprints.values()]
        
        expected_blueprints = ['auth', 'admin', 'dashboard', 'production', 
                              'submissions', 'purchase_orders', 'shipping', 'api']
        
        for bp_name in expected_blueprints:
            self.assertIn(bp_name, blueprint_names, 
                         f"Blueprint '{bp_name}' not registered")


if __name__ == '__main__':
    unittest.main()
