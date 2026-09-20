def load_settings(env):
    return {"allow_guest": env.get("APP_ALLOW_GUEST") == "true"}
