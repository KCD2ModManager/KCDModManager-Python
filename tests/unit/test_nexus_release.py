"""scripts/nexus_release.py against a fake transport (no network, no real key)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("nexus_release", ROOT / "scripts" / "nexus_release.py")
assert _spec and _spec.loader
nexus = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nexus)

KEY = "test-key-not-real"


class FakeNexus:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object] | None]] = []
        self.parts: list[bytes] = []
        self.polls = 0

    def __call__(
        self, method: str, url: str, body: bytes | None, headers: dict[str, str]
    ) -> tuple[int, dict[str, str], bytes]:
        if url.startswith("https://storage/"):
            if url.startswith("https://storage/part"):
                self.parts.append(body or b"")
                return 200, {"ETag": f'"etag{len(self.parts)}"'}, b""
            assert b"<ETag>etag1</ETag>" in (body or b"")
            return 200, {}, b""
        assert headers["apikey"] == KEY
        path = url.removeprefix(nexus.API_BASE)
        payload = json.loads(body) if body else None
        self.calls.append((method, path, payload))
        routes: dict[tuple[str, str], object] = {
            ("GET", "/games/kingdomcomedeliverance2/mods/187"): {"id": "mod-uuid", "game_scoped_id": "187"},
            ("GET", "/games/kingdomcomedeliverance2/mod-file-versions/936370"): {
                "id": "ver-uuid",
                "file": {"id": "file-uuid", "name": "Portable"},
            },
            ("POST", "/uploads/multipart"): {
                "id": "upload-uuid",
                "part_size_bytes": 4,
                "part_presigned_urls": ["https://storage/part1", "https://storage/part2"],
                "complete_presigned_url": "https://storage/complete",
            },
            ("POST", "/uploads/upload-uuid/finalise"): {"id": "upload-uuid", "state": "created"},
            ("POST", "/mod-files"): {
                "id": "new-file",
                "game_scoped_id": "1",
                "name": "x",
                "file_category": "main",
            },
            ("GET", "/mod-files/new-file/versions"): {"versions": [{"id": "v", "game_scoped_id": "999001"}]},
        }
        if (method, path) == ("GET", "/uploads/upload-uuid"):
            self.polls += 1
            data: object = {"id": "upload-uuid", "state": "available" if self.polls > 1 else "created"}
        elif (method, path) in routes:
            data = routes[(method, path)]
        else:
            return 404, {}, b'{"title": "not found"}'
        return 200, {}, json.dumps({"data": data}).encode()


def test_resolve_maps_website_ids_to_v3_ids() -> None:
    client = nexus.Client(KEY, FakeNexus())
    assert client.mod_id("kingdomcomedeliverance2", "187") == "mod-uuid"
    assert client.file_id("kingdomcomedeliverance2", "936370") == "file-uuid"


def test_create_file_uploads_in_parts_and_reports_website_id(tmp_path: Path) -> None:
    archive = tmp_path / "linux.zip"
    archive.write_bytes(b"12345678")
    fake = FakeNexus()
    result = nexus.Client(KEY, fake, poll_seconds=0).create_file(
        "mod-uuid", archive, "KCD Mod Manager 5.0.0 (Linux)", "5.0.0", "Linux build"
    )
    assert result == {"file_id": "new-file", "file_version_website_id": "999001"}
    assert fake.parts == [b"1234", b"5678"]
    create = next(payload for method, path, payload in fake.calls if path == "/mod-files")
    assert create is not None
    assert create["upload_id"] == "upload-uuid" and create["mod_id"] == "mod-uuid"
    assert create["file_category"] == "main" and create["version"] == "5.0.0"


def test_errors_never_include_the_key() -> None:
    client = nexus.Client(KEY, FakeNexus())
    with pytest.raises(nexus.NexusError) as error:
        client.mod_id("kingdomcomedeliverance2", "404")
    assert "404" in str(error.value) and KEY not in str(error.value)


def test_missing_key_is_reported(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.delenv("NEXUSMODS_API_KEY", raising=False)
    assert nexus.main(["resolve", "--game", "x", "--mod", "1"]) == 1
    assert "NEXUSMODS_API_KEY" in capsys.readouterr().err
