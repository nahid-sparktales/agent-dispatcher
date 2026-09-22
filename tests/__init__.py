"""Agent Dispatcher test suite.

Project map and graph state is private and lives under the cache home. Every test process points
that at a throwaway directory, so no test reads or writes the developer's real ~/.cache state.
"""
import atexit
import os
import shutil
import tempfile

_CACHE_HOME = tempfile.mkdtemp(prefix="dispatcher-test-cache-")
os.environ["XDG_CACHE_HOME"] = _CACHE_HOME
atexit.register(shutil.rmtree, _CACHE_HOME, True)
