# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.

"""
HTTP request guards for the local DeskAgent server.

Two checks protect the local API against hostile web pages the user visits:

- Host check (blocks DNS rebinding): a request is only served when its Host
  header names this machine's loopback address. A page on attacker.example
  that re-resolves its domain to 127.0.0.1 still sends "Host: attacker.example"
  and is rejected.
- Origin check (blocks cross-site requests): state-changing requests
  (POST/PUT/PATCH/DELETE) that carry a browser Origin header must come from
  the DeskAgent UI itself. Non-browser clients (MCP servers, Stream Deck,
  curl) send no Origin header and are not affected.

Network mode (DESKAGENT_BIND_HOST=0.0.0.0, e.g. Docker): additional host
names are allowed via DESKAGENT_ALLOWED_HOSTS (comma-separated, e.g.
"deskagent.example.com,192.168.1.20"). Without that list the host check is
skipped in network mode, because the operator exposed the server on purpose.
"""

import os
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from starlette.responses import PlainTextResponse

LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def safe_join(base: Path, name: str) -> Optional[Path]:
    """Join a user-supplied relative path onto base; None if it escapes base."""
    try:
        base_resolved = base.resolve()
        target = (base_resolved / name).resolve()
    except (OSError, ValueError):
        return None
    if not target.is_relative_to(base_resolved):
        return None
    return target


def _split_host(value: str) -> str:
    """Return the host part of a Host header or netloc, lowercased, without port."""
    value = value.strip().lower()
    if value.startswith("["):  # [::1]:8765
        end = value.find("]")
        return value[1:end] if end > 0 else value
    if value.count(":") == 1:
        return value.split(":", 1)[0]
    return value


def _configured_hosts() -> set:
    raw = os.environ.get("DESKAGENT_ALLOWED_HOSTS", "")
    return {_split_host(h) for h in raw.split(",") if h.strip()}


class LocalRequestGuard:
    """ASGI middleware enforcing the Host and Origin checks described above."""

    def __init__(self, app):
        self.app = app
        bind_host = os.environ.get("DESKAGENT_BIND_HOST", "localhost").strip().lower()
        extra = _configured_hosts()
        self.allowed_hosts = LOOPBACK_HOSTS | extra
        # Network mode without an explicit list: the operator exposed the
        # server deliberately, so the Host check cannot know valid names.
        self.check_host = bind_host in LOOPBACK_HOSTS or bool(extra)

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        host_header = headers.get("host", "")
        host = _split_host(host_header)

        if self.check_host and host not in self.allowed_hosts:
            return await self._reject(scope, receive, send, "Invalid Host header")

        origin = headers.get("origin")
        method = scope.get("method", "GET").upper()
        if origin is not None and (method in UNSAFE_METHODS or scope["type"] == "websocket"):
            if not self._origin_allowed(origin, host_header):
                return await self._reject(scope, receive, send, "Cross-origin request blocked")

        return await self.app(scope, receive, send)

    def _origin_allowed(self, origin: str, host_header: str) -> bool:
        if origin == "null":
            return False
        parts = urlsplit(origin)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            return False
        origin_host = _split_host(parts.netloc)
        if origin_host in LOOPBACK_HOSTS:
            return True
        # Same-origin UI served under its own host name (network mode). The
        # Host header itself already passed the Host check above.
        return parts.netloc.lower() == host_header.strip().lower()

    async def _reject(self, scope, receive, send, message: str):
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        response = PlainTextResponse(message, status_code=403)
        await response(scope, receive, send)
