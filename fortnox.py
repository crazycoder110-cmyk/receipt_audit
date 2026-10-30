"""Fortnox: OAuth2 sign-in + upload matched receipts to the voucher inbox, where the accountant books them.

Docs: https://www.fortnox.se/developer. Access tokens live 1 hour; the refresh token rotates on every refresh,
so whoever holds the token must keep the newest one (on_refresh).

One-time connect for the nightly CLI:  python fortnox.py   (saves fortnox_token.json, gitignored)
"""
from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, quote, urlencode, urlparse

import requests

AUTH_URL = "https://apps.fortnox.se/oauth-v1/auth"
TOKEN_URL = "https://apps.fortnox.se/oauth-v1/token"
API = "https://api.fortnox.se/3"
SCOPES = "inbox archive connectfile"
INBOX = "Inbox_v"          # "Inkorg verifikationer": documents waiting to be booked as vouchers
ACCEPTED = {"pdf": "application/pdf", "jpg": "image/jpeg", "jpeg": "image/jpeg", "tif": "image/tiff",
            "tiff": "image/tiff"}
TOKEN_FILE = Path(os.getenv("FORTNOX_TOKEN_FILE", "fortnox_token.json"))


def configured() -> bool:
    return bool(os.getenv("FORTNOX_CLIENT_ID") and os.getenv("FORTNOX_CLIENT_SECRET"))


def redirect_uri() -> str:
    return os.getenv("FORTNOX_REDIRECT_URI") or os.getenv("REDIRECT_URI", "http://localhost:8501")


def auth_url(state: str) -> str:
    return AUTH_URL + "?" + urlencode({
        "client_id": os.environ["FORTNOX_CLIENT_ID"], "redirect_uri": redirect_uri(), "scope": SCOPES,
        "state": state, "access_type": "offline", "response_type": "code"}, quote_via=quote)


def _token(**data: str) -> dict:
    r = requests.post(TOKEN_URL, data=data, timeout=20,
                      auth=(os.environ["FORTNOX_CLIENT_ID"], os.environ["FORTNOX_CLIENT_SECRET"]))
    if not r.ok:
        raise RuntimeError(f"Fortnox sign-in failed ({r.status_code}): {r.text[:200]}")
    token = r.json()
    token["expires_at"] = time.time() + int(token.get("expires_in", 3600)) - 60
    return token


def exchange(code: str) -> dict:
    return _token(grant_type="authorization_code", code=code, redirect_uri=redirect_uri())


class Fortnox:
    def __init__(self, token: dict, on_refresh: Callable[[dict], None] | None = None):
        self.token, self.on_refresh = token, on_refresh

    def _headers(self) -> dict:
        if time.time() > self.token.get("expires_at", 0):
            self.token = _token(grant_type="refresh_token", refresh_token=self.token["refresh_token"])
            if self.on_refresh:
                self.on_refresh(self.token)
        return {"Authorization": f"Bearer {self.token['access_token']}", "Accept": "application/json"}

    def upload(self, filename: str, content: bytes) -> str:
        """Put a receipt in the Fortnox voucher inbox. Returns the Fortnox file id."""
        mime = ACCEPTED.get(filename.rsplit(".", 1)[-1].lower())
        if not mime:
            raise ValueError("Fortnox accepts PDF, JPG and TIF only")
        r = requests.post(f"{API}/inbox", params={"path": INBOX}, headers=self._headers(), timeout=60,
                          files={"file": (filename, content, mime)})
        if not r.ok:
            raise RuntimeError(f"Fortnox upload failed ({r.status_code}): {r.text[:200]}")
        return str(r.json()["File"]["Id"])


def save_token(token: dict) -> None:
    TOKEN_FILE.write_text(json.dumps(token))
    TOKEN_FILE.chmod(0o600)


def from_saved_token() -> Fortnox | None:
    if not (configured() and TOKEN_FILE.exists()):
        return None
    return Fortnox(json.loads(TOKEN_FILE.read_text()), on_refresh=save_token)


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv(".env")
    state = secrets.token_urlsafe(16)
    print("1. Open this link and allow access:\n\n" + auth_url(state) + "\n")
    url = input("2. Paste the full address you were sent back to: ").strip()
    query = parse_qs(urlparse(url).query)
    if query.get("state", [""])[0] != state:
        raise SystemExit("State does not match, start again.")
    save_token(exchange(query["code"][0]))
    print(f"Connected. Token saved to {TOKEN_FILE}")
