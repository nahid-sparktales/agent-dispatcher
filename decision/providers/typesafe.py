"""TypeSafe's documented HTTP API.

    POST {base}/v1/systemone
    Authorization: Bearer <TYPESAFE_API_KEY>
    Content-Type: application/json
    { "state": ..., "model": "jev-latest", "questions": { id: {type, instructions, criteria?} } }

    -> { "model": ..., "answers": { id: answer }, "usage": {input_tokens, output_tokens} }

Answer shapes: choice -> {type, choice, probabilities, confidence};
noul -> {type, noul}; score -> {type, score, legend, probabilities, confidence}.

Documented status codes: 401 invalid key, 422 bad body, 429 rate limited, 529 overloaded.
Reference: https://docs.typesafe.ai/api — checked against the published contract, not assumed.

stdlib `urllib` on purpose. Five small JSON posts do not justify adding an AI framework to a
repository whose whole promise is that it installs nothing. `send()` below is shared with the
gateway provider and is where every credential-safety rule actually lives.
"""
import json
import os
import re
import socket
import time
import urllib.error
import urllib.request

PATH = "/v1/systemone"

# A routing decision returns a few kilobytes. Anything past this is a misconfigured endpoint or
# something hostile, and reading it unbounded is how a decision call becomes a hang.
MAX_BODY_BYTES = 4 * 1024 * 1024

# RFC 9110 field values: visible ASCII plus space and tab. A key carrying anything else cannot
# go in a header at all — and a credential that reaches http.client malformed comes back inside
# a ValueError that quotes the whole header line.
_HEADER_SAFE = re.compile(r"\A[\x21-\x7e]+\Z")


class ProviderError(RuntimeError):
    """Never carries a credential.

    That is a property of how this class is raised, not a hope: every raise site below either
    uses a fixed string or interpolates something the provider itself produced. The one thing
    that could carry a key — an exception from deeper in the stack quoting the header — is
    caught and replaced rather than wrapped, and `from None` drops the chain so a traceback
    cannot resurrect it either.
    """


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects outright.

    urllib's default handler copies every header except content-type and content-length into
    the redirected request, so a 302 from a misconfigured or hostile base URL replays
    `Authorization: Bearer <key>` to whatever host the Location names. A decision endpoint has
    no legitimate reason to redirect.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def credential(config):
    """Read the key at send time. It is never stored, and never returned to a caller."""
    key = os.environ.get(config.credential_env, "").strip()
    if not key:
        raise ProviderError(f"no credential in {config.credential_env}")
    if not _HEADER_SAFE.match(key):
        # Say what is wrong without quoting any of it: a key pasted with a wrapped line is the
        # common cause, and the value is exactly what must not appear in this message.
        raise ProviderError(
            f"the credential in {config.credential_env} contains a character that cannot go in "
            f"an HTTP header (a line break or a space, most likely a paste artefact)")
    return key


def endpoint(config, path):
    url = config.base_url().rstrip("/") + path
    if not url.startswith("https://"):
        host = url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
        if host not in ("localhost", "127.0.0.1", "::1"):
            # Worded to survive its own scrub: `redact.py` treats "bearer <word>" as a
            # credential shape, so saying "bearer credential" here would redact the sentence.
            raise ProviderError(
                "the configured base URL is not https, so the request would carry an "
                "authorization header in cleartext. Unset the base-URL override, or point it "
                "at an https endpoint.")
    return url


def send(config, url, headers, body, opener):
    """One POST, with every failure mode turned into a ProviderError that carries no secret."""
    started = time.monotonic()
    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with opener(req, timeout=config.timeout_seconds) as resp:
            raw = resp.read(MAX_BODY_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise ProviderError(http_message(exc.code)) from None
    except urllib.error.URLError as exc:
        raise ProviderError(f"could not reach the provider ({exc.reason})") from None
    except (TimeoutError, socket.timeout):
        raise ProviderError("the provider did not answer in time") from None
    except ProviderError:
        raise
    except Exception:                                                 # noqa: BLE001
        # Deliberately total. Anything reaching here came from below our own code, and the one
        # thing it might quote is the request — headers included. The class name is safe to
        # keep; the message is not, so it is dropped rather than scrubbed.
        raise ProviderError("the request could not be sent") from None
    if len(raw) > MAX_BODY_BYTES:
        raise ProviderError("the provider returned an implausibly large response")
    # `timeout` is urllib's per-socket-read timeout, so a drip-feed can outlive it many times
    # over. This is the deadline that actually bounds the exchange.
    if time.monotonic() - started > config.timeout_seconds * 3:
        raise ProviderError("the provider did not answer in time")
    try:
        payload = json.loads(raw.decode("utf-8", errors="replace"),
                             parse_constant=_reject_constant)
    except (json.JSONDecodeError, ValueError):
        raise ProviderError("provider returned a body that is not JSON") from None
    if not isinstance(payload, dict):
        raise ProviderError("provider response is not a JSON object")
    return payload


def _reject_constant(name):
    # NaN and Infinity are valid to Python's parser and invalid everywhere downstream — they
    # break the JSON we emit and the percentages we render.
    raise ValueError(f"non-finite number {name} in the response")


def http_message(code):
    return {401: "the provider rejected the credential (401)",
            403: "the credential is not permitted to use this model (403)",
            404: "the model or endpoint was not found (404)",
            422: "the provider rejected the request body (422)",
            429: "rate limited by the provider (429)",
            529: "the provider is overloaded (529)"}.get(code, f"provider returned HTTP {code}")


# Kept under the old private name: vercel.py imported it before the shared `send` existed.
_http_message = http_message


class TypeSafeProvider:
    id = "typesafe"

    def __init__(self, config, opener=None):
        self.config = config
        self._opener = opener or _OPENER.open

    def evaluate(self, state, questions):
        key = credential(self.config)
        body = json.dumps({"state": state, "model": self.config.model,
                           "questions": questions}).encode()
        payload = send(self.config, endpoint(self.config, PATH),
                       {"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                        "User-Agent": "agent-dispatcher-decision/1.0"},
                       body, self._opener)
        if not isinstance(payload.get("answers"), dict):
            raise ProviderError("provider response has no `answers` object")
        usage = payload.get("usage") or {}
        return {"answers": payload["answers"],
                "usage": {"input_tokens": _int(usage.get("input_tokens")),
                          "output_tokens": _int(usage.get("output_tokens"))},
                "model": payload.get("model") or self.config.model}


def _int(value):
    return int(value) if isinstance(value, (int, float)) and value == value else 0
