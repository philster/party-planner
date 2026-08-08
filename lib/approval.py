"""The approval token that binds a human "yes" to an exact insert body.

`build_payload` prints the token to stderr; the agent shows the payload to the
user, and on approval passes the token to `create_event`, which recomputes it
over whatever body it actually reads. A payload swapped in between -- the
classic /tmp race against a predictable filename -- no longer matches, so the
write is refused.

The token travels through the agent's context, not through the filesystem: an
attacker who can rewrite the payload file could rewrite a token file beside it
just as easily.

  from approval import token_for, matches
"""
import hashlib
import hmac
import json

PREFIX = "sha256:"
MIN_LEN = 16  # accept a shortened token; 16 hex chars = 64 bits


def token_for(body):
    """Canonical (whitespace- and key-order-independent) digest of an insert
    body, so re-serialization between the two scripts cannot break the match."""
    canon = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return PREFIX + hashlib.sha256(canon.encode("utf-8")).hexdigest()


def matches(supplied, body):
    """True when `supplied` is the token for `body` (full digest or a >=16-char
    prefix of it). Comparison is constant-time to keep the check boring."""
    if not isinstance(supplied, str):
        return False
    given = supplied.strip().lower()
    if given.startswith(PREFIX):
        given = given[len(PREFIX):]
    expected = token_for(body)[len(PREFIX):]
    if len(given) < MIN_LEN or len(given) > len(expected):
        return False
    return hmac.compare_digest(given, expected[:len(given)])
