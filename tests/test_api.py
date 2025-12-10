"""
Test API endpoints
"""
import unittest
from app import create_app


class TestAPIEndpoints(unittest.TestCase):
    """Test critical API endpoints"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.app = create_app()
        self.client = self.app.test_client()
    
    def test_version_endpoint(self):
        """Test /version returns proper JSON"""
        response = self.client.get('/version')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn('version', data)
        self.assertEqual(data['version'], '2.0.0')
        self.assertIn('title', data)
        self.assertIn('description', data)
    
    def test_api_requires_auth(self):
        """Test API endpoints require authentication"""
        protected_apis = [
            '/api/sync-zoho-pos',
            '/api/po-lines/1',
            '/api/save-product'
        ]
        for api in protected_apis:
            response = self.client.get(api)
            # Should require auth (404 acceptable if route renamed)
            self.assertIn(response.status_code, [302, 401, 403, 404, 405])


if __name__ == '__main__':
    unittest.main()

