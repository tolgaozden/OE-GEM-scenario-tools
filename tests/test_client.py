import base64
import json
import ssl

import pytest
import requests

import oegem.client as oc
from oegem import OEClient, OEError
from oegem.client import TLSAdapter, build_session, quote_path, redact, resolve_tls_mode
from oegem.demo import FakeResponse, FakeSession

TOKEN = "test-token-0123456789-abcdefghij"


class StubSession:
    """Returns queued responses (or raises queued exceptions) and records each call."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def make_jwt(claims):
    def enc(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()
    return f"{enc({'alg': 'HS256', 'typ': 'JWT'})}.{enc(claims)}.c2lnbmF0dXJl"


@pytest.fixture
def sleeps(monkeypatch):
    recorded = []
    monkeypatch.setattr(oc.time, "sleep", lambda s: recorded.append(s))
    return recorded


def stub_client(*responses, **kw):
    session = StubSession(*responses)
    kw.setdefault("backoff", 0.0)
    return OEClient(TOKEN, session=session, **kw), session


def test_quote_path():
    assert quote_path("/oxford-economics/releases/Global Economic Model/") == \
        "oxford-economics/releases/Global%20Economic%20Model"
    assert quote_path("me//runs/x") == "me/runs/x"
    assert quote_path("shared/$Archive/a b") == "shared/%24Archive/a%20b"
    assert quote_path("/") == ""


def test_retries_transient_status_then_succeeds(sleeps):
    client, session = stub_client(FakeResponse(503, {"Message": "busy"}), FakeResponse(502),
                                  FakeResponse(200, {"ok": True}), retries=3, backoff=1.0)
    assert client.get("/v1/x") == {"ok": True}
    assert len(session.calls) == 3
    assert sleeps == [1.0, 2.0]


def test_retries_connection_errors_and_honours_retry_after(sleeps):
    client, session = stub_client(requests.ConnectionError("handshake dropped"),
                                  FakeResponse(429, headers={"Retry-After": "7"}),
                                  FakeResponse(200, {"n": 1}), retries=2, backoff=0.5)
    assert client.get("/v1/x") == {"n": 1}
    assert sleeps == [0.5, 7.0]


def test_retries_exhausted_raise_oeerror(sleeps):
    client, session = stub_client(*[FakeResponse(503, {"Message": "busy"}) for _ in range(4)], retries=3)
    with pytest.raises(OEError) as err:
        client.get("/v1/x")
    assert err.value.status == 503 and "4 attempt" in str(err.value)
    assert len(session.calls) == 4


def test_per_call_retry_override(sleeps):
    client, session = stub_client(FakeResponse(503), retries=5)
    with pytest.raises(OEError):
        client.request("POST", "/v1/operations/solve", json={}, retries=0)
    assert len(session.calls) == 1 and sleeps == []


def test_certificate_failure_is_not_retried(sleeps):
    exc = requests.exceptions.SSLError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")
    client, session = stub_client(exc, retries=5)
    with pytest.raises(OEError, match="OE_TLS"):
        client.get("/v1/x")
    assert len(session.calls) == 1


def test_bom_text_and_empty_bodies():
    client, _ = stub_client(FakeResponse(200, {"a": 1}), FakeResponse(200, text="plain text"), FakeResponse(204))
    assert client.get("/v1/a") == {"a": 1}  # FakeResponse adds a UTF-8 BOM by default
    assert client.get("/v1/b") == "plain text"
    assert client.get("/v1/c") is None
    assert FakeResponse(200, {"a": 1}).content.startswith(b"\xef\xbb\xbf")


def test_non_2xx_raises_with_status_url_and_truncated_body():
    client, session = stub_client(FakeResponse(404, {"Message": "No such forecast"}),
                                  FakeResponse(500, text="x" * 2000))
    with pytest.raises(OEError) as err:
        client.get("/v1/forecast-contents/abc")
    assert err.value.status == 404
    assert err.value.url.endswith("/v1/forecast-contents/abc")
    assert "No such forecast" in str(err.value)
    with pytest.raises(OEError) as err:
        client.get("/v1/y")
    assert err.value.status == 500 and len(err.value.body) == 800
    assert len(session.calls) == 2  # neither 404 nor 500 is retried


def test_token_never_leaks_into_errors_or_repr(sleeps):
    echo = f"bad request; Authorization: Bearer {TOKEN}; token={TOKEN}"
    client, _ = stub_client(FakeResponse(400, text=echo),
                            requests.ConnectionError(f"proxy said {TOKEN}"), retries=0)
    with pytest.raises(OEError) as err:
        client.get("/v1/x")
    for text in (str(err.value), repr(err.value), err.value.body, err.value.url):
        assert TOKEN not in text
    with pytest.raises(OEError) as err:
        client.get("/v1/y")
    assert TOKEN not in str(err.value)
    assert TOKEN not in repr(client) and TOKEN not in str(client)
    assert "***" in redact(f"Bearer {TOKEN}") and TOKEN not in redact(f"x {TOKEN} y", TOKEN)
    assert redact("Missing or invalid bearer token") == "Missing or invalid bearer token"


def test_missing_token_message(monkeypatch):
    monkeypatch.delenv("OE_TOKEN", raising=False)
    with pytest.raises(OEError) as err:
        OEClient(session=StubSession())
    msg = str(err.value)
    for needle in ("OE_TOKEN", "$env:OE_TOKEN", "export OE_TOKEN", "setenv", "demo"):
        assert needle in msg


def test_token_and_base_url_from_env(monkeypatch):
    monkeypatch.setenv("OE_TOKEN", f"  Bearer {TOKEN}  ")
    monkeypatch.setenv("OE_BASE_URL", "https://example.invalid/api/")
    session = StubSession(FakeResponse(200, {"Id": "x"}))
    client = OEClient(session=session)
    assert client.base_url == "https://example.invalid/api"
    client.resource("/me")
    method, url, kw = session.calls[0]
    assert url == "https://example.invalid/api/v1/resources/me"
    assert kw["headers"]["Authorization"] == f"Bearer {TOKEN}"


def test_absolute_url_on_other_host_is_refused():
    client, session = stub_client(FakeResponse(200))
    with pytest.raises(ValueError, match="Refusing"):
        client.get("https://elsewhere.invalid/v1/x")
    assert session.calls == []
    client.get(client.base_url + "/v1/ok")
    assert len(session.calls) == 1


def test_token_claims_and_repr_expiry():
    jwt = make_jwt({"sub": "user-1", "exp": 2000000000})
    client = OEClient(jwt, session=StubSession())
    assert client.token_claims == {"sub": "user-1", "exp": 2000000000}
    assert "expires 2033-05-18" in repr(client) and jwt not in repr(client)
    assert OEClient(TOKEN, session=StubSession()).token_claims == {}


def test_tls_modes(monkeypatch):
    with pytest.raises(ValueError, match="Unknown TLS mode"):
        resolve_tls_mode("bogus")
    session, mode = build_session("relaxed")
    adapter = session.get_adapter("https://model.example.invalid")
    assert mode == "relaxed" and isinstance(adapter, TLSAdapter)
    ctx = adapter._ssl_context
    assert not ctx.verify_flags & ssl.VERIFY_X509_STRICT
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname
    assert adapter.poolmanager.connection_pool_kw["ssl_context"] is ctx
    assert adapter.proxy_manager_for("http://proxy.example.invalid:8080").connection_pool_kw["ssl_context"] is ctx
    session, mode = build_session("default")
    assert mode == "default" and not isinstance(session.get_adapter("https://x.invalid"), TLSAdapter)
    monkeypatch.setenv("OE_TLS", "relaxed")
    assert OEClient(TOKEN).tls == "relaxed"
    monkeypatch.delenv("OE_TLS")
    assert resolve_tls_mode() == ("truststore" if oc._have_truststore() else "default")


def test_truststore_mode():
    truststore = pytest.importorskip("truststore")
    session, mode = build_session("truststore")
    adapter = session.get_adapter("https://x.invalid")
    assert mode == "truststore" and isinstance(adapter._ssl_context, truststore.SSLContext)


def test_demo_and_from_env(monkeypatch):
    client = OEClient.demo()
    assert client.is_demo and isinstance(client.session, FakeSession)
    assert client.whoami()["Path"] == "/me"
    monkeypatch.setenv("OEGEM_DEMO", "1")
    assert OEClient.from_env().is_demo
    monkeypatch.delenv("OEGEM_DEMO")
    monkeypatch.setenv("OE_TOKEN", TOKEN)
    real = OEClient.from_env()
    assert not real.is_demo and isinstance(real.session, requests.Session)
