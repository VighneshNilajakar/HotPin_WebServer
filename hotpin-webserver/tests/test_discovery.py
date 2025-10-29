"""Unit tests for the discovery module."""
import unittest
from unittest.mock import patch, MagicMock
import sys
import os

# Add the project root to the path so we can import the discovery module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

try:
    from hotpin.discovery import get_primary_ip, make_ws_url, DiscoveryService
    DISCOVERY_AVAILABLE = True
except ImportError:
    DISCOVERY_AVAILABLE = False

class TestDiscovery(unittest.TestCase):
    """Test cases for the discovery module."""
    
    def setUp(self):
        """Set up test fixtures before each test method."""
        if not DISCOVERY_AVAILABLE:
            self.skipTest("Discovery module not available")
    
    def test_get_primary_ip(self):
        """Test that get_primary_ip returns a valid IP address."""
        ip = get_primary_ip()
        self.assertIsInstance(ip, str)
        # Should be either localhost or a valid IPv4 address
        self.assertTrue(ip == "127.0.0.1" or len(ip.split('.')) == 4)
        if ip != "127.0.0.1":
            parts = ip.split('.')
            for part in parts:
                self.assertTrue(part.isdigit())
                self.assertTrue(0 <= int(part) <= 255)
    
    def test_make_ws_url_without_token(self):
        """Test make_ws_url without token."""
        url = make_ws_url("192.168.1.100", 8000, "/ws")
        self.assertEqual(url, "ws://192.168.1.100:8000/ws")
    
    def test_make_ws_url_with_token(self):
        """Test make_ws_url with token."""
        url = make_ws_url("192.168.1.100", 8000, "/ws", "abc123")
        self.assertEqual(url, "ws://192.168.1.100:8000/ws?token=abc123")
    
    def test_make_ws_url_with_tls(self):
        """Test make_ws_url with TLS."""
        url = make_ws_url("192.168.1.100", 8000, "/ws", use_tls=True)
        self.assertEqual(url, "wss://192.168.1.100:8000/ws")
    
    def test_make_ws_url_with_tls_and_token(self):
        """Test make_ws_url with TLS and token."""
        url = make_ws_url("192.168.1.100", 8000, "/ws", "abc123", True)
        self.assertEqual(url, "wss://192.168.1.100:8000/ws?token=abc123")
    
    def test_discovery_service_initialization(self):
        """Test DiscoveryService initialization."""
        service = DiscoveryService(port=8000, path="/ws", token="abc123", use_tls=False)
        self.assertEqual(service.port, 8000)
        self.assertEqual(service.path, "/ws")
        self.assertEqual(service.token, "abc123")
        self.assertFalse(service.use_tls)
    
    def test_discovery_service_no_token(self):
        """Test DiscoveryService initialization without token."""
        service = DiscoveryService(port=8000, path="/ws")
        self.assertIsNone(service.token)
    
    @patch('hotpin.discovery.get_primary_ip')
    def test_discover_urls(self, mock_get_primary_ip):
        """Test URL discovery."""
        mock_get_primary_ip.return_value = "192.168.1.100"
        service = DiscoveryService(port=8000, path="/ws", token="abc123")
        urls = service.discover_urls()
        
        # Should have at least the primary URL
        self.assertGreater(len(urls), 0)
        self.assertIn("ws://192.168.1.100:8000/ws?token=abc123", urls)

if __name__ == '__main__':
    unittest.main()