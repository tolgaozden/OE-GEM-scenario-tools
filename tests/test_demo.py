import json
import re
import zlib

import pytest
import requests

import oegem.demo as demo
from oegem import OEClient, OEError
from oegem.demo import (ANNUAL_ONLY_GROUPS, INDICATORS, SOLVE_ROUTE, FakeResponse, FakeSession, annualise,
                        indicator_kind, synthetic_series, toy_equation)
from oegem.periods import period_range


def first_release_id(session):
    return session.forecast_id(demo.EXTENSION + "/Demo26_2 5yr")


def test_docstring_says_synthetic():
    doc = demo.__doc__.upper()
    assert "SYNTHETIC" in doc and "NOT OXFORD ECONOMICS MODEL OUTPUT" in doc


def test_series_are_deterministic_and_seeded_by_pair():
    a, b = synthetic_series("GDP", "US"), synthetic_series("GDP", "US")
    assert a == b and a is not b
    assert synthetic_series("GDP", "CHINA") != a and synthetic_series("CPI", "US") != a
    one, two = FakeSession(), FakeSession()
    assert one.get_series(first_release_id(one), "AAA", "ALPHA") == two.get_series(first_release_id(two), "AAA", "ALPHA")
    assert demo._seed("GDP", "US") == zlib.crc32(b"GDP:US")  # stable across runs, unlike hash()


def test_coverage_and_magnitudes():
    q = synthetic_series("GDP", "US")
    assert {"2015Q1", "2035Q4"} <= set(q) and list(q) == period_range("2010Q1", "2035Q4")
    assert "2050Q4" in synthetic_series("GDP", "US", end="2050Q4")
    for item in INDICATORS:
        values = list(synthetic_series(item["Code"], "KOREA").values())
        kind = indicator_kind(item["Code"])
        if kind == "rate":
            assert all(0.0 <= v <= 10.0 for v in values)
        elif kind == "shock":
            assert set(values) == {0.0}
        else:
            assert all(30.0 <= v <= 60000.0 for v in values), item["Code"]


def test_annual_only_group():
    assert ANNUAL_ONLY_GROUPS == ("BETA",)
    s = FakeSession()
    fid = first_release_id(s)
    assert s.values(fid, "GDP", "BETA") == {}
    annual = s.values(fid, "GDP", "BETA", annual=True)
    assert list(annual)[:2] == ["2010", "2011"]
    us = s.values(fid, "GDP", "US", annual=True)
    assert us["2026"] == annualise(s.values(fid, "GDP", "US"))["2026"]


def test_raw_responses_have_bom_and_need_auth():
    s = FakeSession()
    url = demo.DEMO_BASE_URL + "/v1/resources/me"
    unauth = s.request("GET", url)
    assert unauth.status_code == 401
    ok = s.request("GET", url, headers={"Authorization": "Bearer x-demo"})
    assert ok.status_code == 200 and ok.content.startswith(b"\xef\xbb\xbf")
    with pytest.raises(ValueError):
        ok.json()  # like requests with an explicit utf-8 charset: the BOM breaks plain json()
    assert json.loads(ok.content.decode("utf-8-sig"))["Path"] == "/me"
    assert FakeResponse(200, {"a": 1}, bom=False).json() == {"a": 1}


def test_values_endpoint_limits_and_shapes(client, release):
    url = f"/v1/forecast-contents/{release['Id']}/variables"
    body = [{"IndicatorCode": "GDP", "GroupCode": "BETA", "Frequency": "Annual"}]
    item = client.post(url, json=body, params={"onlyProps": "Values"})[0]
    assert item["Values"][0]["Period"] == "2010-01-01T00:00:00"
    too_many = [{"IndicatorCode": f"X{i}", "GroupCode": "US"} for i in range(401)]
    with pytest.raises(OEError) as err:
        client.post(url, json=too_many)
    assert err.value.status == 400 and "400" in str(err.value)
    with pytest.raises(OEError) as err:
        client.get("/v1/forecast-contents/not-a-forecast/indicators")
    assert err.value.status == 404


def test_model_variables_toy_equations(client, release):
    url = f"/v1/forecast-contents/{release['Id']}/model-variables"
    body = [{"IndicatorCode": c, "GroupCode": "ALPHA"} for c in ("AAA", "BBB", "CCC", "DDD", "GGG")]
    items = {i["IndicatorCode"]: i for i in client.post(url, json=body,
                                                        params={"onlyProps": "Equations,Residuals,Metadata"})}
    assert isinstance(items["AAA"]["Equations"], str) and "&AAA:ALPHA" in items["AAA"]["Equations"]
    assert isinstance(items["BBB"]["Equations"], list) and "BBB:ALPHA[-1]" in items["BBB"]["Equations"][0]
    assert "Expression" in items["CCC"]["Equations"] and "S(AAA:ALPHA, 4)" in items["CCC"]["Equations"]["Expression"]
    assert items["DDD"]["Equations"][0]["Equation"].startswith("EXP(0.5 * LN(EEE:ALPHA)")
    assert items["GGG"]["Equations"] == [] and items["GGG"]["ResidualType"] is None and items["GGG"]["Residuals"] == []
    assert items["BBB"]["ResidualType"] == "Multiplicative" and items["AAA"]["ResidualType"] == "Additive"
    assert len(items["BBB"]["Residuals"]) == 16 and items["AAA"]["Metadata"]["Source"] == "synthetic demo data"
    only_eq = client.post(url, json=body[:1], params={"onlyProps": "Equations"})[0]
    assert "Residuals" not in only_eq and "Metadata" not in only_eq
    assert toy_equation("NOPE", "US") == (None, None)


def test_real_looking_mnemonics_have_no_toy_equations(client, release):
    """Licence safety: only the fictional codes carry toy equations in the demo."""
    real_looking = ("GDP", "C", "CPI", "RSH", "IF", "M", "X", "GC", "RLG", "WPO_EQN", "RFED", "CONF_SHOCK")
    assert not set(real_looking) & set(demo.TOY_EQUATIONS)
    assert all(len(code) == 3 and len(set(code)) == 1 for code in demo.TOY_EQUATIONS)
    url = f"/v1/forecast-contents/{release['Id']}/model-variables"
    body = [{"IndicatorCode": c, "GroupCode": g} for c in real_looking for g in ("US", "ALPHA")]
    for item in client.post(url, json=body, params={"onlyProps": "Equations,Residuals,Metadata"}):
        assert item["Equations"] == [] and item["ResidualType"] is None and item["Residuals"] == []
    for code in demo.TOY_EQUATIONS:
        text = demo.toy_equation(code, "ALPHA")[0]
        text = json.dumps(text)
        assert "WORLD" not in text
        refs = set(re.findall(r"([A-Z]+):([A-Z_]+)", text))
        assert {g for _, g in refs} == {"ALPHA"}, code   # no links to other groups
        assert {i for i, _ in refs} <= set(demo._FAMILIES) - set(real_looking)
        assert not re.search(r"\d\.\d{3,}", text)        # toy coefficients have at most 2 decimals


def test_solve_routes_and_route_plugin(client):
    for method, path, status in (("POST", "/v1/operations/solve", 400), ("GET", "/v1/operations/op-1", 404),
                                 ("GET", "/v1/operations/op-1/await", 404)):
        with pytest.raises(OEError) as err:
            client.request(method, path, json={})
        assert err.value.status == status

    def fake_solve(session, req):
        session.operations["op-1"] = {"Id": "op-1", "Status": "Queued", "Body": req.json}
        return session.operations["op-1"]

    client.session.add_route(*SOLVE_ROUTE, fake_solve)
    assert client.post("/v1/operations/solve", json={"Commands": ""})["Status"] == "Queued"
    with pytest.raises(OEError):  # other sessions keep the default table
        OEClient.demo().post("/v1/operations/solve", json={})


def test_store_api_inheritance_and_overrides(client):
    s = client.session
    base = first_release_id(s)
    child = s.add_forecast("me/examples/child", parent=base)
    assert s.get_series(child, "GDP", "US") == s.get_series(base, "GDP", "US")
    s.set_series(child, "GDP", "US", {"2026q1": 1.0, "2026Q2": 2})
    assert s.values(child, "GDP", "US") == {"2026Q1": 1.0, "2026Q2": 2.0}
    assert s.get_series(base, "GDP", "US")["2026Q1"] != 1.0
    s.remove("me/examples/child")
    with pytest.raises(demo.DemoError):
        s.forecast(child)


def test_resource_tree_and_refusals():
    s = FakeSession()
    auth = {"Authorization": "Bearer x-demo"}
    base = demo.DEMO_BASE_URL + "/v1/resources/"
    tree = s.request("GET", base + "oxford-economics/releases/Global%20Economic%20Model/Extension", headers=auth)
    names = [c["Name"] for c in json.loads(tree.content.decode("utf-8-sig"))["Children"]]
    assert names == ["Demo26_1 5yr", "Demo26_2 25yr", "Demo26_2 5yr", "Previous releases"]
    assert s.request("DELETE", base + "demo-shared/team-scenarios/old-scenario", headers=auth).status_code == 403
    assert s.request("DELETE", base + "me", headers=auth).status_code == 403
    assert s.request("PUT", base + "me/new", json={"Name": "new", "ResourceType": "Directory"},
                     headers=auth).status_code == 201
    assert s.request("PUT", base + "me/new", json={"ResourceType": "Directory"}, headers=auth).status_code == 409
    assert s.request("PATCH", base + "me/new", json={"Directory": "/me/new"}, headers=auth).status_code == 400


def test_fault_injection_with_client_retries(client):
    client.session.fail_next(503, requests.ConnectionError("dropped"))
    assert client.whoami()["Path"] == "/me"  # demo client retries twice without sleeping
    client.session.fail_next(503, 503, 503)
    with pytest.raises(OEError) as err:
        client.whoami()
    assert err.value.status == 503
