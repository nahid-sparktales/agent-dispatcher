from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    allow_guest: bool = False


def load_settings(env):
    return Settings(allow_guest=bool(env.get("APP_ALLOW_GUEST", False)))
