import unittest
from flowdesk.api import handle_request
from flowdesk.storage import MemoryTaskStore


class ApiTests(unittest.TestCase):
    def test_create_then_list(self):
        store = MemoryTaskStore()
        self.assertEqual(handle_request("POST", "/tasks", {"title": "  ship  "}, store),
                         {"id": 1, "title": "ship"})
        self.assertEqual(handle_request("GET", "/tasks", store=store),
                         [{"id": 1, "title": "ship"}])
