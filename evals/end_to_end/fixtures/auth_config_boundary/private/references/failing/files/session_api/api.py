from session_api.auth import identity
from session_api.settings import load_settings


def handle_request(path, token=None, env=None):
    settings = load_settings({} if env is None else env)
    if path == "/health":
        return {"status": 200, "body": "ok"}
    if path != "/profile":
        return {"status": 404, "body": "not found"}
    user = identity(token, settings)
    if user is None:
        return {"status": 401, "body": "authentication required"}
    return {"status": 200, "body": user}
