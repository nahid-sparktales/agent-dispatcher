def identity(token, settings):
    if token == "demo-session":
        return {"name": "member", "guest": False}
    if settings.allow_guest:
        return {"name": "guest", "guest": True}
    return None
