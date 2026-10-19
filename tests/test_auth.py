import base64
import json
from datetime import datetime, timedelta, timezone

import pytest

from oegem import OEError
from oegem.auth import (clean_token, decode_jwt_claims, fetch_token_password_grant, token_expiry,
                        token_from_env, token_status)
from oegem.demo import FakeResponse

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)


def enc(obj) -> str:
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()


def make_jwt(claims) -> str:
    """A fake, unsigned JWT built for the test (not a credential)."""
    return f"{enc({'alg': 'HS256', 'typ': 'JWT'})}.{enc(claims)}.c2lnbmF0dXJl"


class PostRecorder:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, json=None, timeout=None, **kw):
        self.calls.append((url, json))
        return self.response


@pytest.fixture
def no_auth_env(monkeypatch):
    for var in ("OE_AUTH_DOMAIN", "OE_AUTH_CLIENT_ID", "OE_AUTH_AUDIENCE"):
        monkeypatch.delenv(var, raising=False)


def test_decode_jwt_claims():
    claims = {"sub": "user-1", "exp": 2000000000, "name": "Test"}
    assert decode_jwt_claims(make_jwt(claims)) == claims
    assert decode_jwt_claims("Bearer " + make_jwt(claims)) == claims
    for bad in ("not-a-jwt", "", None, "a.!!!.c", f"a.{enc([1, 2])}.c"):
        assert decode_jwt_claims(bad) == {}


def test_token_expiry_is_utc_aware():
    exp = token_expiry(make_jwt({"exp": 2000000000}))
    assert exp == datetime(2033, 5, 18, 3, 33, 20, tzinfo=timezone.utc)
    assert exp.tzinfo is not None
    assert token_expiry("opaque-token") is None
    assert token_expiry(make_jwt({"exp": "soon"})) is None


def test_token_status_never_contains_token():
    future = make_jwt({"exp": int((NOW + timedelta(minutes=90)).timestamp())})
    status = token_status(future, now=NOW)
    assert status == {"present": True, "expires_at": "2030-01-01T13:30:00+00:00",
                      "expires_in_minutes": 90.0, "expired": False}
    assert future not in json.dumps(status)
    past = make_jwt({"exp": int((NOW - timedelta(minutes=5)).timestamp())})
    assert token_status(past, now=NOW)["expired"] is True
    assert token_status("opaque-token") == {"present": True, "expires_at": None,
                                            "expires_in_minutes": None, "expired": None}
    assert token_status(None)["present"] is False and token_status("  ")["present"] is False


def test_token_from_env(monkeypatch):
    monkeypatch.delenv("OE_TOKEN", raising=False)
    with pytest.raises(OEError, match="OE_TOKEN"):
        token_from_env()
    monkeypatch.setenv("OE_TOKEN", "  'abc-token'  ")
    assert token_from_env() == "abc-token"
    monkeypatch.setenv("MY_TOKEN", "Bearer xyz")
    assert token_from_env("MY_TOKEN") == "xyz"
    assert clean_token(' "Bearer  q1" ') == "q1"


def test_password_grant_refuses_without_settings(no_auth_env):
    recorder = PostRecorder(FakeResponse(200, {"access_token": "never"}))
    with pytest.raises(ValueError) as err:
        fetch_token_password_grant("demo-user", "pw-123", session=recorder)
    assert "OE_AUTH_DOMAIN" in str(err.value) and "OE_AUTH_CLIENT_ID" in str(err.value)
    assert recorder.calls == []


def test_password_grant_posts_to_configured_domain(no_auth_env, monkeypatch):
    monkeypatch.setenv("OE_AUTH_DOMAIN", "https://auth.example.invalid/")
    monkeypatch.setenv("OE_AUTH_CLIENT_ID", "test-client")
    recorder = PostRecorder(FakeResponse(200, {"access_token": "fake-tok-123", "expires_in": 86400}))
    assert fetch_token_password_grant("demo-user", "pw-123", session=recorder) == "fake-tok-123"
    url, body = recorder.calls[0]
    assert url == "https://auth.example.invalid/oauth/token"
    assert body["grant_type"] == "password" and body["client_id"] == "test-client"
    assert "audience" not in body
    monkeypatch.setenv("OE_AUTH_AUDIENCE", "https://api.example.invalid")
    fetch_token_password_grant("demo-user", "pw-123", session=recorder)
    assert recorder.calls[1][1]["audience"] == "https://api.example.invalid"


def test_password_grant_errors_hide_password(no_auth_env):
    refused = FakeResponse(403, {"error": "invalid_grant", "error_description": "Wrong password pw-123"})
    with pytest.raises(OEError) as err:
        fetch_token_password_grant("u", "pw-123", domain="auth.example.invalid", client_id="c",
                                   session=PostRecorder(refused))
    assert err.value.status == 403
    assert "pw-123" not in str(err.value) and "pw-123" not in err.value.body
    with pytest.raises(ValueError, match="username and a password"):
        fetch_token_password_grant("u", "", domain="auth.example.invalid", client_id="c",
                                   session=PostRecorder(refused))
    with pytest.raises(OEError, match="no access_token"):
        fetch_token_password_grant("u", "pw", domain="d.invalid", client_id="c",
                                   session=PostRecorder(FakeResponse(200, {"token_type": "Bearer"})))
