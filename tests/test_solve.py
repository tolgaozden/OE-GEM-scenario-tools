"""Solving one scenario against the synthetic demo backend (numbers are NOT model output)."""
from datetime import datetime

import pytest

from oegem import OEError
from oegem.demo import OPERATION_AWAIT_ROUTE, ROUTES, SOLVE_ROUTE
from oegem.scenario import Scenario
from oegem.solve import SolveResult, default_output_path, is_pending, slug, solve

RANGE = {"solve_from": "2026Q3", "solve_to": "2031Q4"}


def ops_calls(session):
    return [(c.method, c.path) for c in session.calls if c.path.startswith("/v1/operations")]


def test_output_path_and_slug():
    when = datetime(2026, 10, 16, 9, 5, 7)
    assert default_output_path("/me/runs/", "oil up!", when=when) == "/me/runs/oil_up_-20261016-090507"
    assert slug("a/b c") == "a_b_c" and slug("") == "scenario"
    with pytest.raises(ValueError):
        default_output_path("", "x")
    assert is_pending("In Progress") and is_pending("Queued") and not is_pending("Succeeded")


def test_solve_succeeds_and_applies_commands(client, release):
    s = client.session
    sc = (Scenario("toy").set_level("AAA:ALPHA", "2027Q1", [111.5, 112.5])
          .scale("BBB:ALPHA", "2027Q1", [2.0]).shift_residual("CCC:ALPHA", "2027Q1", [3.0]))
    res = solve(client, release, sc, poll_seconds=0, output_folder="/me/examples", **RANGE)
    assert isinstance(res, SolveResult) and res.ok and res.failure == ""
    assert res.output_path.startswith("/me/examples/toy-") and res.forecast_id == s.forecast_id(res.output_path)
    assert res.submitted_at.endswith("Z") and res.seconds >= 0 and res.to_dict()["status"] == "Succeeded"
    base, new = release["Id"], res.forecast_id
    assert s.get_series(new, "AAA", "ALPHA")["2027Q2"] == 112.5
    assert s.get_series(new, "BBB", "ALPHA")["2027Q1"] == pytest.approx(2 * s.get_series(base, "BBB", "ALPHA")["2027Q1"])
    assert s.get_series(new, "CCC", "ALPHA")["2027Q1"] == pytest.approx(s.get_series(base, "CCC", "ALPHA")["2027Q1"] + 3)
    assert s.get_series(new, "AAA", "ALPHA")["2026Q4"] == s.get_series(base, "AAA", "ALPHA")["2026Q4"]
    calls = ops_calls(s)
    assert calls[0] == ("POST", "/v1/operations/solve")
    assert [m for m, p in calls[1:]] == ["GET", "GET"] and all(p.endswith("/await") for _, p in calls[1:])
    body = next(c.json for c in s.calls if c.method == "POST" and c.path == "/v1/operations/solve")
    assert body == {"InputForecast": release["Path"], "SolutionRange": {"From": "2026Q3", "To": "2031Q4"},
                    "Commands": sc.commands_text(), "OutputForecast": res.output_path}


def test_failed_solve_is_returned_not_raised(client, release):
    res = solve(client, release["Path"], "SHIFT AAA:ALPHA 2027Q1 1\n", name="typo", poll_seconds=0, **RANGE)
    assert res.status == "Failed" and not res.ok and res.forecast_id is None
    assert "unknown command 'SHIFT'" in res.failure


def test_submit_is_never_retried(client, release):
    client.session.fail_next(503)
    with pytest.raises(OEError) as err:
        solve(client, release, "FIX AAA:ALPHA 2027Q1:2027Q4", poll_seconds=0, **RANGE)
    assert err.value.status == 503
    assert ops_calls(client.session) == [("POST", "/v1/operations/solve")]


def test_falls_back_to_plain_polling_without_long_poll(client, release):
    client.session.add_route(*OPERATION_AWAIT_ROUTE, lambda s, req: (404, {"Message": "no long poll"}))
    res = solve(client, release, "FIX AAA:ALPHA 2027Q1:2027Q4", poll_seconds=0, **RANGE)
    assert res.ok
    paths = [p for _, p in ops_calls(client.session)]
    assert sum(p.endswith("/await") for p in paths) == 1          # tried once, then plain GETs
    assert paths[-1] == f"/v1/operations/{res.operation_id}"


def test_timeout_returns_pending_status(client, release):
    res = solve(client, release, "FIX AAA:ALPHA 2027Q1:2027Q4", poll_seconds=0, timeout_seconds=0, **RANGE)
    assert res.status == "Queued" and res.forecast_id is None and "Still Queued" in res.failure
    assert ops_calls(client.session) == [("POST", "/v1/operations/solve")]


def test_lost_contact_after_submit_raises(client, release):
    original = ROUTES[SOLVE_ROUTE]

    def flaky(session, req):
        out = original(session, req)
        session.fail_next(*([503] * 6))   # /await and the plain GET both fail after retries
        return out

    client.session.add_route(*SOLVE_ROUTE, flaky)
    with pytest.raises(OEError, match="Lost contact"):
        solve(client, release, "FIX AAA:ALPHA 2027Q1:2027Q4", poll_seconds=0, **RANGE)


def test_input_errors(client, release):
    with pytest.raises(ValueError, match="solve_from"):
        solve(client, release, "FIX AAA:ALPHA 2027Q1:2027Q4")
    with pytest.raises(ValueError, match="No commands"):
        solve(client, release, "# nothing here\n", **RANGE)
    with pytest.raises(ValueError, match="no Path"):
        solve(client, {"Id": "x"}, "FIX AAA:ALPHA 2027Q1:2027Q4", **RANGE)
    sc = Scenario("own_range", solve_from="2026Q3", solve_to="2027Q4").fix("AAA:ALPHA", "2027Q1:2027Q4")
    assert solve(client, release, sc, poll_seconds=0).ok


# ------------------------------------------------------------- demo solve endpoint


def post(client, release, commands, out="/me/examples/x", **over):
    body = {"InputForecast": release["Path"], "SolutionRange": {"From": "2026Q3", "To": "2031Q4"},
            "Commands": commands, "OutputForecast": out}
    body.update(over)
    return client.post("/v1/operations/solve", json=body)


def test_demo_operation_steps_and_request_checks(client, release):
    op = post(client, release, "FIX AAA:ALPHA 2027Q1:2027Q4")
    assert op["Status"] == "Queued" and "Commands" not in op
    steps = [client.get(f"/v1/operations/{op['Id']}")["Status"] for _ in range(3)]
    assert steps == ["InProgress", "Succeeded", "Succeeded"]
    for kwargs, status in (({}, 409),                                        # output now exists
                           ({"out": "/me/examples/y", "InputForecast": "/me/nope"}, 404),
                           ({"out": "/me/missing-folder/y"}, 404),
                           ({"out": "/me/examples/y", "SolutionRange": {"From": "2031Q4", "To": "2026Q3"}}, 400),
                           ({"out": "/me/examples/y", "Extra": 1}, 400)):
        with pytest.raises(OEError) as err:
            post(client, release, "FIX AAA:ALPHA 2027Q1:2027Q4", **kwargs)
        assert err.value.status == status


def test_demo_spread_respects_fix_and_range(client, release):
    s, base = client.session, release["Id"]
    cmds = "\n".join(["MULTIPLY AAA:WORLD 2027Q1 4@1.2", "FIX AAA:WORLD 2027Q1:2027Q4",
                      "FIX BBB:JAPAN 2027Q1:2027Q4", "FIX BBB:KOREA 2027Q1:2027Q4",
                      "UNFIX BBB:KOREA 2027Q1:2027Q4"])
    res = solve(client, release, cmds, name="spread", poll_seconds=0, **RANGE)
    new = res.forecast_id
    # mechanical rule: every other series moves by SPREAD_SHARE (0.1) of the 20% WORLD shock
    us0, us1 = s.get_series(base, "BBB", "US"), s.get_series(new, "BBB", "US")
    assert us1["2027Q1"] == pytest.approx(us0["2027Q1"] * 1.02, rel=1e-6)
    assert us1["2026Q4"] == us0["2026Q4"] and us1["2028Q1"] == us0["2028Q1"]
    assert s.get_series(new, "BBB", "JAPAN")["2027Q1"] == s.get_series(base, "BBB", "JAPAN")["2027Q1"]
    assert s.get_series(new, "BBB", "KOREA")["2027Q1"] != s.get_series(base, "BBB", "KOREA")["2027Q1"]
    assert s.get_series(new, "MMM_SHOCK", "US") == s.get_series(base, "MMM_SHOCK", "US")   # zero series stay put
    beta0, beta1 = s.get_series(base, "BBB", "BETA"), s.get_series(new, "BBB", "BETA")   # annual-only group
    assert beta1["2027"] == pytest.approx(beta0["2027"] * 1.02, rel=1e-6)


def test_demo_residual_and_annual_periods(client, release):
    s, base = client.session, release["Id"]
    ok = solve(client, release, "INCREASE &GDP:BETA 2027 1.5\nINCREASE &C:US 2027Q1 1", name="a",
               poll_seconds=0, **RANGE)
    assert ok.ok
    assert s.get_series(ok.forecast_id, "GDP", "BETA")["2027"] == pytest.approx(s.get_series(base, "GDP", "BETA")["2027"] + 1.5)
    gdp0, gdp1 = s.get_series(base, "GDP", "US")["2027Q1"], s.get_series(ok.forecast_id, "GDP", "US")["2027Q1"]
    assert gdp1 > gdp0                                   # mechanical spread within the group
    bad = solve(client, release, "INCREASE &GDP:BETA 2027Q1 1.5", name="b", poll_seconds=0, **RANGE)
    assert bad.status == "Failed" and "annual" in bad.failure
