"""Local GitHub App authentication for NoviqX.

The private key is loaded from a user-configured path at runtime. It must never
be committed, copied into the repository, or sent to an MCP client.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

import jwt


class NoviqXConfigurationError(RuntimeError):
    """Raised when required NoviqX configuration is missing or invalid."""


class NoviqXAuthenticationError(RuntimeError):
    """Raised when GitHub rejects the App authentication exchange."""


class GitHubAppAuth:
    """Create App JWTs and cache short-lived installation access tokens."""

    API_ROOT = "https://api.github.com"
    TOKEN_SKEW_SECONDS = 60

    def __init__(self, app_id=None, installation_id=None, private_key_path=None,
                 *, api_root=None, opener=None, clock=time.time):
        self.app_id = str(app_id or os.getenv("NOVIQX_APP_ID", "")).strip()
        self.installation_id = str(
            installation_id or os.getenv("NOVIQX_INSTALLATION_ID", "")
        ).strip()
        configured_path = private_key_path or os.getenv("NOVIQX_PRIVATE_KEY_PATH", "")
        self.private_key_path = Path(configured_path).expanduser() if configured_path else None
        self.api_root = (api_root or os.getenv("NOVIQX_API_URL") or self.API_ROOT).rstrip("/")
        self._opener = opener or urllib.request.urlopen
        self._clock = clock
        self._lock = threading.Lock()
        self._token = None
        self._token_expires_at = 0.0

    def _validate_config(self):
        if not self.app_id.isdigit():
            raise NoviqXConfigurationError("NOVIQX_APP_ID must be a numeric GitHub App ID.")
        if not self.installation_id.isdigit():
            raise NoviqXConfigurationError("NOVIQX_INSTALLATION_ID must be numeric.")
        if self.private_key_path is None:
            raise NoviqXConfigurationError("Set NOVIQX_PRIVATE_KEY_PATH to the local PEM file.")
        if not self.private_key_path.is_file():
            raise NoviqXConfigurationError("NoviqX private key file does not exist.")
        return self.private_key_path

    def create_app_jwt(self):
        """Sign a short-lived RS256 JWT for GitHub App authentication."""
        try:
            private_key = self._validate_config().read_text(encoding="utf-8")
            now = int(self._clock())
            return jwt.encode(
                {"iat": now - 30, "exp": now + 8 * 60, "iss": self.app_id},
                private_key, algorithm="RS256",
            )
        except (OSError, ValueError, jwt.PyJWTError) as exc:
            raise NoviqXAuthenticationError(
                f"Could not create NoviqX App JWT ({type(exc).__name__})."
            ) from exc

    def get_installation_token(self, *, force_refresh=False):
        """Return a cached installation token, refreshing it before expiration."""
        with self._lock:
            now = self._clock()
            if (not force_refresh and self._token
                    and now < self._token_expires_at - self.TOKEN_SKEW_SECONDS):
                return self._token

            app_jwt = self.create_app_jwt()
            request = urllib.request.Request(
                f"{self.api_root}/app/installations/{self.installation_id}/access_tokens",
                data=b"{}", method="POST",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {app_jwt}",
                    "X-GitHub-Api-Version": "2022-11-28",
                    "Content-Type": "application/json",
                    "User-Agent": "Nova-NoviqX-MCP",
                },
            )
            try:
                with self._opener(request, timeout=20) as response:
                    payload: dict[str, Any] = json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                raise NoviqXAuthenticationError(
                    f"GitHub rejected the installation-token request (HTTP {exc.code})."
                ) from exc
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                raise NoviqXAuthenticationError(
                    f"Could not obtain a GitHub installation token ({type(exc).__name__})."
                ) from exc

            token, expires_at = payload.get("token"), payload.get("expires_at")
            if not isinstance(token, str) or not token or not isinstance(expires_at, str):
                raise NoviqXAuthenticationError("GitHub returned an incomplete token response.")
            try:
                expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00")).timestamp()
            except ValueError as exc:
                raise NoviqXAuthenticationError("GitHub returned an invalid token expiry.") from exc
            self._token, self._token_expires_at = token, expiry
            return token
