"""HTTP layer for the Oxford Economics model web API.

`OEClient` sends authenticated requests and handles the API's quirks:

* The bearer token comes from the ``OE_TOKEN`` environment variable (or an
  argument). It is never logged, written to disk or shown in error messages.
* Transient failures (dropped connections, timeouts, HTTP 429/502/503/504) are
  retried with exponential backoff, because TLS-inspecting proxies drop
  handshakes now and then.
* Responses may start with a UTF-8 byte-order mark; it is stripped before JSON
  parsing.
* TLS: ``tls="auto"`` (the default) verifies certificates against the operating
  system's trust store through the optional ``truststore`` package, which is
  what corporate proxies usually need. ``"relaxed"`` keeps normal verification
  but clears the ``VERIFY_X509_STRICT`` flag (Python 3.13+ sets it and some
  proxy CAs fail it). ``"default"`` leaves requests' own settings alone.
  Verification is never disabled.
"""
from __future__ import annotations

import json as _json
import logging
import os
import re
import ssl
import time
from typing import Any, List, Optional, Tuple
from urllib.parse import quote, urlsplit

import requests
from requests.adapters import HTTPAdapter

log = logging.getLogger("oegem")

DEFAULT_BASE_URL = "https://model.oxfordeconomics.com/api"
TLS_MODES = ("auto", "truststore", "relaxed", "default")
RETRY_STATUS = (429, 502, 503, 504)
BODY_LIMIT = 800
MAX_DELAY = 60.0
TLS_HINT = (
    "If you are behind a TLS-inspecting proxy, set OE_TLS=truststore (pip install truststore) "
    "or OE_TLS=relaxed. Certificate verification is never switched off."
)
_STATUS_HINTS = {
    401: "token missing, invalid or expired: set a fresh OE_TOKEN (tokens last about 24 hours)",
    403: "your account is not allowed to do this on this resource",
    404: "not found: check the path, id or mnemonic",
}
_DETAIL_KEYS = ("Message", "message", "error_description", "Error", "error", "title", "detail", "FailureReason")
_RETRYABLE_EXC = (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError)
_BEARER_RE = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{16,}")  # token-length values only
_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]*")


class OEError(RuntimeError):
    """An Oxford Economics API call failed, or the client could not be set up.

    Attributes: status is the HTTP status (None for connection-level failures),
    url the request URL (it never contains the token), and body the response text,
    redacted and truncated to 800 characters.
    """

    def __init__(self, message: str, *, status: Optional[int] = None, url: str = "", body: str = ""):
        super().__init__(message)
        self.status = status
        self.url = url
        self.body = (body or "")[:BODY_LIMIT]


def redact(text, token: Optional[str] = None) -> str:
    """Return text with the token, any "Bearer ..." value and JWT-like strings replaced by ***."""
    if text is None:
        return ""
    out = str(text)
    if token and len(token) >= 4:
        out = out.replace(token, "***")
    out = _BEARER_RE.sub(r"\1***", out)
    return _JWT_RE.sub("***", out)


def quote_path(path: str) -> str:
    """Percent-encode each segment of a resource path, keeping the '/' separators.

    Leading/trailing slashes and empty segments are dropped, so "/me/runs/" gives
    "me/runs" and "Global Economic Model" gives "Global%20Economic%20Model". Pass
    plain (not already encoded) paths.
    """
    return "/".join(quote(seg, safe="") for seg in str(path).strip().split("/") if seg)


def response_text(resp) -> str:
    """Decode a response body as UTF-8 text with any byte-order mark removed."""
    raw = getattr(resp, "content", None)
    if isinstance(raw, (bytes, bytearray)):
        text = bytes(raw).decode("utf-8", errors="replace")
    else:
        text = getattr(resp, "text", "") or ""
    return text.lstrip("﻿")


def parse_body(resp) -> Any:
    """Parsed JSON (BOM stripped), the raw text if it is not JSON, or None for an empty body."""
    text = response_text(resp)
    if not text.strip():
        return None
    try:
        return _json.loads(text)
    except ValueError:
        return text


def as_records(payload, keys=("Items", "Results", "Data", "Value", "Indicators", "Groups")) -> List[dict]:
    """Return the list of dicts in an API payload (a bare list or a list under a wrapper key)."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in keys:
            if isinstance(payload.get(key), list):
                return as_records(payload[key], keys)
    return []


def _error_detail(body: str) -> str:
    try:
        data = _json.loads(body)
    except ValueError:
        text = " ".join(body.split())
        return "" if text.startswith("<") else text[:200]
    if isinstance(data, dict):
        for key in _DETAIL_KEYS:
            if isinstance(data.get(key), str) and data[key].strip():
                return data[key].strip()[:300]
    return ""


def _retry_after(resp) -> Optional[float]:
    value = (getattr(resp, "headers", None) or {}).get("Retry-After")
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------- TLS


class TLSAdapter(HTTPAdapter):
    """HTTPAdapter that hands one SSLContext to urllib3 for direct and proxied connections."""

    def __init__(self, ssl_context: ssl.SSLContext, **kwargs):
        self._ssl_context = ssl_context  # must exist before HTTPAdapter.__init__ builds the pool
        super().__init__(**kwargs)

    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = self._ssl_context
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, proxy, **proxy_kwargs):
        proxy_kwargs.setdefault("ssl_context", self._ssl_context)
        return super().proxy_manager_for(proxy, **proxy_kwargs)


def _have_truststore() -> bool:
    try:
        import truststore  # noqa: F401
    except Exception:
        return False
    return True


def resolve_tls_mode(tls: Optional[str] = None) -> str:
    """Turn a tls argument (or the OE_TLS variable) into "truststore", "relaxed" or "default"."""
    mode = str(tls if tls is not None else os.environ.get("OE_TLS") or "auto").strip().lower() or "auto"
    if mode not in TLS_MODES:
        raise ValueError(f"Unknown TLS mode {mode!r}: use one of {', '.join(TLS_MODES)} (argument tls= or OE_TLS).")
    if mode == "auto":
        return "truststore" if _have_truststore() else "default"
    return mode


def ssl_context_for(mode: str) -> Optional[ssl.SSLContext]:
    """SSLContext for a resolved TLS mode (None for "default"). Verification stays on."""
    if mode == "truststore":
        try:
            import truststore
        except Exception as exc:
            raise ValueError(
                "OE_TLS=truststore needs the truststore package: pip install truststore "
                "(or install the 'tls' extra)."
            ) from exc
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    if mode == "relaxed":
        ctx = ssl.create_default_context()
        try:  # add the CA bundle requests uses, so public CAs work on systems without an OS store
            ctx.load_verify_locations(requests.utils.DEFAULT_CA_BUNDLE_PATH)
        except Exception:
            pass
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
        return ctx
    return None


def build_session(tls: Optional[str] = None) -> Tuple[requests.Session, str]:
    """Return (requests.Session, resolved TLS mode) with the TLS mode applied to https:// URLs."""
    mode = resolve_tls_mode(tls)
    session = requests.Session()
    ctx = ssl_context_for(mode)
    if ctx is not None:
        session.mount("https://", TLSAdapter(ctx))
    return session, mode


# ------------------------------------------------------------------------- client


class OEClient:
    """Authenticated client for the Oxford Economics model web API.

    Args: token is the bearer token (default: the OE_TOKEN environment variable).
    base_url defaults to OE_BASE_URL or DEFAULT_BASE_URL. timeout is per request, in
    seconds. retries is the number of extra attempts for transient failures and backoff
    the first retry delay in seconds (doubled each time, capped at 60 s). session is a
    requests-compatible session to use instead of building one (demo mode passes
    oegem.demo.FakeSession); TLS settings are not applied to an injected session.
    tls is "auto", "truststore", "relaxed" or "default" (default: OE_TLS, else "auto").
    """

    def __init__(self, token=None, *, base_url=None, timeout=180, retries=5, backoff=2.0,
                 session=None, tls=None):
        from .auth import clean_token, missing_token_message, token_from_env

        tok = clean_token(token) if token is not None else token_from_env()
        if not tok:
            raise OEError(missing_token_message())
        self._token = tok
        self.base_url = str(base_url or os.environ.get("OE_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/")
        self.timeout = timeout
        self.retries = max(0, int(retries))
        self.backoff = max(0.0, float(backoff))
        self.is_demo = False
        if session is None:
            self.session, self.tls = build_session(tls)
        else:
            self.session, self.tls = session, "custom-session"

    @classmethod
    def demo(cls) -> "OEClient":
        """Client backed by the synthetic offline backend (numbers are NOT model output)."""
        from .demo import DEMO_BASE_URL, FakeSession, make_demo_token

        log.warning("DEMO MODE: synthetic offline backend (oegem.demo); numbers are NOT model output")
        client = cls(token=make_demo_token(), base_url=DEMO_BASE_URL, session=FakeSession(),
                     retries=2, backoff=0.0)
        client.is_demo = True
        client.tls = "demo"
        return client

    @classmethod
    def from_env(cls) -> "OEClient":
        """demo() if OEGEM_DEMO is "1"/"true", otherwise a normal client from OE_TOKEN."""
        if os.environ.get("OEGEM_DEMO", "").strip().lower() in ("1", "true", "yes", "on"):
            return cls.demo()
        return cls()

    def __repr__(self) -> str:
        from .auth import token_expiry

        exp = token_expiry(self._token)
        tok = "set" if exp is None else f"set, expires {exp:%Y-%m-%d %H:%M} UTC"
        demo = ", demo=True" if self.is_demo else ""
        return f"OEClient(base_url={self.base_url!r}, tls={self.tls!r}, token=<{tok}>{demo})"

    __str__ = __repr__

    def __enter__(self) -> "OEClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying session."""
        closer = getattr(self.session, "close", None)
        if callable(closer):
            closer()

    @property
    def token_claims(self) -> dict:
        """Claims of the token if it is a JWT ({} otherwise). Not verified; for expiry checks only."""
        from .auth import decode_jwt_claims

        return decode_jwt_claims(self._token)

    def _url(self, path: str) -> str:
        p = str(path).strip()
        if p.lower().startswith(("http://", "https://")):
            host = urlsplit(p).netloc.lower()
            if host != urlsplit(self.base_url).netloc.lower():
                raise ValueError(f"Refusing to send the API token to {host}: absolute URLs must start with {self.base_url}.")
            return p
        return f"{self.base_url}/{p.lstrip('/')}"

    def request(self, method: str, path: str, *, params=None, json=None, retries: Optional[int] = None) -> Any:
        """Send one API request and return the parsed body.

        Args: path is "/v1/..." relative to base_url, or an absolute URL on the same host.
        params and json are passed to requests. retries overrides the client setting for
        this call (e.g. 0 for a request that must not be repeated).
        Returns parsed JSON (BOM stripped), raw text if the body is not JSON, or None.
        Raises OEError for non-2xx responses and for transient failures that persist.
        """
        method = method.upper()
        url = self._url(path)
        headers = {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}
        attempts = 1 + (self.retries if retries is None else max(0, int(retries)))
        problem, status, last = "", None, None
        for attempt in range(1, attempts + 1):
            wait_hint = None
            try:
                resp = self.session.request(method, url, params=params, json=json, headers=headers,
                                            timeout=self.timeout)
            except _RETRYABLE_EXC as exc:
                status, last = None, None
                problem = redact(f"{type(exc).__name__}: {exc}", self._token)
                if "CERTIFICATE_VERIFY_FAILED" in problem:
                    raise OEError(f"{method} {url}: TLS certificate verification failed ({problem}). {TLS_HINT}",
                                  url=url) from None
            else:
                status, last = resp.status_code, resp
                if 200 <= status < 300:
                    return parse_body(resp)
                if status not in RETRY_STATUS:
                    raise self._http_error(method, url, resp)
                problem = f"HTTP {status}"
                wait_hint = _retry_after(resp)
            if attempt < attempts:
                wait = min(MAX_DELAY, self.backoff * 2 ** (attempt - 1))
                if wait_hint is not None:
                    wait = min(MAX_DELAY, max(wait, wait_hint))
                log.warning("%s %s: %s; retrying in %.1f s (attempt %d of %d)",
                            method, url, problem, wait, attempt + 1, attempts)
                time.sleep(wait)
        hint = f" {TLS_HINT}" if status is None and "SSL" in problem else ""
        body = redact(response_text(last), self._token) if last is not None else ""
        raise OEError(f"{method} {url} failed after {attempts} attempt(s): {problem}.{hint}",
                      status=status, url=url, body=body)

    def _http_error(self, method: str, url: str, resp) -> OEError:
        status = resp.status_code
        body = redact(response_text(resp), self._token)
        msg = f"{method} {url} -> HTTP {status}"
        detail = _error_detail(body)
        if detail:
            msg += f": {detail}"
        if status in _STATUS_HINTS:
            msg += f" ({_STATUS_HINTS[status]})"
        return OEError(msg, status=status, url=url, body=body)

    def get(self, path: str, params=None) -> Any:
        """GET path; see request()."""
        return self.request("GET", path, params=params)

    def post(self, path: str, json=None, params=None) -> Any:
        """POST a JSON body; see request()."""
        return self.request("POST", path, params=params, json=json)

    def put(self, path: str, json=None, params=None) -> Any:
        """PUT a JSON body; see request()."""
        return self.request("PUT", path, params=params, json=json)

    def patch(self, path: str, json=None, params=None) -> Any:
        """PATCH a JSON body; see request()."""
        return self.request("PATCH", path, params=params, json=json)

    def delete(self, path: str, params=None) -> Any:
        """DELETE path; see request()."""
        return self.request("DELETE", path, params=params)

    def resource(self, path: str) -> dict:
        """GET /v1/resources/<path>. Accepts "/me", "me/folder", or a release path."""
        quoted = quote_path(path)
        if not quoted:
            raise ValueError("Empty resource path: use 'me' for your workspace root or a release path.")
        return self.get(f"/v1/resources/{quoted}")

    def whoami(self) -> dict:
        """The user's own workspace root (resource "me")."""
        return self.resource("me")
