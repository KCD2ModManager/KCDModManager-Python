"""Nexus Mods single sign-on (websocket protocol 2), as used by the original manager.

Flow: connect to ``wss://sso.nexusmods.com``, send ``{"id": <uuid>, "token": null, "protocol": 2}``,
open ``https://www.nexusmods.com/sso?id=<uuid>&application=kcd2mm`` in the browser and wait for
``{"success": true, "data": {"api_key": ...}}``.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from collections.abc import Callable

from websockets.exceptions import WebSocketException
from websockets.sync.client import connect

from kcd_mod_manager.infrastructure.nexus import APPLICATION_NAME, NexusError

log = logging.getLogger(__name__)

SSO_SOCKET_URL = "wss://sso.nexusmods.com"
SSO_PAGE_URL = "https://www.nexusmods.com/sso?id={id}&application={app}"


class SsoCancelled(NexusError):
    pass


def request_api_key(
    open_browser: Callable[[str], None],
    cancelled: threading.Event,
    timeout_seconds: float = 300.0,
    socket_url: str = SSO_SOCKET_URL,
) -> str:
    session_id = str(uuid.uuid4())
    waited = 0.0
    try:
        with connect(socket_url, open_timeout=15) as socket:
            socket.send(json.dumps({"id": session_id, "token": None, "protocol": 2}))
            open_browser(SSO_PAGE_URL.format(id=session_id, app=APPLICATION_NAME))
            while waited < timeout_seconds:
                if cancelled.is_set():
                    raise SsoCancelled("Login cancelled")
                try:
                    message = socket.recv(timeout=1.0)
                except TimeoutError:
                    waited += 1.0
                    continue
                try:
                    payload = json.loads(message)
                except (TypeError, ValueError):
                    continue
                if not isinstance(payload, dict):
                    continue
                if not payload.get("success", False):
                    raise NexusError(str(payload.get("error") or "SSO request rejected"))
                data = payload.get("data") or {}
                api_key = data.get("api_key") if isinstance(data, dict) else None
                if isinstance(api_key, str) and api_key:
                    return api_key
    except (OSError, WebSocketException) as exc:
        raise NexusError(f"SSO connection failed: {type(exc).__name__}") from exc
    raise NexusError("SSO login timed out")
