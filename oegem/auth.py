"""Token helpers: read OE_TOKEN, inspect a token's expiry, fetch a token by password grant.

Tokens live in the ``OE_TOKEN`` environment variable only. Nothing here writes a
token to disk or logs it, and `token_status` reports expiry without the token.
The password grant needs the authorisation server details of your own Oxford
Economics account (``OE_AUTH_DOMAIN``, ``OE_AUTH_CLIENT_ID`` and, if your setup
uses one, ``OE_AUTH_AUDIENCE``); the package ships no defaults for them.
"""
from __future__ import annotations

import base64
import json
import os
import re
from datetime import datetime, timezone
from typing import Optional

import requests

from .client import OEError, parse_body, redact, response_text

AUTH_ENV_VARS = ("OE_AUTH_DOMAIN", "OE_AUTH_CLIENT_ID", "OE_AUTH_AUDIENCE")


def missing_token_message(var: str = "OE_TOKEN") -> str:
    """How-to text shown when no token is available."""
    return (
        f"No Oxford Economics API token found in the {var} environment variable.\n"
        "Copy a bearer token from your Oxford Economics model account (tokens last about 24 hours)\n"
        "and set it for the current session:\n"
        f'  PowerShell:  $env:{var} = "<token>"\n'
        f'  bash/zsh:    export {var}="<token>"\n'
        f'  MATLAB:      setenv("{var}", "<token>")\n'
        "With password login and the OE_AUTH_* variables set, `oegem auth token` can fetch one.\n"
        "To try the tools without a token use demo mode: `oegem --demo ...` or set OEGEM_DEMO=1."
    )


def clean_token(token) -> str:
    """Strip whitespace, surrounding quotes and a leading "Bearer " from a pasted token."""
    t = str(token or "").strip().strip('"').strip("'").strip()
    if t.lower().startswith("bearer "):
        t = t[7:].strip()
    return t


def token_from_env(var: str = "OE_TOKEN") -> str:
    """Return the cleaned token from environment variable var; OEError with a how-to if missing."""
    token = clean_token(os.environ.get(var))
    if not token:
        raise OEError(missing_token_message(var))
    return token


def decode_jwt_claims(token) -> dict:
    """Decode a JWT's payload without verifying it; {} if the token is not a JWT."""
    try:
        parts = clean_token(token).split(".")
        if len(parts) < 2 or not parts[1]:
            return {}
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")).decode("utf-8"))
    except Exception:
        return {}
    return claims if isinstance(claims, dict) else {}


def token_expiry(token) -> Optional[datetime]:
    """Expiry time from the JWT "exp" claim as a UTC-aware datetime, or None."""
    exp = decode_jwt_claims(token).get("exp")
    try:
        return datetime.fromtimestamp(float(exp), tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def token_status(token, *, now: Optional[datetime] = None) -> dict:
    """Summary of a token without the token itself.

    Returns {"present", "expires_at" (ISO 8601 UTC or None), "expires_in_minutes", "expired"};
    the last three are None when the expiry cannot be read. now is for testing.
    """
    present = bool(clean_token(token))
    exp = token_expiry(token) if present else None
    if exp is None:
        return {"present": present, "expires_at": None, "expires_in_minutes": None, "expired": None}
    now = now or datetime.now(timezone.utc)
    minutes = (exp - now).total_seconds() / 60.0
    return {"present": True, "expires_at": exp.isoformat(), "expires_in_minutes": round(minutes, 1),
            "expired": minutes <= 0}


def fetch_token_password_grant(username, password, *, domain=None, client_id=None, audience=None,
                               scope="openid profile", timeout=30, session=None) -> str:
    """Fetch an access token with the OAuth password grant.

    Args: username and password of your account. domain, client_id and audience default to
    OE_AUTH_DOMAIN, OE_AUTH_CLIENT_ID and OE_AUTH_AUDIENCE; domain and client_id are required,
    audience is sent only when given. session is an optional requests-like session (default:
    one built with the OE_TLS setting). Returns the access token; the caller decides where it
    goes (normally the OE_TOKEN variable of the current shell). Raises ValueError for missing
    settings and OEError if the server refuses.
    """
    domain = str(domain or os.environ.get("OE_AUTH_DOMAIN") or "").strip()
    client_id = str(client_id or os.environ.get("OE_AUTH_CLIENT_ID") or "").strip()
    audience = str(audience or os.environ.get("OE_AUTH_AUDIENCE") or "").strip()
    missing = [name for name, value in (("OE_AUTH_DOMAIN", domain), ("OE_AUTH_CLIENT_ID", client_id)) if not value]
    if missing:
        raise ValueError(
            f"Password login needs {' and '.join(missing)}. These values come from your Oxford Economics "
            "account setup (ask your account administrator) and must be supplied as environment variables "
            "(OE_AUTH_DOMAIN, OE_AUTH_CLIENT_ID, optionally OE_AUTH_AUDIENCE). The package has no defaults."
        )
    if not username or not password:
        raise ValueError("Password login needs both a username and a password.")
    host = re.sub(r"^https?://", "", domain, flags=re.IGNORECASE).strip("/")
    url = f"https://{host}/oauth/token"
    body = {"grant_type": "password", "username": username, "password": password,
            "client_id": client_id, "scope": scope}
    if audience:
        body["audience"] = audience
    if session is None:
        from .client import build_session

        session, _ = build_session()

    def scrub(text) -> str:
        return redact(str(text).replace(str(password), "***"))

    try:
        resp = session.post(url, json=body, timeout=timeout)
    except requests.RequestException as exc:
        raise OEError(f"Token request to {url} failed: {type(exc).__name__}: {scrub(exc)}", url=url) from None
    data = parse_body(resp)
    if not 200 <= resp.status_code < 300:
        detail = ""
        if isinstance(data, dict):
            detail = str(data.get("error_description") or data.get("error") or "")
        raise OEError(f"Token request refused: HTTP {resp.status_code} {scrub(detail)}".strip(),
                      status=resp.status_code, url=url, body=scrub(response_text(resp)))
    token = data.get("access_token") if isinstance(data, dict) else None
    if not token:
        raise OEError("Token response contained no access_token.", status=resp.status_code, url=url)
    return str(token)
