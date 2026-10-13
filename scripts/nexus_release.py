"""Nexus Mods v3 helpers for the release workflow (documented endpoints only, see api-docs.nexusmods.com).

The API key is read from ``NEXUSMODS_API_KEY`` and never printed.

    # Website IDs (as shown on the mod page) -> v3 IDs used by the upload endpoints
    python scripts/nexus_release.py resolve --game kingdomcomedeliverance2 --mod 187 --file-version 936370

    # First upload of an entirely new file on a mod page
    python scripts/nexus_release.py create-file --mod-id <v3 mod id> --path build.zip \
        --name "KCD Mod Manager 5.0.0 (Linux)" --version 5.0.0 --description "..."

Both commands write ``key=value`` lines to ``$GITHUB_OUTPUT`` when set, otherwise to stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

API_BASE = os.environ.get("NEXUSMODS_API_BASE", "https://api.nexusmods.com/v3").rstrip("/")
USER_AGENT = "KCDModManager-release"


class NexusError(RuntimeError):
    pass


Transport = Callable[[str, str, bytes | None, dict[str, str]], tuple[int, dict[str, str], bytes]]


def urllib_transport(
    method: str, url: str, body: bytes | None, headers: dict[str, str]
) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


class Client:
    def __init__(
        self, api_key: str, transport: Transport = urllib_transport, poll_seconds: float = 2.0
    ) -> None:
        if not api_key:
            raise NexusError("NEXUSMODS_API_KEY is not set")
        self._key = api_key
        self._transport = transport
        self._poll_seconds = poll_seconds

    # ------------------------------------------------------------------ plumbing
    def _api(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        headers = {"apikey": self._key, "User-Agent": USER_AGENT, "Content-Type": "application/json"}
        body = json.dumps(payload).encode() if payload is not None else None
        status, _headers, data = self._transport(method, f"{API_BASE}{path}", body, headers)
        if not 200 <= status < 300:
            raise NexusError(f"{method} {path} failed: {status} {data.decode(errors='replace')[:500]}")
        return json.loads(data)["data"] if data else None

    def _raw(self, method: str, url: str, body: bytes, headers: dict[str, str]) -> dict[str, str]:
        status, response_headers, data = self._transport(method, url, body, headers)
        if not 200 <= status < 300:
            raise NexusError(f"{method} to storage failed: {status} {data.decode(errors='replace')[:300]}")
        return response_headers

    # ------------------------------------------------------------------ lookups
    def mod_id(self, game: str, game_scoped_id: str) -> str:
        return str(self._api("GET", f"/games/{game}/mods/{game_scoped_id}")["id"])

    def file_id(self, game: str, version_game_scoped_id: str) -> str:
        version = self._api("GET", f"/games/{game}/mod-file-versions/{version_game_scoped_id}")
        return str(version["file"]["id"])

    def file_versions(self, file_id: str) -> list[dict[str, Any]]:
        return list(self._api("GET", f"/mod-files/{file_id}/versions")["versions"])

    # ------------------------------------------------------------------ upload
    def upload(self, path: Path) -> str:
        """Multipart upload (same flow as Nexus-Mods/upload-action); returns the upload ID once available."""
        size = path.stat().st_size
        session = self._api("POST", "/uploads/multipart", {"filename": path.name, "size_bytes": str(size)})
        part_size = int(session["part_size_bytes"])
        parts: list[tuple[int, str]] = []
        with path.open("rb") as handle:
            for number, url in enumerate(session["part_presigned_urls"], start=1):
                chunk = handle.read(part_size)
                headers = self._raw(
                    "PUT",
                    url,
                    chunk,
                    {"Content-Type": "application/octet-stream", "Content-Length": str(len(chunk))},
                )
                etag = next((v for k, v in headers.items() if k.lower() == "etag"), "")
                if not etag:
                    raise NexusError(f"no ETag returned for part {number}")
                parts.append((number, etag.replace('"', "")))
                print(f"uploaded part {number}/{len(session['part_presigned_urls'])}")
        xml = (
            "<CompleteMultipartUpload>\n"
            + "\n".join(
                f"  <Part>\n    <PartNumber>{n}</PartNumber>\n    <ETag>{e}</ETag>\n  </Part>"
                for n, e in parts
            )
            + "\n</CompleteMultipartUpload>"
        )
        self._raw(
            "POST", session["complete_presigned_url"], xml.encode(), {"Content-Type": "application/xml"}
        )
        upload_id = str(session["id"])
        self._api("POST", f"/uploads/{upload_id}/finalise")
        delay = self._poll_seconds
        for _attempt in range(60):
            if self._api("GET", f"/uploads/{upload_id}")["state"] == "available":
                return upload_id
            time.sleep(delay)
            delay = min(delay * 1.5, 30.0)
        raise NexusError(f"upload {upload_id} did not become available")

    def create_file(
        self, mod_id: str, path: Path, name: str, version: str, description: str, category: str = "main"
    ) -> dict[str, str]:
        """Creates an entirely new file on a mod page; returns its v3 ID and the website ID of its version."""
        upload_id = self.upload(path)
        created = self._api(
            "POST",
            "/mod-files",
            {
                "upload_id": upload_id,
                "mod_id": mod_id,
                "name": name,
                "version": version,
                "description": description,
                "file_category": category,
                "primary_mod_manager_download": False,
                "allow_mod_manager_download": True,
                "show_requirements_pop_up": False,
                "update_mod_version": False,
            },
        )
        file_id = str(created["id"])
        versions = self.file_versions(file_id)
        website_id = str(versions[-1]["game_scoped_id"]) if versions else ""
        return {"file_id": file_id, "file_version_website_id": website_id}


def _emit(values: dict[str, str]) -> None:
    target = os.environ.get("GITHUB_OUTPUT")
    lines = "".join(f"{key}={value}\n" for key, value in values.items())
    if target:
        with Path(target).open("a", encoding="utf-8") as handle:
            handle.write(lines)
    print(lines, end="")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    resolve = commands.add_parser("resolve")
    resolve.add_argument("--game", required=True, help="game domain, e.g. kingdomcomedeliverance2")
    resolve.add_argument("--mod", required=True, help="mod ID from the mod page URL")
    resolve.add_argument("--file-version", default="", help="file ID shown in the Files tab")
    create = commands.add_parser("create-file")
    create.add_argument("--mod-id", required=True, help="v3 mod ID (from resolve)")
    create.add_argument("--path", type=Path, required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--version", required=True)
    create.add_argument("--description", default="")
    create.add_argument("--category", default="main", choices=("main", "optional", "miscellaneous"))
    args = parser.parse_args(argv)

    try:
        client = Client(os.environ.get("NEXUSMODS_API_KEY", ""))
        if args.command == "resolve":
            values = {"mod_id": client.mod_id(args.game, args.mod)}
            if args.file_version:
                values["file_id"] = client.file_id(args.game, args.file_version)
            _emit(values)
        else:
            _emit(
                client.create_file(
                    args.mod_id, args.path, args.name, args.version, args.description, args.category
                )
            )
    except NexusError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
