# Generated historical snapshot. Editing it does not change the live application.
def load_settings(env):
    return {"allow_guest": bool(env.get("APP_ALLOW_GUEST", False))}
