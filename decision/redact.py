"""A conservative scrub of the task text before it leaves the machine.

This is a defensive layer, not a guarantee. Regexes catch the credential shapes that are
recognisable; they cannot catch a password that looks like a word, a customer name, or a
proprietary identifier. The real protection is in what the request carries at all — task text
and compact registry metadata, never file contents, environment or transcript. The
documentation says that rather than implying this function makes a request safe.

Two rules the patterns below follow, learned the hard way:

* **No ambiguous repetition.** `\\s*:?\\s*` over the same whitespace backtracks quadratically,
  so a pasted log of tab characters could hang the engine. Every optional run here is bounded.
* **Prose is not an assignment.** "the auth token is expired" is routing signal and must
  survive; "the password is hunter2hunter2" is a credential and must not. The prose form
  therefore only fires on a value that at least contains a digit.
"""
import re

PLACEHOLDER = "[redacted]"

_SECRET_WORD = r"(?:api[_-]?key|secret|token|password|passwd|passphrase|credential)s?"

# Ordered most specific first. Each pattern is a shape, not a dictionary of known secrets.
PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bvck_[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bey[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),  # JWT
    re.compile(r"\b[A-Za-z][A-Za-z0-9+.-]*://[^\s/@]+:[^\s/@]+@\S+"),                  # user:pass@
    # Authorization: Bearer x  /  x-api-key: x. Bounded runs, no nested optional whitespace.
    re.compile(r"(?i)\b(?:authorization|bearer)\b[\s:]{0,4}(?:bearer[ \t]{1,4})?"
               r"[\"']?[A-Za-z0-9_.\-+/=]{8,}"),
    # key = value / "api_key": "value"
    re.compile(r"(?i)\b" + _SECRET_WORD + r"\b[ \t]{0,4}[:=][ \t]{0,4}[\"']?[^\s\"',;]{6,}"),
    # The prose form — "the password is hunter2hunter2" — but only when the value carries a
    # digit, so "the token is expired" and "rotate the api key" stay intact.
    re.compile(r"(?i)\b" + _SECRET_WORD + r"\b[ \t]{1,4}(?:is|was)[ \t]{1,4}"
               r"[\"']?(?=[^\s\"',;]*\d)[^\s\"',;]{8,}"),
)


def scrub(text):
    """Return the text with recognisable credential shapes replaced."""
    if not text:
        return ""
    out = text
    for pattern in PATTERNS:
        out = pattern.sub(PLACEHOLDER, out)
    return out


def task_state(task, limit=2000):
    """The task, capped and scrubbed, as it will be sent.

    Capped *first*: scrubbing a 10MB paste before throwing 99.98% of it away is work nobody
    asked for, and it is the input size that makes any regex cost matter. A small headroom over
    the limit keeps a credential that straddles the boundary from being cut in half and
    surviving as two innocuous-looking halves.
    """
    text = (task or "")[: limit * 2]
    text = scrub(text).strip()
    if len(text) > limit:
        text = text[:limit].rstrip() + " …[truncated]"
    return text
