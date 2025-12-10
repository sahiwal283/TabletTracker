"""
Test that critical routes are accessible
"""
import unittest
from app import create_app


class TestRoutes(unittest.TestCase):
    """Test critical route availability"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.app = create_app()
        self.client = self.app.test_client()
    
    def test_index_route(self):
        """Test index/login page loads"""
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
    
    def test_version_route(self):
        """Test version endpoint"""
        response = self.client.get('/version')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn('version', data)
    
    def test_dashboard_requires_auth(self):
        """Test dashboard requires authentication"""
        response = self.client.get('/dashboard')
        # Should redirect to login
        self.assertIn(response.status_code, [302, 401, 403])


if __name__ == '__main__':
    unittest.main()

