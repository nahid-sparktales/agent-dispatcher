"""A deterministic provider, so the suite and the evals never need a paid call.

`script` is a list of behaviours consumed one per request, which is how the fallback tests
reproduce a timeout, a 429, a malformed body or an id that does not exist without a network.
"""
import json
import urllib.error

from .typesafe import ProviderError

BEHAVIOURS = ("ok", "timeout", "rate-limit", "server-error", "auth-error", "malformed",
              "empty", "unknown-candidate", "low-confidence")


class MockProvider:
    """A test double. `config.PROVIDERS` does not list it, so it is unreachable by
    configuration — the only way in is `service(provider_instance=MockProvider(...))`, which
    is a call only this suite and the eval harness make."""

    id = "mock"

    def __init__(self, config, answers=None, script=(), usage=None):
        self.config = config
        self.answers = answers or {}
        self.script = list(script)
        self.usage = usage or {"input_tokens": 0, "output_tokens": 0}
        self.calls = []

    def _next(self):
        return self.script.pop(0) if self.script else "ok"

    def evaluate(self, state, questions):
        self.calls.append({"state": state, "questions": questions})
        behaviour = self._next()
        if behaviour == "timeout":
            raise ProviderError("could not reach the provider (timed out)")
        if behaviour == "rate-limit":
            raise ProviderError("rate limited by the provider (429)")
        if behaviour == "server-error":
            raise ProviderError("the provider is overloaded (529)")
        if behaviour == "auth-error":
            raise ProviderError("the provider rejected the credential (401)")
        if behaviour == "malformed":
            raise ProviderError("provider returned a body that is not JSON")
        if behaviour == "empty":
            return {"answers": {}, "usage": self.usage, "model": self.config.model}

        answers = {}
        for qid, q in questions.items():
            if qid in self.answers:
                answers[qid] = self.answers[qid]
                continue
            if q.get("type") == "choice":
                options = list(q.get("criteria", {}))
                pick = "quantum-database-wizard" if behaviour == "unknown-candidate" else (
                    options[0] if options else "")
                conf = 0.12 if behaviour == "low-confidence" else 0.93
                probs = {o: (1.0 if o == pick else 0.0) for o in options}
                answers[qid] = {"type": "choice", "choice": pick, "confidence": conf,
                                "probabilities": probs}
            elif q.get("type") == "score":
                answers[qid] = {"type": "score", "score": 1.0, "confidence": 0.5,
                                "probabilities": {}}
            else:
                answers[qid] = {"type": "noul", "noul": 0.9}
        return {"answers": answers, "usage": self.usage, "model": self.config.model}


class HTTPMock:
    """A urlopen stand-in for the two real providers, so their wire handling is tested too."""

    def __init__(self, status=200, body=None, raises=None):
        self.status, self.body, self.raises = status, body, raises
        self.requests = []

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        if self.raises:
            raise self.raises
        if self.status >= 400:
            raise urllib.error.HTTPError(req.full_url, self.status, "err", {}, None)
        payload = self.body if isinstance(self.body, (str, bytes)) else json.dumps(self.body)
        return _Resp(payload.encode() if isinstance(payload, str) else payload)


class _Resp:
    def __init__(self, data):
        self._data = data

    def read(self, size=-1):
        return self._data if size is None or size < 0 else self._data[:size]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False
