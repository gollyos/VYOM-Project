from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import httpx

# Google's Desktop-app OAuth flow: no server-side redirect URI needed. The
# user completes consent in their own browser and pastes back the resulting
# `code` (or the whole redirected URL, which begin_oauth's caller already
# extracts via IntegrationRegistry's normal /oauth/callback contract) - the
# LOOPBACK redirect_uri below is what Google's "Desktop app" OAuth client
# type expects; it does not need to actually be served.
_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_LOOPBACK_REDIRECT = "http://localhost"


def _pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(40)).rstrip(b"=").decode("ascii")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    return verifier, challenge


@dataclass
class GoogleOAuthClient:
    """Shared Desktop-app OAuth2 + PKCE flow for any Google API surface
    (Gmail, Sheets, Calendar, ...). One client per (client_id, scopes) —
    Gmail and Sheets each construct their own instance with their own scope
    list, since Google's per-scope consent screen should only ever ask for
    what that specific integration actually needs.

    client_id/client_secret come from a "Desktop app" OAuth client the user
    creates once in Google Cloud Console (Credentials -> Create Credentials
    -> OAuth 2.0 Client ID -> Desktop app) and enables the relevant API for
    (Gmail API / Google Sheets API). Never fabricated or defaulted - a
    missing client_id/secret means the integration is simply unconfigured,
    matching this repo's `DisconnectedEmailProvider` pattern.
    """

    client_id: str
    client_secret: str
    scopes: tuple[str, ...]
    #: keyed by the `state` token begin_oauth() minted, so a code exchange
    #: can find the matching PKCE verifier even across process calls within
    #: the same run (IntegrationRegistry already tracks state -> integration
    #: id; this tracks state -> verifier for the PKCE half only).
    _pending: dict[str, str] = field(default_factory=dict)

    def authorization_url(self, state: str) -> str:
        verifier, challenge = _pkce_pair()
        self._pending[state] = verifier
        params = {
            "client_id": self.client_id,
            "redirect_uri": _LOOPBACK_REDIRECT,
            "response_type": "code",
            "scope": " ".join(self.scopes),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return f"{_AUTH_ENDPOINT}?{urlencode(params)}"

    @staticmethod
    def extract_code(raw: str) -> str:
        """Accepts either a bare authorization code or the full redirected
        URL the user copies from their browser address bar (the same
        forgiving contract the google-workspace Hermes skill uses, since
        users reliably paste the whole URL rather than parsing it themselves)."""
        raw = raw.strip()
        if "code=" not in raw:
            return raw
        from urllib.parse import parse_qs, urlparse

        parsed = urlparse(raw)
        query = parse_qs(parsed.query)
        codes = query.get("code")
        return codes[0] if codes else raw

    async def exchange_code(self, state: str, code: str) -> dict[str, Any]:
        code = self.extract_code(code)
        verifier = self._pending.pop(state, None)
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": _LOOPBACK_REDIRECT,
        }
        if verifier:
            payload["code_verifier"] = verifier
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(_TOKEN_ENDPOINT, data=payload)
        if response.status_code >= 400:
            raise RuntimeError(f"Google token exchange failed: HTTP {response.status_code}: {response.text[:300]}")
        return response.json()

    async def refresh(self, refresh_token: str) -> dict[str, Any]:
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(_TOKEN_ENDPOINT, data=payload)
        if response.status_code >= 400:
            raise RuntimeError(f"Google token refresh failed: HTTP {response.status_code}: {response.text[:300]}")
        return response.json()
