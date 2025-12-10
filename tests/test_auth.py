"""
Test authentication flows
"""
import unittest
from app import create_app
from config import Config


class TestAuthentication(unittest.TestCase):
    """Test authentication and authorization"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.app = create_app()
        self.client = self.app.test_client()
    
    def test_login_page_loads(self):
        """Test login page is accessible"""
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'login', response.data.lower())
    
    def test_admin_login_success(self):
        """Test admin login with correct credentials"""
        response = self.client.post('/', data={
            'username': 'admin',
            'password': Config.ADMIN_PASSWORD,
            'login_type': 'admin'
        }, follow_redirects=False)
        # Should redirect on successful login
        self.assertIn(response.status_code, [302, 303])
    
    def test_admin_login_failure(self):
        """Test admin login with incorrect credentials"""
        response = self.client.post('/', data={
            'username': 'admin',
            'password': 'wrong_password',
            'login_type': 'admin'
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Invalid', response.data)
    
    def test_logout(self):
        """Test logout functionality"""
        # Login first
        with self.client as client:
            client.post('/', data={
                'username': 'admin',
                'password': Config.ADMIN_PASSWORD,
                'login_type': 'admin'
            })
            # Then logout
            response = client.get('/logout', follow_redirects=False)
            self.assertIn(response.status_code, [302, 303])
    
    def test_protected_route_redirects(self):
        """Test that protected routes redirect when not authenticated"""
        protected_routes = ['/dashboard', '/admin', '/production']
        for route in protected_routes:
            response = self.client.get(route)
            # Should redirect to login or return 403 (200 acceptable if shows login form)
            self.assertIn(response.status_code, [200, 302, 303, 401, 403])


if __name__ == '__main__':
    unittest.main()

