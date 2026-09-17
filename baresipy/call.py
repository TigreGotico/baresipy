"""Call metadata helpers.

Small, dependency-free data structures describing a single call, plus a SIP
URI parser used to populate them.
"""
from dataclasses import dataclass
from typing import Optional, Tuple
import re

_SIP_URI_RE = re.compile(
    r"^(?:sip:)?(?:(?P<user>[^@:;]+)@)?(?P<host>[^@:;]+)(?::\d+)?(?:;.*)?$")


def parse_sip_uri(uri: str) -> Tuple[Optional[str], Optional[str]]:
    """Parse a SIP URI (or bare `user@host`) into `(user, host)`.

    Handles `sip:user@host[:port][;params]` and bare `user@host` forms.
    Missing parts are returned as `None`. Best-effort - malformed input
    simply yields `(None, None)`.
    """
    if not uri:
        return None, None
    uri = uri.strip()
    match = _SIP_URI_RE.match(uri)
    if not match:
        return None, None
    return match.group("user"), match.group("host")


@dataclass
class CallInfo:
    uri: str
    user: Optional[str]
    host: Optional[str]
    direction: str  # "in" | "out"
    started: float
    ended: Optional[float] = None
    reason: Optional[str] = None
    dtmf: str = ""
