"""Synthetic offline backend for oegem: demo mode and the test suite.

ALL NUMBERS PRODUCED HERE ARE SYNTHETIC. THEY ARE NOT OXFORD ECONOMICS MODEL OUTPUT
AND ARE UNRELATED TO THE GLOBAL ECONOMIC MODEL. Series come from seeded
pseudo-random formulas (seed = zlib.crc32 of "INDICATOR:GROUP"), the equations are
toy formulas written for testing, and every release name, folder, catalogue entry,
residual and identifier is made up. Never use demo results for analysis.

What the backend emulates, enough to run the package end to end offline:

* ``GET/PUT/PATCH/DELETE /v1/resources/<path>``: a small fake release tree under
  ``oxford-economics/releases/Global Economic Model`` (``Extension/Demo26_1 5yr``,
  ``Extension/Demo26_2 5yr``, ``Extension/Demo26_2 25yr`` and
  ``Extension/Previous releases/2026-01_1/Demo26_0 5yr``), a fictional shared area
  ``demo-shared/team-scenarios`` with a ``$Archive`` folder, and the user's ``/me``
  workspace. Folders can be created, moved and deleted; deleting anything outside
  ``/me`` is refused unless it sits inside a ``$Archive`` folder.
* ``GET /v1/forecast-contents/<id>`` plus ``/indicators`` and ``/groups``.
* ``POST .../variables`` (values; at most 400 selections; group BETA is annual-only
  and returns nothing unless ``"Frequency": "Annual"`` is requested; annual periods
  come back as ISO date strings) and ``POST .../model-variables`` (toy equations for
  the fictional codes AAA-FFF only, in varying payload shapes, with residual types,
  synthetic residuals and metadata; every other code, including the real-looking
  example mnemonics, is exogenous: no equation and no residual type). The fictional
  economy GAMMA has only three toy equations, each leaning on ALPHA, so the economy
  profile heuristic has a "satellite" to find. Metadata uses the API's field names
  (units, scaling, annualisation type, history end 2026Q2, or 2025 for the annual-only
  group, base years) with made-up values and no contact fields; the fictional indexes
  FFF and ZZZ change BaseYearIndex in the newer demo releases.
* JSON bodies start with a UTF-8 byte-order mark; requests without a bearer token
  get HTTP 401; ``FakeSession.fail_next`` injects failures for retry tests.

* ``POST /v1/operations/solve`` plus ``GET /v1/operations/<id>`` and ``.../await``:
  toy solves. An operation moves Queued -> InProgress -> Succeeded (or Failed) by one
  step on each status request, with no sleeping. On success a new forecast (child of
  the input forecast) holds the input series changed by the commands inside the
  SolutionRange. A mechanical rule (`_spread_shocks`) then passes a fixed share of each
  group's average shock on to the group's other series, so demo outputs show some
  movement. The rule links no particular variables, has no economic content and says
  nothing about how the GEM or any other model responds.

Handlers live in a dispatch table keyed by ``(method, regex)``. A handler plugs in
with ``register(method, pattern, fn)`` (or ``@route(...)``; ``FakeSession.add_route``
for one session), where ``fn(session, request)`` uses the store API of `FakeSession`
(`add_forecast`, `get_series`, `set_series`, `operations`) and returns a payload, a
``(status, payload)`` tuple or a `FakeResponse`.
"""
from __future__ import annotations

import base64
import json as _json
import math
import random
import re
import time
import uuid
import zlib
from collections import namedtuple
from dataclasses import dataclass
from functools import lru_cache
from http import HTTPStatus
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, unquote, urlsplit

import requests

from .periods import in_range, normalize_period, parse_period, parse_range, period_range, year_of
from .scenario import KNOWN_VERBS, WINDOW_VERBS, Command

DEMO_BASE_URL = "https://oegem-demo.invalid/api"
GEM_ROOT = "oxford-economics/releases/Global Economic Model"
EXTENSION = GEM_ROOT + "/Extension"
PREVIOUS = EXTENSION + "/Previous releases"
SHARED_ROOT = "demo-shared/team-scenarios"
ARCHIVE_FOLDER = SHARED_ROOT + "/$Archive"
USER_ROOT = "me"
HISTORY_START = "2010Q1"
DEFAULT_END = "2035Q4"
LONG_END = "2050Q4"
REVISION_START_YEAR = 2026
MAX_SELECTIONS = 400
ANNUAL_ONLY_GROUPS = ("BETA",)

# ------------------------------------------------------------- synthetic catalogue
# (code, name, units, family). Families drive the synthetic generator only.
_INDICATOR_TABLE = [
    ("GDP", "Real GDP (synthetic)", "Synthetic units, constant prices", "level"),
    ("CPI", "Consumer price index (synthetic)", "Index", "index"),
    ("C", "Private consumption (synthetic)", "Synthetic units, constant prices", "level"),
    ("IF", "Fixed investment (synthetic)", "Synthetic units, constant prices", "level"),
    ("GC", "Government consumption (synthetic)", "Synthetic units, constant prices", "level"),
    ("X", "Exports of goods and services (synthetic)", "Synthetic units, constant prices", "level"),
    ("M", "Imports of goods and services (synthetic)", "Synthetic units, constant prices", "level"),
    ("RSH", "Short-term interest rate (synthetic)", "Percent", "rate"),
    ("RLG", "Long-term interest rate (synthetic)", "Percent", "rate"),
    ("WPO_EQN", "World oil price (synthetic)", "Synthetic price units", "price"),
    ("RFED", "US policy rate (synthetic)", "Percent", "rate"),
    ("CONF_SHOCK", "Confidence shock variable (synthetic)", "Shock units", "shock"),
    ("AAA", "Fictional activity index", "Index", "index"),
    ("BBB", "Fictional price index", "Index", "index"),
    ("CCC", "Fictional wage level", "Synthetic units", "level"),
    ("DDD", "Fictional credit stock", "Synthetic units", "level"),
    ("EEE", "Fictional employment", "Synthetic units", "level"),
    ("FFF", "Fictional house price index", "Index", "index"),
    ("GGG", "Fictional exchange rate", "Synthetic units", "index"),
    ("HHH", "Fictional export volume", "Synthetic units", "level"),
    ("KKK", "Fictional bond yield", "Percent", "rate"),
    ("LLL", "Fictional unemployment rate", "Percent", "rate"),
    ("QQQ", "Fictional population", "Synthetic units", "level"),
    ("ZZZ", "Fictional productivity index", "Index", "index"),
    ("MMM_SHOCK", "Fictional demand shock", "Shock units", "shock"),
    ("NNN_DUM", "Fictional dummy variable", "0/1", "shock"),
    ("PPP_ADD", "Fictional add factor for prices", "Synthetic units", "shock"),
]
INDICATORS: List[dict] = [{"Code": c, "Name": n, "Units": u} for c, n, u, _ in _INDICATOR_TABLE]
_FAMILIES = {c: f for c, _, _, f in _INDICATOR_TABLE}
_NAMES = {c: (n, u) for c, n, u, _ in _INDICATOR_TABLE}

GROUPS: List[dict] = [
    {"Code": "US", "Name": "United States (synthetic)", "Type": "Country"},
    {"Code": "CHINA", "Name": "China (synthetic)", "Type": "Country"},
    {"Code": "JAPAN", "Name": "Japan (synthetic)", "Type": "Country"},
    {"Code": "EURO_11", "Name": "Eurozone (synthetic)", "Type": "Region"},
    {"Code": "INDIA", "Name": "India (synthetic)", "Type": "Country"},
    {"Code": "KOREA", "Name": "Korea (synthetic)", "Type": "Country"},
    {"Code": "INDONESI", "Name": "Indonesia (synthetic)", "Type": "Country"},
    {"Code": "WORLD", "Name": "World (synthetic)", "Type": "Region"},
    {"Code": "ALPHA", "Name": "Fictional economy Alpha", "Type": "Country"},
    {"Code": "BETA", "Name": "Fictional economy Beta", "Type": "Country"},
    {"Code": "GAMMA", "Name": "Fictional economy Gamma", "Type": "Country"},
]
_GROUP_NAMES = {g["Code"]: g["Name"] for g in GROUPS}

# Toy equations, for the FICTIONAL codes AAA-FFF only: made-up formulas that exercise the
# equation parser (lags and leads, additive and multiplicative residuals, LN/EXP/DLOG/DIFF
# calls, ^ exponents, a two-argument call) and the payload shapes the API may use. They do
# not follow the form of any real model. Every other code, including the real-looking
# example mnemonics (GDP, C, CPI, RSH, ...), is exogenous in the demo: no equation, no
# residual type. Entries: (residual type, payload shape, template with {g} = group).
TOY_EQUATIONS: Dict[str, Tuple[str, str, str]] = {
    "AAA": ("Additive", "text",
            "0.5 * AAA:{g}[-1] + 0.25 * BBB:{g} - 0.1 * CCC:{g}[+1] + 2 + &AAA:{g}"),
    "BBB": ("Multiplicative", "list",
            "(BBB:{g}[-1] + 0.5 * DIFF(DDD:{g}) + 0.2 * DLOG(EEE:{g})) * &BBB:{g}"),
    "CCC": ("Additive", "dict",
            "0.25 * S(AAA:{g}, 4) + 0.75 * CCC:{g}[-1] + &CCC:{g}"),
    "DDD": ("Multiplicative", "list_of_dicts",
            "EXP(0.5 * LN(EEE:{g}) + 0.5 * LN(FFF:{g}[-1])) * &DDD:{g}"),
    "EEE": ("Additive", "text",
            "EEE:{g}[-1] + 0.3 * (FFF:{g} / 100) ^ 2 - 1.5 + &EEE:{g}"),
    "FFF": ("Multiplicative", "text",
            "(GGG:{g}[+1] ^ 0.5) * (AAA:{g}[-2] ^ 0.5) * &FFF:{g}"),
}


# Group-specific toys: the fictional economy GAMMA gets only three equations, each leaning on
# the fictional economy ALPHA, so that equations.group_profile has a "satellite-looking" group
# to find. None = exogenous in that group. Same caveat: made-up formulas, no real model's form.
TOY_GROUP_EQUATIONS: Dict[Tuple[str, str], Optional[Tuple[str, str, str]]] = {
    ("AAA", "GAMMA"): ("Additive", "text", "0.5 * AAA:GAMMA[-1] + 0.5 * AAA:ALPHA + &AAA:GAMMA"),
    ("BBB", "GAMMA"): ("Multiplicative", "list", "(BBB:ALPHA * BBB:GAMMA[-1] / BBB:ALPHA[-1]) * &BBB:GAMMA"),
    ("CCC", "GAMMA"): ("Additive", "dict", "0.75 * CCC:GAMMA[-1] + 0.25 * DIFF(CCC:ALPHA) + &CCC:GAMMA"),
    ("DDD", "GAMMA"): None,
    ("EEE", "GAMMA"): None,
    ("FFF", "GAMMA"): None,
}


def toy_equation(indicator: str, group: str) -> Tuple[Any, Optional[str]]:
    """(equation payload in its demo shape, residual type), or (None, None) for exogenous codes.

    Only the fictional codes in TOY_EQUATIONS have equations (in group GAMMA: see
    TOY_GROUP_EQUATIONS); everything else is exogenous.
    """
    key = (str(indicator), str(group))
    spec = TOY_GROUP_EQUATIONS[key] if key in TOY_GROUP_EQUATIONS else TOY_EQUATIONS.get(indicator)
    if spec is None:
        return None, None
    rtype, shape, template = spec
    text = template.format(g=group)
    payload = {"text": text, "list": [text], "dict": {"Expression": text},
               "list_of_dicts": [{"Equation": text, "Kind": "toy"}]}[shape]
    return payload, rtype


# ---------------------------------------------------------------- synthetic series


def _seed(*parts: str) -> int:
    """Stable seed (zlib.crc32, not Python's randomised hash())."""
    return zlib.crc32(":".join(parts).encode("utf-8"))


def _rng(*parts: str) -> random.Random:
    return random.Random(_seed(*parts))


def indicator_kind(code: str) -> str:
    """Generator family of a code: level, index, price, rate or shock (unknown codes are guessed)."""
    c = str(code).upper()
    if c in _FAMILIES:
        return _FAMILIES[c]
    if re.search(r"SHOCK|DUM|_ADD$|RESID", c):
        return "shock"
    if c.startswith("R") and len(c) <= 4:
        return "rate"
    return "level"


def annualise(series: Dict[str, float]) -> Dict[str, float]:
    """Annual means of a quarterly series (complete years only)."""
    years: Dict[int, List[float]] = {}
    for p, v in series.items():
        y, q = parse_period(p)
        if q:
            years.setdefault(y, []).append(v)
    return {str(y): round(sum(vs) / len(vs), 4) for y, vs in sorted(years.items()) if len(vs) == 4}


def _revise(series: Dict[str, float], indicator: str, group: str, vintage: int, kind: str) -> Dict[str, float]:
    """Small vintage-dependent shift of the forecast years, so demo releases differ."""
    if not vintage or kind == "shock":
        return series
    sign = 1.0 if _seed("revision", indicator, group) % 2 else -1.0
    out = {}
    for p, v in series.items():
        steps = year_of(p) - REVISION_START_YEAR + 1
        if steps <= 0:
            out[p] = v
            continue
        ramp = min(1.0, steps / 3.0)
        if kind == "rate":
            out[p] = round(min(10.0, max(0.0, v + sign * 0.05 * vintage * ramp)), 4)
        else:
            out[p] = round(v * (1.0 + sign * 0.003 * vintage * ramp), 4)
    return out


@lru_cache(maxsize=4096)
def _synthetic(indicator: str, group: str, vintage: int, end: str) -> Dict[str, float]:
    rnd = _rng(indicator, group)
    u = [rnd.random() for _ in range(5)]
    kind = indicator_kind(indicator)
    periods = period_range(HISTORY_START, end)
    if kind == "shock":
        quarterly = {p: 0.0 for p in periods}
    else:
        cycle, phase = 16.0 + 16.0 * u[3], 2.0 * math.pi * u[4]
        if kind == "rate":
            base, growth, amp = 0.5 + 6.0 * u[0], 0.0, 0.5 + 1.5 * u[1]
        elif kind == "index":
            base, growth, amp = 80.0 + 40.0 * u[0], 0.003 + 0.006 * u[1], 0.003 + 0.010 * u[2]
        elif kind == "price":
            base, growth, amp = 40.0 + 50.0 * u[0], 0.001 + 0.004 * u[1], 0.05 + 0.10 * u[2]
        else:
            base, growth, amp = 100.0 * 10 ** (1.8 * u[0]), 0.002 + 0.006 * u[1], 0.005 + 0.015 * u[2]
        quarterly = {}
        for i, p in enumerate(periods):
            wave = math.sin(2.0 * math.pi * i / cycle + phase)
            noise = rnd.random() - 0.5
            if kind == "rate":
                v = min(10.0, max(0.0, base + amp * wave + 0.2 * noise))
            else:
                v = base * math.exp(growth * i) * (1.0 + amp * wave) * (1.0 + 0.004 * noise)
            quarterly[p] = round(v, 4)
    quarterly = _revise(quarterly, indicator, group, vintage, kind)
    return annualise(quarterly) if group in ANNUAL_ONLY_GROUPS else quarterly


def synthetic_series(indicator: str, group: str, *, vintage: int = 0, end: str = DEFAULT_END) -> Dict[str, float]:
    """Deterministic synthetic series {period: value} at the group's native frequency.

    Quarterly from 2010Q1 to end, or annual for annual-only groups. vintage shifts the
    years from 2026 on a little. The numbers are synthetic, not model output.
    """
    return dict(_synthetic(str(indicator), str(group), int(vintage), normalize_period(end)))


def api_period(p: str) -> str:
    """Period label as the demo API writes it: "2026Q1", or "2026-01-01T00:00:00" for a year."""
    y, q = parse_period(p)
    return f"{y}Q{q}" if q else f"{y}-01-01T00:00:00"


def _residuals(indicator: str, group: str, rtype: Optional[str]) -> List[dict]:
    if not rtype:
        return []
    rnd = _rng("residual", indicator, group)
    centre = 1.0 if rtype == "Multiplicative" else 0.0
    periods = ([str(y) for y in range(2024, 2028)] if group in ANNUAL_ONLY_GROUPS
               else period_range("2024Q1", "2027Q4"))
    return [{"Period": api_period(p), "Value": round(centre + 0.01 * (rnd.random() - 0.5), 6)} for p in periods]


# Synthetic metadata per generator family: Unit, Scaling, ScaleFactor, AnnualizationType and
# whether a quarterly series counts as seasonally adjusted. The field names follow the API;
# the values are made up and say nothing about how any real model labels its series.
_META_FAMILY = {
    "level": ("Synthetic units", "Millions", 1000000, "Sum", True),
    "index": ("Index", "Units", 1, "Average", True),
    "price": ("Synthetic price units", "Units", 1, "Average", False),
    "rate": ("Percent", "Units", 1, "Average", False),
    "shock": ("Shock units", "Units", 1, "Sum", False),
}
_META_ANNUALIZATION = {"DDD": "EndOfPeriod", "EEE": "Average", "QQQ": "Average"}   # fictional stock, averages
HISTORY_END = "2026Q2"            # last historical quarter of every quarterly demo series
HISTORY_END_ANNUAL = "2025"       # last historical year of the annual-only group
BASE_YEAR = 2015
REBASED_INDICATORS = ("FFF", "ZZZ")   # fictional indexes re-based in the newer demo releases
REBASE_VINTAGE = 2
REBASED_YEAR = 2020


def toy_metadata(indicator: str, group: str, vintage: int = 0) -> dict:
    """Synthetic Metadata dict for one pair: the API's field names with made-up values.

    Unit, scaling and annualisation follow the demo generator family; HistoryEnd is 2026Q2
    (2025 for annual-only groups; shock series carry only DerivedHistoryEnd); the fictional
    indexes in REBASED_INDICATORS move BaseYearIndex from 2015 to 2020 in releases of
    vintage REBASE_VINTAGE or later. There are no contact fields.
    """
    ind, grp = str(indicator), str(group)
    kind = indicator_kind(ind)
    unit, scaling, factor, how, adjusted = _META_FAMILY[kind]
    name, units = _NAMES.get(ind, (f"Synthetic variable {ind}", "Synthetic units"))
    annual_only = grp in ANNUAL_ONLY_GROUPS
    end = HISTORY_END_ANNUAL if annual_only else HISTORY_END
    base_index = None
    if kind == "index":
        base_index = REBASED_YEAR if ind in REBASED_INDICATORS and int(vintage) >= REBASE_VINTAGE else BASE_YEAR
    props = {"SectorCoverage": "Total (synthetic)"}
    if kind == "level":
        props["PriceBasis"] = "Constant (synthetic)"
    return {
        "AnnualizationType": _META_ANNUALIZATION.get(ind, how),
        "BaseYearIndex": base_index,
        "BaseYearPrice": BASE_YEAR if kind == "level" else None,
        "DerivedHistoryEnd": end,
        "Description": name,
        "GroupName": _GROUP_NAMES.get(grp, f"Synthetic group {grp}"),
        "HistoryEnd": None if kind == "shock" else end,
        "IndicatorProperties": props,
        "InternalId": 100000 + _seed("internal-id", ind, grp) % 900000,
        "IsSeasonallyAdjusted": bool(adjusted and not annual_only),
        "OriginalSourceCode": f"SYN-{ind}",
        "OriginalSourceProvider": "Synthetic demo source",
        "ScaleFactor": factor,
        "Scaling": scaling,
        "Source": "synthetic demo data",
        "Unit": unit,
        "Units": units,
    }


def make_demo_token(hours: float = 24.0) -> str:
    """Unsigned JWT-shaped dummy token for demo mode (not a credential; built at runtime)."""
    def enc(obj) -> str:
        return base64.urlsafe_b64encode(_json.dumps(obj, separators=(",", ":")).encode()).rstrip(b"=").decode()

    claims = {"sub": "demo-user", "iss": "oegem-demo", "exp": int(time.time() + hours * 3600)}
    return f"{enc({'alg': 'none', 'typ': 'JWT'})}.{enc(claims)}.demo"


# ------------------------------------------------------------------ HTTP plumbing


class FakeResponse:
    """Minimal stand-in for requests.Response.

    JSON payloads are serialised with a leading UTF-8 BOM when bom=True, like the real
    API; json() then fails exactly as requests does with an explicit utf-8 charset, so
    callers must strip the BOM (OEClient does).
    """

    def __init__(self, status_code: int = 200, payload: Any = None, *, text: Optional[str] = None,
                 headers: Optional[dict] = None, url: str = "", bom: bool = True):
        if text is None:
            text = "" if payload is None else _json.dumps(payload)
        self.status_code = int(status_code)
        self.url = url
        self.encoding = "utf-8"
        self.headers = {"Content-Type": "application/json; charset=utf-8"}
        self.headers.update(headers or {})
        self.content = (b"\xef\xbb\xbf" if bom and text else b"") + text.encode("utf-8")
        try:
            self.reason = HTTPStatus(self.status_code).phrase
        except ValueError:
            self.reason = ""

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> Any:
        return _json.loads(self.text)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} {self.reason}", response=self)

    def close(self) -> None:
        pass


class DemoError(Exception):
    """Raise inside a handler to answer with an HTTP error status and {"Message": message}."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class DemoRequest:
    """What a handler receives: decoded API path ("/v1/..."), query params, JSON body, regex match."""

    method: str
    path: str
    params: Dict[str, str]
    json: Any
    match: Any
    headers: Dict[str, str]


Call = namedtuple("Call", "method path params json")
Handler = Callable[["FakeSession", DemoRequest], Any]
ROUTES: Dict[Tuple[str, str], Handler] = {}

SOLVE_ROUTE = ("POST", r"^/v1/operations/solve$")
OPERATION_ROUTE = ("GET", r"^/v1/operations/(?P<op_id>[^/]+)$")
OPERATION_AWAIT_ROUTE = ("GET", r"^/v1/operations/(?P<op_id>[^/]+)/await$")


def register(method: str, pattern: str, handler: Handler) -> Handler:
    """Add, or replace, the handler for (method, pattern) in the default dispatch table.

    Sessions copy the table when created, so register before creating a FakeSession.
    """
    ROUTES[(method.upper(), pattern)] = handler
    return handler


def route(method: str, pattern: str):
    """Decorator form of register()."""
    def deco(fn: Handler) -> Handler:
        return register(method, pattern, fn)
    return deco


class FakeSession:
    """In-memory stand-in for requests.Session that answers the API with synthetic data.

    Store (per instance):
      resources:  canonical path (no leading "/", e.g. "me/examples") -> {"Id", "Name", "Type"}
      forecasts:  forecast id -> {"path", "name", "parent" (forecast id or None), "vintage", "end",
                  "series": {(indicator, group): {period: value}}, "deleted"}. A series not stored on
                  a forecast is read from its parent, and at the root from synthetic_series().
                  Keys are quarterly periods, or years for annual-only groups.
      operations: operation id -> operation dict (free for a demo solve handler)
      routes:     (method, regex) -> handler, copied from ROUTES; add_route() changes this session only
      calls:      Call(method, path, params, json) for every request received (for tests)
    """

    def __init__(self, *, bom: bool = True):
        self.bom = bom
        self.headers: Dict[str, str] = {}
        self.calls: List[Call] = []
        self.resources: Dict[str, dict] = {}
        self.forecasts: Dict[str, dict] = {}
        self.operations: Dict[str, dict] = {}
        self.routes: Dict[Tuple[str, str], Handler] = dict(ROUTES)
        self._faults: List[Any] = []
        self._counter = 0
        self._seed_tree()

    # -- store API ---------------------------------------------------------------
    def _seed_tree(self) -> None:
        for folder in ("oxford-economics", "oxford-economics/releases", GEM_ROOT, EXTENSION, PREVIOUS,
                       PREVIOUS + "/2026-01_1", "demo-shared", SHARED_ROOT, ARCHIVE_FOLDER,
                       USER_ROOT, USER_ROOT + "/examples"):
            self.add_folder(folder)
        first = self.add_forecast(EXTENSION + "/Demo26_1 5yr", vintage=1)
        second = self.add_forecast(EXTENSION + "/Demo26_2 5yr", vintage=2)
        self.add_forecast(EXTENSION + "/Demo26_2 25yr", vintage=2, end=LONG_END)
        self.add_forecast(PREVIOUS + "/2026-01_1/Demo26_0 5yr", vintage=0)
        self.add_forecast(SHARED_ROOT + "/old-scenario", parent=first)
        self.add_forecast(USER_ROOT + "/examples/demo-copy", parent=second)

    @staticmethod
    def canonical(path) -> str:
        """Store key of a path: no leading/trailing "/" or empty segments ("/me/x/" -> "me/x")."""
        return "/".join(seg for seg in str(path or "").strip().split("/") if seg)

    def _new_id(self, key: str) -> str:
        self._counter += 1
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"oegem-demo:{self._counter}:{key}"))

    def _check_new(self, key: str) -> None:
        if not key:
            raise DemoError(400, "Empty resource path")
        if key in self.resources:
            raise DemoError(409, f"/{key} already exists")
        if "/" in key:
            parent = key.rsplit("/", 1)[0]
            if parent not in self.resources:
                raise DemoError(404, f"Parent folder /{parent} does not exist")
            if self.resources[parent]["Type"] != "Directory":
                raise DemoError(400, f"/{parent} is not a folder")

    def add_folder(self, path) -> dict:
        """Create a folder (its parent must exist) and return its resource dict."""
        key = self.canonical(path)
        self._check_new(key)
        self.resources[key] = {"Id": self._new_id(key), "Name": key.rsplit("/", 1)[-1], "Type": "Directory"}
        return self.resource_dict(key)

    def add_forecast(self, path, *, parent: Optional[str] = None, vintage: int = 0,
                     end: Optional[str] = None) -> str:
        """Create a forecast resource at path and return its id.

        parent is the id of a forecast whose series it inherits (None: synthetic base data with
        the given vintage). end is the last quarter (default: the parent's, else 2035Q4).
        """
        key = self.canonical(path)
        self._check_new(key)
        if parent is not None:
            base = self.forecast(parent)
            end = end or base["end"]
        fid = self._new_id(key)
        name = key.rsplit("/", 1)[-1]
        self.resources[key] = {"Id": fid, "Name": name, "Type": "Forecast"}
        self.forecasts[fid] = {"path": key, "name": name, "parent": parent, "vintage": int(vintage),
                               "end": normalize_period(end or DEFAULT_END), "series": {}, "deleted": False}
        return fid

    def forecast(self, fid) -> dict:
        """Store entry of a live forecast; DemoError 404 if unknown or deleted."""
        fc = self.forecasts.get(str(fid))
        if fc is None or fc["deleted"]:
            raise DemoError(404, f"Forecast {fid} not found")
        return fc

    def forecast_id(self, path) -> Optional[str]:
        """Id of the forecast at path, or None."""
        res = self.resources.get(self.canonical(path))
        return res["Id"] if res and res["Type"] == "Forecast" else None

    def root_vintage(self, fid) -> int:
        """Vintage of the release a forecast descends from (a solved forecast has its input's)."""
        fc = self.forecast(fid)
        while fc["parent"] is not None:
            fc = self.forecasts[fc["parent"]]
        return int(fc["vintage"])

    def get_series(self, fid, indicator: str, group: str) -> Dict[str, float]:
        """Copy of a forecast's native-frequency series: stored, else inherited, else synthetic."""
        fc = self.forecasts.get(str(fid))
        if fc is None:
            raise DemoError(404, f"Forecast {fid} not found")
        key = (str(indicator), str(group))
        while True:
            if key in fc["series"]:
                return dict(fc["series"][key])
            if fc["parent"] is None:
                return synthetic_series(key[0], key[1], vintage=fc["vintage"], end=fc["end"])
            fc = self.forecasts[fc["parent"]]

    def set_series(self, fid, indicator: str, group: str, values: Dict[str, float]) -> None:
        """Store a full series on a forecast (periods are normalised; quarterly or annual keys)."""
        fc = self.forecast(fid)
        fc["series"][(str(indicator), str(group))] = {normalize_period(p): float(v) for p, v in values.items()}

    def values(self, fid, indicator: str, group: str, *, annual: bool = False) -> Dict[str, float]:
        """What the variables endpoint returns for one pair: nothing for an annual-only series
        at the default frequency; annual means when annual=True."""
        series = self.get_series(fid, indicator, group)
        native_annual = bool(series) and parse_period(next(iter(series)))[1] == 0
        if annual:
            return series if native_annual else annualise(series)
        return {} if native_annual else series

    def resource_dict(self, path) -> dict:
        """API-shaped resource dict (with Children for folders); DemoError 404 if missing."""
        key = self.canonical(path)
        if key not in self.resources:
            raise DemoError(404, f"Resource /{key} not found")
        out = self._summary(key)
        if self.resources[key]["Type"] == "Directory":
            out["Children"] = [self._summary(k) for k in self._children(key)]
        return out

    def _summary(self, key: str) -> dict:
        res = self.resources[key]
        return {"Id": res["Id"], "Name": res["Name"], "Path": "/" + key, "Type": res["Type"],
                "ResourceType": res["Type"]}

    def _children(self, key: str) -> List[str]:
        prefix = key + "/"
        return sorted(k for k in self.resources if k.startswith(prefix) and "/" not in k[len(prefix):])

    def move(self, path, new_parent) -> str:
        """Move a resource (and everything below it) into new_parent; returns the new key."""
        key, parent = self.canonical(path), self.canonical(new_parent)
        new_key = f"{parent}/{key.rsplit('/', 1)[-1]}"
        for k in sorted(k for k in self.resources if k == key or k.startswith(key + "/")):
            self.resources[new_key + k[len(key):]] = self.resources.pop(k)
        for fc in self.forecasts.values():
            if fc["path"] == key or fc["path"].startswith(key + "/"):
                fc["path"] = new_key + fc["path"][len(key):]
        return new_key

    def remove(self, path) -> None:
        """Delete a resource and everything below it (forecast data stays for inheritance)."""
        key = self.canonical(path)
        for k in [k for k in self.resources if k == key or k.startswith(key + "/")]:
            res = self.resources.pop(k)
            if res["Id"] in self.forecasts:
                self.forecasts[res["Id"]]["deleted"] = True

    def fail_next(self, *faults) -> None:
        """Queue failures for the next requests: an int (HTTP status) or an exception to raise."""
        self._faults.extend(faults)

    def add_route(self, method: str, pattern: str, handler: Handler) -> None:
        """Add or replace a handler for this session only."""
        self.routes[(method.upper(), pattern)] = handler

    # -- requests.Session interface ------------------------------------------------
    def _respond(self, status: int, payload: Any, url: str) -> FakeResponse:
        return FakeResponse(status, payload, url=url, bom=self.bom)

    def request(self, method, url, params=None, json=None, headers=None, timeout=None, data=None, **kwargs):
        """Dispatch one request to the matching handler and return a FakeResponse."""
        method = str(method).upper()
        parts = urlsplit(str(url))
        idx = parts.path.find("/v1/")
        path = unquote(parts.path[idx:] if idx >= 0 else parts.path)
        query = dict(parse_qsl(parts.query))
        query.update({str(k): str(v) for k, v in (params or {}).items()})
        if json is None and data:
            try:
                json = _json.loads(data)
            except (TypeError, ValueError):
                json = None
        self.calls.append(Call(method, path, query, json))
        if self._faults:
            fault = self._faults.pop(0)
            if isinstance(fault, BaseException):
                raise fault
            return self._respond(int(fault), {"Message": f"Injected demo failure (HTTP {fault})"}, url)
        auth = str((headers or {}).get("Authorization") or self.headers.get("Authorization") or "")
        if not auth.startswith("Bearer ") or not auth[7:].strip():
            return self._respond(401, {"Message": "Missing or invalid bearer token"}, url)
        for (verb, pattern), handler in self.routes.items():
            if verb != method:
                continue
            match = re.match(pattern, path)
            if not match:
                continue
            req = DemoRequest(method, path, query, json, match, dict(headers or {}))
            try:
                result = handler(self, req)
            except DemoError as exc:
                return self._respond(exc.status, {"Message": exc.message}, url)
            if isinstance(result, FakeResponse):
                return result
            if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], int):
                return self._respond(result[0], result[1], url)
            return self._respond(200, result, url)
        return self._respond(404, {"Message": f"No demo endpoint for {method} {path}"}, url)

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)

    def put(self, url, **kw):
        return self.request("PUT", url, **kw)

    def patch(self, url, **kw):
        return self.request("PATCH", url, **kw)

    def delete(self, url, **kw):
        return self.request("DELETE", url, **kw)

    def mount(self, prefix, adapter) -> None:
        """No-op (TLS adapters do not apply to the demo backend)."""

    def close(self) -> None:
        """No-op."""


# ----------------------------------------------------------------------- handlers
_RES = r"^/v1/resources/(?P<path>.+)$"
_FC = r"^/v1/forecast-contents/(?P<fid>[^/]+)"


@route("GET", _RES)
def _get_resource(s: FakeSession, req: DemoRequest):
    return s.resource_dict(req.match.group("path"))


@route("PUT", _RES)
def _put_resource(s: FakeSession, req: DemoRequest):
    key = s.canonical(req.match.group("path"))
    body = req.json if isinstance(req.json, dict) else {}
    if str(body.get("ResourceType") or body.get("Type") or "").lower() != "directory":
        raise DemoError(400, "The demo only creates folders: send ResourceType 'Directory'.")
    if key.split("/")[0] == "oxford-economics":
        raise DemoError(403, "The release tree is read-only.")
    return 201, s.add_folder(key)


@route("PATCH", _RES)
def _patch_resource(s: FakeSession, req: DemoRequest):
    key = s.canonical(req.match.group("path"))
    s.resource_dict(key)
    body = req.json if isinstance(req.json, dict) else {}
    parent = s.canonical(body.get("Directory") or "")
    if not parent:
        raise DemoError(400, "Send {'Directory': '<new parent path>'}.")
    if "/" not in key or key.split("/")[0] == "oxford-economics" or parent.split("/")[0] == "oxford-economics":
        raise DemoError(403, "This resource cannot be moved there.")
    target = s.resources.get(parent)
    if target is None:
        raise DemoError(404, f"Folder /{parent} does not exist")
    if target["Type"] != "Directory":
        raise DemoError(400, f"/{parent} is not a folder")
    if parent == key or parent.startswith(key + "/"):
        raise DemoError(400, "A folder cannot be moved into itself.")
    if f"{parent}/{key.rsplit('/', 1)[-1]}" in s.resources:
        raise DemoError(409, f"/{parent} already contains {key.rsplit('/', 1)[-1]}")
    return s.resource_dict(s.move(key, parent))


@route("DELETE", _RES)
def _delete_resource(s: FakeSession, req: DemoRequest):
    key = s.canonical(req.match.group("path"))
    s.resource_dict(key)
    segments = key.split("/")
    if key == USER_ROOT:
        raise DemoError(403, "The workspace root cannot be deleted.")
    in_user_area = segments[0] == USER_ROOT
    in_archive = "$Archive" in segments[:-1] and segments[0] != "oxford-economics"
    if not (in_user_area or in_archive):
        raise DemoError(403, "Deleting shared resources is not allowed. Move the item into the shared "
                             "archive folder ($Archive) first.")
    s.remove(key)
    return 204, None


@route("GET", _FC + "$")
def _get_forecast(s: FakeSession, req: DemoRequest):
    fid = req.match.group("fid")
    fc = s.forecast(fid)
    return {"Id": fid, "Name": fc["name"], "Path": "/" + fc["path"], "Type": "Forecast"}


@route("GET", _FC + "/indicators$")
def _get_indicators(s: FakeSession, req: DemoRequest):
    s.forecast(req.match.group("fid"))
    return [dict(x) for x in INDICATORS]


@route("GET", _FC + "/groups$")
def _get_groups(s: FakeSession, req: DemoRequest):
    s.forecast(req.match.group("fid"))
    return [dict(x) for x in GROUPS]


def _selections(body) -> List[Tuple[str, str, bool]]:
    if not isinstance(body, list):
        raise DemoError(400, "The body must be a list of {IndicatorCode, GroupCode} selections.")
    if len(body) > MAX_SELECTIONS:
        raise DemoError(400, f"At most {MAX_SELECTIONS} selections per request (got {len(body)}).")
    out = []
    for item in body:
        if not isinstance(item, dict) or not item.get("IndicatorCode") or not item.get("GroupCode"):
            raise DemoError(400, "Each selection needs IndicatorCode and GroupCode.")
        annual = str(item.get("Frequency") or "").strip().lower() == "annual"
        out.append((str(item["IndicatorCode"]), str(item["GroupCode"]), annual))
    return out


@route("POST", _FC + "/variables$")
def _post_variables(s: FakeSession, req: DemoRequest):
    fid = req.match.group("fid")
    s.forecast(fid)
    out = []
    for ind, grp, annual in _selections(req.json):
        values = s.values(fid, ind, grp, annual=annual)
        out.append({"IndicatorCode": ind, "GroupCode": grp,
                    "Values": [{"Period": api_period(p), "Value": v} for p, v in values.items()]})
    return out


@route("POST", _FC + "/model-variables$")
def _post_model_variables(s: FakeSession, req: DemoRequest):
    vintage = s.root_vintage(req.match.group("fid"))
    wanted = str(req.params.get("onlyProps") or "Equations,Residuals,Metadata")
    props = {p.strip().lower() for p in wanted.split(",") if p.strip()}
    out = []
    for ind, grp, _ in _selections(req.json):
        equation, rtype = toy_equation(ind, grp)
        item: Dict[str, Any] = {"IndicatorCode": ind, "GroupCode": grp}
        if "equations" in props:
            item["Equations"] = [] if equation is None else equation
        if props & {"equations", "residuals"}:
            item["ResidualType"] = rtype
        if "residuals" in props:
            item["Residuals"] = _residuals(ind, grp, rtype)
        if "metadata" in props:
            item["Metadata"] = toy_metadata(ind, grp, vintage)
        out.append(item)
    return out


# --------------------------------------------------------------------- toy solves
# A demo solve copies the input forecast, applies the commands inside the solution
# range and then spreads the result mechanically (`_spread_shocks`), so that demo
# tables and charts show movement beyond the series a scenario touches. SYNTHETIC:
# the spreading rule is a mechanical device. It links no particular variables, has no
# economic content and says nothing about how the GEM or any other model responds.
SPREAD_SHARE = 0.1   # share of a group's average shock passed on to its other series
SPREAD_CAP = 5.0     # largest pass-through move in one period, in percent
WORLD_GROUP = "WORLD"
SOLVE_BODY_KEYS = ("InputForecast", "SolutionRange", "Commands", "OutputForecast")


def _utc_stamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _demo_commands(text: str) -> List[Command]:
    """Parse the command text of a demo solve; ValueError names the first bad line."""
    out = []
    for n, raw in enumerate(str(text or "").splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        try:
            cmd = Command.from_line(line)
        except ValueError as exc:
            raise ValueError(f"Line {n}: {exc}") from None
        if cmd.verb not in KNOWN_VERBS:
            raise ValueError(f"Line {n}: unknown command {cmd.verb!r} (known: {', '.join(KNOWN_VERBS)}).")
        if cmd.verb in WINDOW_VERBS and cmd.end is None:
            raise ValueError(f"Line {n}: {cmd.verb} needs a window FROM:TO.")
        out.append(cmd)
    return out


def _change(before: Dict[str, float], after: Dict[str, float], period: str, relative: bool) -> float:
    """Change of a series at period (in percent if relative); an annual period averages its
    quarters, a quarterly period takes its year's change."""
    year, quarter = parse_period(period)
    if period in after:
        keys = [period]
    elif quarter == 0:
        keys = [f"{year}Q{q}" for q in range(1, 5) if f"{year}Q{q}" in after]
    else:
        keys = [str(year)] if str(year) in after else []
    moves = []
    for k in keys:
        b, a = before.get(k), after.get(k)
        if b is None or a is None or (relative and b == 0):
            continue
        moves.append(100.0 * (a / b - 1.0) if relative else a - b)
    return sum(moves) / len(moves) if moves else 0.0


def _is_zero(values: Dict[str, float]) -> bool:
    return all(abs(v) < 1e-12 for v in values.values())


def _spread_shocks(s: FakeSession, input_id: str, series: Dict[Tuple[str, str], Dict[str, float]],
                   fixed: set, lo: str, hi: str) -> None:
    """Pass a share of each group's average shock on to its other series (SYNTHETIC).

    The series changed by the commands are the shocks. In each period a group's shock
    is the average move of its shocked series: the percent change, or the change in
    units for a series that is zero in the input forecast (shock and dummy variables).
    Shocks to WORLD series count for every group. Every other series of the demo
    catalogue then moves by SPREAD_SHARE times that shock, capped at SPREAD_CAP
    percent, except in FIXed periods, outside the solution range, and for series that
    are zero in the input forecast. Changes `series` in place.
    """
    shocked: Dict[str, list] = {}
    changed_keys = set()
    for (ind, grp), after in series.items():
        before = s.get_series(input_id, ind, grp)
        if after != before:
            shocked.setdefault(grp, []).append((before, after, not _is_zero(before)))
            changed_keys.add((ind, grp))
    if not shocked:
        return
    memo: Dict[Tuple[str, str], float] = {}

    def group_shock(grp: str, period: str) -> float:
        if (grp, period) not in memo:
            moves = [_change(b, a, period, relative=rel) for b, a, rel in shocked.get(grp, [])]
            memo[(grp, period)] = sum(moves) / len(moves) if moves else 0.0
        return memo[(grp, period)]

    targets = [(i["Code"], g["Code"]) for g in GROUPS for i in INDICATORS]
    for key in targets:
        if key in changed_keys:
            continue
        ind, grp = key
        data = series.get(key) or s.get_series(input_id, ind, grp)
        if not data or _is_zero(data):
            continue
        new, moved = dict(data), False
        for p in data:
            if not in_range(p, lo, hi) or (ind, grp, p) in fixed:
                continue
            shock = group_shock(grp, p) + (group_shock(WORLD_GROUP, p) if grp != WORLD_GROUP else 0.0)
            move = max(-SPREAD_CAP, min(SPREAD_CAP, SPREAD_SHARE * shock))
            if move:
                new[p] = round(data[p] * (1.0 + move / 100.0), 6)
                moved = True
        if moved:
            series[key] = new


def _run_solve(s: FakeSession, op: dict) -> Optional[str]:
    """Carry out a demo solve. Returns a failure reason, or None after creating the output forecast."""
    try:
        commands = _demo_commands(op["_commands"])
    except ValueError as exc:
        return f"Invalid scenario commands. {exc}"
    input_id, (lo, hi), out_key = op["_input_id"], op["_range"], op["_out_key"]
    if out_key in s.resources:
        return f"Output forecast /{out_key} already exists."
    series: Dict[Tuple[str, str], Dict[str, float]] = {}
    fixed: set = set()
    for n, cmd in enumerate(commands, 1):
        ind, grp = cmd.indicator, cmd.group  # a residual target (&X:G) is applied to X:G: crude stand-in
        if cmd.verb in WINDOW_VERBS:
            for p in cmd.periods():
                if in_range(p, lo, hi):
                    (fixed.add if cmd.verb == "FIX" else fixed.discard)((ind, grp, p))
            continue
        data = series.setdefault((ind, grp), s.get_series(input_id, ind, grp))
        for p, v in zip(cmd.periods(), cmd.values):
            if not in_range(p, lo, hi):
                continue
            if p not in data:
                return (f"Line {n}: {cmd.target} has no value in {p}; annual-only economies take annual "
                        "periods (e.g. 2027).")
            if cmd.verb == "SET":
                data[p] = v
            elif cmd.verb == "MULTIPLY":
                data[p] = round(data[p] * v, 6)
            else:
                data[p] = round(data[p] + v, 6)
    _spread_shocks(s, input_id, series, fixed, lo, hi)
    out_id = s.add_forecast(out_key, parent=input_id)
    for (ind, grp), values in series.items():
        if values != s.get_series(input_id, ind, grp):
            s.set_series(out_id, ind, grp, values)
    op["OutputForecastId"] = out_id
    return None


def _public(op: dict) -> dict:
    return {k: v for k, v in op.items() if not k.startswith("_")}


@route(*SOLVE_ROUTE)
def _post_solve(s: FakeSession, req: DemoRequest):
    body = req.json
    if not isinstance(body, dict):
        raise DemoError(400, f"Send a JSON object with {', '.join(SOLVE_BODY_KEYS)}.")
    missing = [k for k in SOLVE_BODY_KEYS if k not in body]
    unknown = sorted(set(body) - set(SOLVE_BODY_KEYS))
    if missing or unknown:
        raise DemoError(400, f"Bad solve request: missing {missing}, unknown {unknown}; "
                             f"send exactly {', '.join(SOLVE_BODY_KEYS)}.")
    rng = body["SolutionRange"]
    try:
        lo, hi = parse_range((rng["From"], rng["To"]))
    except (TypeError, KeyError, ValueError):
        raise DemoError(400, "SolutionRange must be {'From': '2026Q3', 'To': '2031Q4'}.") from None
    if not isinstance(body["Commands"], str):
        raise DemoError(400, "Commands must be one string of newline-separated command lines.")
    source = str(body["InputForecast"] or "")
    input_id = s.forecast_id(source)
    if input_id is None and source in s.forecasts and not s.forecasts[source]["deleted"]:
        input_id = source
    if input_id is None:
        raise DemoError(404, f"Input forecast {source} not found.")
    out_key = s.canonical(body["OutputForecast"])
    parent = out_key.rsplit("/", 1)[0] if "/" in out_key else ""
    if not parent or out_key.split("/")[0] == "oxford-economics":
        raise DemoError(403, "Write solve outputs into your workspace (/me/...) or a shared folder you can write to.")
    taken = any(o["_out_key"] == out_key and o["Status"] in ("Queued", "InProgress") for o in s.operations.values())
    if out_key in s.resources or taken:
        raise DemoError(409, f"/{out_key} already exists: use a new output path (append a timestamp).")
    if s.resources.get(parent, {}).get("Type") != "Directory":
        raise DemoError(404, f"Output folder /{parent} does not exist: create it first.")
    op_id = s._new_id("operation")
    s.operations[op_id] = {
        "Id": op_id, "Status": "Queued", "InputForecast": source, "OutputForecast": body["OutputForecast"],
        "SolutionRange": {"From": lo, "To": hi}, "SubmittedAt": _utc_stamp(),
        "_input_id": input_id, "_range": (lo, hi), "_out_key": out_key, "_commands": body["Commands"],
    }
    return 202, _public(s.operations[op_id])


def _advance(s: FakeSession, op_id: str) -> dict:
    """One status step per request: Queued -> InProgress -> Succeeded/Failed."""
    op = s.operations.get(op_id)
    if op is None:
        raise DemoError(404, f"Operation {op_id} not found.")
    if op["Status"] == "Queued":
        op["Status"] = "InProgress"
    elif op["Status"] == "InProgress":
        reason = _run_solve(s, op)
        op["Status"] = "Failed" if reason else "Succeeded"
        if reason:
            op["FailureReason"] = reason
        op["CompletedAt"] = _utc_stamp()
    return _public(op)


@route(*OPERATION_ROUTE)
def _get_operation(s: FakeSession, req: DemoRequest):
    return _advance(s, req.match.group("op_id"))


@route(*OPERATION_AWAIT_ROUTE)
def _await_operation(s: FakeSession, req: DemoRequest):
    return _advance(s, req.match.group("op_id"))
