import unittest
from session_api.api import handle_request


class GuestSettingRegression(unittest.TestCase):
    def test_explicit_false_is_not_truthy(self):
        self.assertEqual(handle_request("/profile", env={"APP_ALLOW_GUEST": "false"})["status"], 401)

    def test_true_still_enables_guest(self):
        self.assertEqual(handle_request("/profile", env={"APP_ALLOW_GUEST": "true"})["status"], 200)
