from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    allow_guest: bool = False


def load_settings(env):
    if "APP_ALLOW_GUEST" not in env:
        return Settings()
    raw = env["APP_ALLOW_GUEST"].strip().lower()
    if raw in ("true", "1", "yes"):
        return Settings(allow_guest=True)
    if raw in ("false", "0", "no"):
        return Settings(allow_guest=False)
    raise ValueError("invalid APP_ALLOW_GUEST value")
