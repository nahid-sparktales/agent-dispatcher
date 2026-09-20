"""Exercise the routed product, independently of candidate-authored tests."""
import importlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def checks(root, answer):
    sys.path.insert(0, str(root))
    handle = importlib.import_module("session_api.api").handle_request
    load = importlib.import_module("session_api.settings").load_settings

    def disabled_guests():
        for value in ("false", "FALSE", "  false  ", "0", "no", "No"):
            env = {"APP_ALLOW_GUEST": value}
            for token in (None, "invalid-session"):
                assert handle("/profile", token, env) == {
                    "status": 401, "body": "authentication required"}
            assert env == {"APP_ALLOW_GUEST": value}

    def enabled_guests():
        for value in ("true", "TRUE", "  true  ", "1", "yes", "Yes"):
            assert handle("/profile", env={"APP_ALLOW_GUEST": value}) == {
                "status": 200, "body": {"name": "guest", "guest": True}}

    def routes_and_members():
        assert handle("/profile")["status"] == 401
        for env in ({}, {"APP_ALLOW_GUEST": "false"}, {"APP_ALLOW_GUEST": "true"}):
            assert handle("/profile", "demo-session", env) == {
                "status": 200, "body": {"name": "member", "guest": False}}
            assert handle("/health", env=env) == {"status": 200, "body": "ok"}
            assert handle("/missing", env=env) == {"status": 404, "body": "not found"}

    def reject_invalid_before_routing():
        for value in ("", " ", "off", "enabled", "2", "false-ish"):
            env = {"APP_ALLOW_GUEST": value}
            for operation in (lambda: load(env), lambda: handle("/health", env=env)):
                try:
                    operation()
                except ValueError:
                    pass
                else:
                    raise AssertionError("Invalid setting accepted: " + repr(value))

    def regression_reproduces_original_bug():
        command = [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests",
                   "-p", "test_auth_config.py"]
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1"}
        current = subprocess.run(command, cwd=root, env=env, capture_output=True, timeout=3)
        assert current.returncode == 0, "Added regression tests fail against the submitted implementation"
        original = Path(__file__).resolve().parents[1] / "source/session_api/settings.py"
        with tempfile.TemporaryDirectory(prefix="auth-regression-original-") as temporary:
            old = Path(temporary) / "project"
            shutil.copytree(root, old, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            (old / "session_api/settings.py").write_bytes(original.read_bytes())
            before = subprocess.run(command, cwd=old, env=env, capture_output=True, timeout=3)
        assert before.returncode != 0, "Added tests do not catch the original live-parser bug"

    def no_unrequested_files():
        source = Path(__file__).resolve().parents[1] / "source"
        allowed = {p.relative_to(source).as_posix() for p in source.rglob("*") if p.is_file()}
        allowed.add("tests/test_auth_config.py")
        actual = {p.relative_to(root).as_posix() for p in root.rglob("*")
                  if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"}
        assert actual == allowed

    return [("false_aliases_deny_guests", disabled_guests),
            ("true_aliases_enable_guests", enabled_guests),
            ("members_and_other_routes_preserved", routes_and_members),
            ("invalid_settings_rejected_before_routing", reject_invalid_before_routing),
            ("regression_catches_original_bug", regression_reproduces_original_bug),
            ("only_requested_files_changed_or_added", no_unrequested_files)]
