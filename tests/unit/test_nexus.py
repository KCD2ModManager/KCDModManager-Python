from __future__ import annotations

import json
import threading
from pathlib import Path

import httpx
import pytest

from kcd_mod_manager.application.nexus_account import NexusAccount
from kcd_mod_manager.application.session import ManagerSession
from kcd_mod_manager.application.settings import AppSettings
from kcd_mod_manager.domain.models import GameType
from kcd_mod_manager.infrastructure import app_updates
from kcd_mod_manager.infrastructure.credentials import MemoryCredentialStore
from kcd_mod_manager.infrastructure.nexus import (
    NexusAuthError,
    NexusClient,
    NexusPremiumRequired,
    NexusRateLimited,
    latest_file,
)
from tests.conftest import make_mod

FILES = {
    "files": [
        {"file_id": 1, "version": "1.0", "uploaded_timestamp": 100, "name": "old", "mod_version": "1.0"},
        {"file_id": 2, "version": "1.1", "uploaded_timestamp": 300, "name": "new", "mod_version": "1.2"},
        {"file_id": 3, "version": "0.9", "uploaded_timestamp": 200, "name": "mid", "mod_version": ""},
    ],
    "file_updates": [],
}


def client_with(handler) -> tuple[NexusClient, list[httpx.Request]]:  # type: ignore[no-untyped-def]
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return NexusClient(lambda: "KEY123", transport=httpx.MockTransport(wrapped)), seen


def test_files_and_latest() -> None:
    client, seen = client_with(lambda r: httpx.Response(200, json=FILES))
    files = client.mod_files("kingdomcomedeliverance2", 187)
    assert seen[0].url.path == "/v1/games/kingdomcomedeliverance2/mods/187/files.json"
    assert seen[0].headers["apikey"] == "KEY123"
    newest = latest_file(files)
    assert newest is not None and newest.file_id == 2 and newest.effective_version == "1.2"


def test_validate() -> None:
    payload = {"user_id": 7, "name": "henry", "email": "h@example.com", "is_premium": True}
    client, seen = client_with(lambda r: httpx.Response(200, json=payload))
    user = client.validate("OTHERKEY")
    assert (user.user_id, user.name, user.is_premium) == (7, "henry", True)
    assert seen[0].headers["apikey"] == "OTHERKEY"


@pytest.mark.parametrize(
    ("status", "error"), [(401, NexusAuthError), (403, NexusPremiumRequired), (429, NexusRateLimited)]
)
def test_error_mapping(status: int, error: type[Exception]) -> None:
    client, _ = client_with(lambda r: httpx.Response(status, json={}))
    with pytest.raises(error):
        client.mod_files("d", 1)


@pytest.mark.parametrize(
    "payload", [[{"URI": "https://cdn/x.zip"}], {"URI": "https://cdn/x.zip"}, "https://cdn/x.zip"]
)
def test_download_link_shapes(payload: object) -> None:
    client, seen = client_with(lambda r: httpx.Response(200, json=payload))
    assert client.download_link("d", 5, 9) == "https://cdn/x.zip"
    assert seen[0].url.path == "/v1/games/d/mods/5/files/9/download_link.json"


def test_endorse_uses_post() -> None:
    client, seen = client_with(lambda r: httpx.Response(200, json={"status": "Endorsed"}))
    client.endorse("d", 5)
    assert seen[0].method == "POST" and seen[0].url.path.endswith("/mods/5/endorse.json")


def test_has_endorsed_reads_the_users_endorsements() -> None:
    payload = [
        {"mod_id": 187, "domain_name": "kingdomcomedeliverance2", "status": "Endorsed"},
        {"mod_id": 2119, "domain_name": "kingdomcomedeliverance", "status": "Abstained"},
        {"mod_id": "bad", "domain_name": "kingdomcomedeliverance2"},
        "noise",
    ]
    client, seen = client_with(lambda r: httpx.Response(200, json=payload))
    assert client.has_endorsed("kingdomcomedeliverance2", 187)
    assert not client.has_endorsed("kingdomcomedeliverance", 2119)
    assert not client.has_endorsed("kingdomcomedeliverance2", 1)
    assert seen[0].method == "GET" and seen[0].url.path == "/v1/user/endorsements.json"


def test_app_update_check_uses_the_python_release_repository() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json={"tag_name": "v9.0.0"})

    update = app_updates.check_for_app_update("5.1.0", transport=httpx.MockTransport(handler))
    assert seen == ["/repos/KCD2ModManager/KCDModManager-Python/releases/latest"]
    assert update is not None and update.latest_version == "9.0.0"
    assert app_updates.manager_page(GameType.KCD1).endswith("/kingdomcomedeliverance/mods/2119")
    assert app_updates.manager_page(None).endswith("/kingdomcomedeliverance2/mods/187")


def test_missing_key() -> None:
    client = NexusClient(lambda: None, transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    with pytest.raises(NexusAuthError):
        client.mod_files("d", 1)


def test_session_update_checks(session: ManagerSession) -> None:
    make_mod(session.mods_dir, "alpha", "1.0")
    make_mod(session.mods_dir, "beta", "2.0")
    make_mod(session.mods_dir, "skipped", "1.0")
    session.reload()
    session.set_mod_number(session.mods[0], 10)
    session.set_mod_number(session.mods[1], 20)
    client, seen = client_with(lambda r: httpx.Response(200, json=FILES))
    session.nexus = client
    summary = session.check_all_updates()
    assert summary.checked == 2 and [m.id for m in summary.updates] == ["alpha"]
    assert session.mods[0].has_update and session.mods[0].latest_version == "1.2"
    assert len(seen) == 2


def test_session_update_checks_stop_on_rate_limit(session: ManagerSession) -> None:
    for name in ("a", "b"):
        make_mod(session.mods_dir, name)
    session.reload()
    for i, mod in enumerate(session.mods, start=1):
        session.set_mod_number(mod, i)
    client, seen = client_with(lambda r: httpx.Response(429))
    session.nexus = client
    summary = session.check_all_updates(threading.Event())
    assert summary.rate_limited and len(seen) == 1


def test_account_refresh_and_logout() -> None:
    settings = AppSettings()
    saved: list[bool] = []
    creds = MemoryCredentialStore("KEY")
    client = NexusClient(
        creds.get,
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"user_id": 1, "name": "n", "email": "e", "is_premium": False})
        ),
    )
    account = NexusAccount(settings, lambda: saved.append(True), creds, client)
    user = account.refresh()
    assert user is not None and settings.nexus_username == "n" and saved
    account.logout()
    assert creds.get() is None and settings.nexus_username == "" and not account.is_logged_in


def test_account_refresh_revoked_key_logs_out() -> None:
    settings = AppSettings(nexus_username="old")
    creds = MemoryCredentialStore("KEY")
    client = NexusClient(creds.get, transport=httpx.MockTransport(lambda r: httpx.Response(401)))
    account = NexusAccount(settings, lambda: None, creds, client)
    assert account.refresh() is None
    assert creds.get() is None and settings.nexus_username == ""


def test_app_update_check() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"tag_name": "v9.0"}))
    update = app_updates.check_for_app_update("5.0.0", transport=transport)
    assert update is not None and update.latest_version == "9.0"
    same = httpx.MockTransport(lambda r: httpx.Response(200, json={"tag_name": "v5.0.0"}))
    assert app_updates.check_for_app_update("5.0.0", transport=same) is None
    failing = httpx.MockTransport(lambda r: httpx.Response(500))
    assert app_updates.check_for_app_update("5.0.0", transport=failing) is None


def test_settings_never_contain_token(tmp_path: Path) -> None:
    from kcd_mod_manager.bootstrap import build_context
    from kcd_mod_manager.infrastructure.app_paths import AppPaths

    creds = MemoryCredentialStore("SUPERSECRETKEY")
    ctx = build_context(AppPaths(tmp_path / "data"), credentials=creds)
    ctx.session.save_settings()
    assert "SUPERSECRETKEY" not in (tmp_path / "data" / "settings.json").read_text()
    assert json.loads((tmp_path / "data" / "settings.json").read_text())["schema_version"] == 1
