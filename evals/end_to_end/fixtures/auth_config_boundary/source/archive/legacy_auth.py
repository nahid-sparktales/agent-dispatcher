# Retired implementation; not imported by session_api.
def allow_guest(env):
    return bool(env.get("APP_ALLOW_GUEST", "true"))
