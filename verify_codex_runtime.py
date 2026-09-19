#!/usr/bin/env python3
"""Optional native Codex discovery check. No model request, credential, or hook execution.

Requires Codex CLI; the ordinary CI suite remains entirely offline and CLI-independent.
"""
import argparse
import json
from pathlib import Path
import queue
import shutil
import subprocess
import tempfile
import threading
import time

from build_codex import DEFAULT_OUTPUT


def verify(package):
    package = Path(package).resolve()
    skill = package / "skills/agent-dispatcher"
    if not (skill / "SKILL.md").is_file():
        raise ValueError("build the Codex package first with python3 build_codex.py")
    with tempfile.TemporaryDirectory(prefix="dispatcher-discovery-") as tmp:
        project = Path(tmp).resolve()
        installed = project / ".agents/skills/agent-dispatcher"
        shutil.copytree(skill, installed)
        messages = queue.Queue()
        proc = subprocess.Popen(["codex", "app-server", "--listen", "stdio://"], cwd=project,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True)

        def reader():
            for line in proc.stdout:
                try:
                    messages.put(json.loads(line))
                except ValueError:
                    pass

        threading.Thread(target=reader, daemon=True).start()

        def request(rid, method, params):
            proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}) + "\n")
            proc.stdin.flush()
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                reply = messages.get(timeout=max(0.1, deadline - time.monotonic()))
                if reply.get("id") == rid:
                    if "error" in reply:
                        raise RuntimeError(f"Codex rejected {method}: {reply['error']}")
                    return reply["result"]
            raise TimeoutError(f"Codex did not answer {method}")

        try:
            request(1, "initialize", {"clientInfo": {"name": "dispatcher_validation", "version": "1.0"}})
            proc.stdin.write('{"jsonrpc":"2.0","method":"initialized","params":{}}\n')
            proc.stdin.flush()
            result = request(2, "skills/list", {"cwds": [str(project)], "forceReload": True})
            found, errors = [], []
            for entry in result["data"]:
                found.extend(s for s in entry["skills"] if str(installed) in s.get("path", ""))
                errors.extend(e for e in entry.get("errors", []) if str(installed) in e.get("path", ""))
            if errors or len(found) != 1 or found[0]["name"] != "agent-dispatcher":
                raise RuntimeError(f"unexpected Codex skill discovery: {len(found)} skills, errors={errors}")
            print("Codex discovered agent-dispatcher with no package errors; supporting guides stayed out of discovery.")
        finally:
            proc.stdin.close()
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    verify(args.package)
