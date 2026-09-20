import unittest
from session_api.api import handle_request


class ExistingApiTests(unittest.TestCase):
    def test_member(self):
        self.assertEqual(handle_request("/profile", "demo-session")["body"],
                         {"name": "member", "guest": False})

    def test_public_health(self):
        self.assertEqual(handle_request("/health"), {"status": 200, "body": "ok"})
