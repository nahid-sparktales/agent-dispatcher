from flowdesk.service import TaskService
from flowdesk.storage import MemoryTaskStore


def handle_request(method, path, payload=None, store=None):
    service = TaskService(store if store is not None else MemoryTaskStore())
    if method == "GET" and path == "/tasks":
        return service.list_tasks()
    if method == "POST" and path == "/tasks":
        return service.add_task(payload["title"])
    raise ValueError("unsupported route")
