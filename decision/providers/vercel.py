"""Vercel AI Gateway, for accounts that already bill through it.

Vercel documents the evaluation modality **through the AI SDK only** — "It is not supported
through the OpenAI-compatible, Anthropic-compatible, or Cohere-compatible endpoints" — so the
request below targets the gateway's own evaluation route rather than a published REST contract.
That makes this the less-supported of the two providers, and `docs/jev.md` says so plainly.
A Python caller that wants the documented contract should use the `typesafe` provider.

The gateway speaks the AI SDK's vocabulary, where TypeSafe's `noul` is called `boolean` and
comes back as `{type: "boolean", probability}`. This module is the only place that difference
exists; it normalises to TypeSafe's vocabulary on the way in and out, so the engine above sees
one shape. Everything about credentials, redirects, deadlines and error handling is shared with
`typesafe.py` rather than reimplemented — one place to get it right.
"""
import json

from .typesafe import _OPENER, credential, endpoint, send

PATH = "/v4/ai/evaluation-model"
SPEC_VERSION = "4"
PROTOCOL_VERSION = "0.0.1"


class VercelGatewayProvider:
    id = "vercel"

    def __init__(self, config, opener=None):
        self.config = config
        self._opener = opener or _OPENER.open

    @staticmethod
    def _out(questions):
        sent = {}
        for qid, q in questions.items():
            copy = dict(q)
            if copy.get("type") == "noul":
                copy["type"] = "boolean"
            sent[qid] = copy
        return sent

    @staticmethod
    def _back(answers):
        out = {}
        for qid, ans in answers.items():
            if not isinstance(ans, dict):
                continue
            if ans.get("type") == "boolean":
                out[qid] = {"type": "noul", "noul": ans.get("probability")}
            else:
                out[qid] = ans
        return out

    def evaluate(self, state, questions):
        from .typesafe import ProviderError, _int
        key = credential(self.config)
        body = json.dumps({"state": state, "questions": self._out(questions)}).encode()
        payload = send(self.config, endpoint(self.config, PATH),
                       {"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                        "ai-model-id": self.config.model,
                        "ai-evaluation-model-specification-version": SPEC_VERSION,
                        "ai-gateway-protocol-version": PROTOCOL_VERSION,
                        "User-Agent": "agent-dispatcher-decision/1.0"},
                       body, self._opener)
        answers = payload.get("answers")
        if not isinstance(answers, dict):
            raise ProviderError("provider response has no `answers` object")
        usage = payload.get("usage") or {}
        return {"answers": self._back(answers),
                "usage": {"input_tokens": _int(usage.get("inputTokens",
                                                         usage.get("input_tokens"))),
                          "output_tokens": _int(usage.get("outputTokens",
                                                          usage.get("output_tokens")))},
                "model": self.config.model}
