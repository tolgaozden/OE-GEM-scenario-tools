"""Model introspection: equations, residual types, parameters and dependencies.

The model-variables endpoint returns, for each INDICATOR:GROUP pair, the equation text
(in a payload whose shape varies), the residual (add-factor) type, the residual values
and a metadata dict. This module turns that into tables and documents:

* `fetch_model_variables`: raw records, batched (at most 400 selections per POST).
* `equation_text`: readable text for an ``Equations`` payload of any shape.
* `equations`: one row per indicator and group (indicator, group, name, residual_type,
  n_residuals, equation, metadata as JSON text); `expand_metadata` turns the metadata
  into columns and `residual_summary` counts residual types per group.
* `parse_references`, `dependencies`, `used_by`, `to_dot`: the variables an equation
  refers to (with lags, leads and residual terms), read in either direction.
* `parse_coefficients`, `parameters`: the numbers in the equation text. The API has no
  parameters endpoint; coefficients exist only as numeric literals in the equations.
* `to_latex` and the writers `export_markdown`, `export_latex`, `export_excel`, `export_json`.
* `group_profile`: one row per group (equation counts, links to other groups, residual
  types) with a heuristic economy class (full, satellite, annual-only, aggregate,
  unknown); the API itself does not flag satellite or aggregate economies.

Equation syntax understood: ``MNEM:GROUP`` references; lags and leads in square brackets
(``X:G[-1]``, ``X:G[+1]``; an unsigned ``X:G[2]`` is read as a lag, as in the MATLAB
converter); ``&X:G`` is an equation residual; function calls such as ``LN(...)``,
``EXP(...)``, ``DLOG(...)``, ``DIFF(...)`` and ``S(x, 4)``; operators ``+ - * / ^``
(``**`` is read as ``^``); parentheses. When the text holds ``LHS = RHS``, `dependencies`
uses the right-hand side only.

Coefficient heuristic (`parse_coefficients`). The text is split into tokens (numbers,
references with optional ``&`` and ``[lag]``, function names, bare names, operators,
parentheses, commas) and each number is classified by its neighbours, in this order:

1. "argument": the number is a whole argument of a function call (the 4 in ``S(X:G, 4)``);
   term = the call.
2. "exponent": the number follows ``^``; term = the base it raises.
3. "coefficient": the number follows ``factor *``; term = that factor.
4. "constant": the number follows ``/`` (a divisor); term shows the division.
5. "coefficient": the number is followed by ``*``; term = the next factor: a reference, a
   bare name, a whole function call or a parenthesised group (balanced parentheses),
   together with a ``^`` power of it.
6. "constant": anything else, e.g. a stand-alone added or subtracted number (term "").

A factor is a reference, a bare name, a number, a function call or a parenthesised group.
Signs: a minus directly in front of the number (unary or binary) is applied, so
``0 - 1.25`` gives the constant -1.25 and ``X:G - 0.5 * Y:G`` gives -0.5 for ``Y:G``; for
rule 3 a minus in front of the factor is applied too (``- Y:G * 0.5`` gives -0.5). The zero
of the ``0 - x`` idiom is not reported. A number raised to a power (``2 ^ 3 * X:G``) is
classified by what follows the power.

Limits: the heuristic reads text, not algebra. It does not distribute signs or factors
over parentheses (in ``-(0.5 * X:G)`` it reports 0.5), does not multiply chains of numbers
(``2 * 0.5 * X:G`` gives two entries), reports a number inside a function call relative to
that call only, and cannot tell estimated parameters from fixed scaling numbers such as
100 or 4. Use it to locate numbers in the text and read the equation before relying on a
value. Tokens it does not know (comparison operators, other symbols) are kept as plain
operators.

Equation text, and every table and file built from it, is licensed model content: keep the
outputs (default folder ``outputs/equations``) out of shared or public repositories.
"""
from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple
from urllib.parse import quote

import pandas as pd

from .catalogue import _snake
from .catalogue import indicators as _catalogue_indicators
from .client import as_records
from .data import MAX_BATCH, _batch, _codes, _parse_pairs

log = logging.getLogger("oegem")

DEFAULT_DIR = Path("outputs") / "equations"
DEFAULT_PROPS = ("Equations", "Residuals", "Metadata")
TEXT_KEYS = ("Equation", "Definition", "Expression", "Formula", "Text")
EQUATION_COLUMNS = ["indicator", "group", "name", "residual_type", "n_residuals", "equation", "metadata"]
DEPENDENCY_COLUMNS = ["indicator", "group", "ref_indicator", "ref_group", "lag", "is_residual"]
PARAMETER_COLUMNS = ["indicator", "group", "idx", "value", "term", "kind"]
RESIDUAL_SUMMARY_COLUMNS = ["group", "residual_type", "indicators", "with_equation"]
COEF_KINDS = ("constant", "coefficient", "exponent", "argument")
EXCEL_CELL_LIMIT = 32767
NOTICE = ("Equation text comes from the model release that was queried and is licensed model "
          "content: keep this file out of shared or public repositories.")


# ------------------------------------------------------------------- fetching


def _forecast_id(forecast) -> str:
    """Forecast id from an id string or a resource dict (as returned by resolve_release)."""
    if isinstance(forecast, Mapping):
        fid = forecast.get("Id") or forecast.get("id")
        if not fid:
            raise ValueError("The resource dict has no 'Id': pass a forecast id or the dict from resolve_release().")
        return str(fid)
    fid = str(forecast or "").strip()
    if not fid:
        raise ValueError("Give a forecast id (or the dict returned by resolve_release()).")
    return fid


def fetch_model_variables(client, forecast_id, pairs, props=DEFAULT_PROPS, batch: int = MAX_BATCH) -> List[dict]:
    """Raw model-variables records for some INDICATOR:GROUP pairs.

    Args: forecast_id is a forecast id (or the dict from resolve_release); pairs is a list
    of "IND:GRP" strings or (ind, grp) tuples (a leading "&" is ignored: a residual belongs
    to its variable's equation); props lists the properties to ask for (any of Equations,
    Residuals, Metadata); batch is the number of selections per POST (at most 400).
    Returns one dict per record as the API sends it (IndicatorCode, GroupCode, Equations,
    ResidualType, Residuals, Metadata); missing codes are filled in from the request.
    """
    fid = _forecast_id(forecast_id)
    items = [pairs] if isinstance(pairs, str) else list(pairs or [])
    sel = _parse_pairs([p.strip().lstrip("&") if isinstance(p, str) else p for p in items])
    if not sel:
        raise ValueError("Give at least one pair, e.g. pairs=['AAA:ALPHA'] (check codes with `oegem catalogue`).")
    names = [props] if isinstance(props, str) else list(props or [])
    only = ",".join(str(p).strip() for p in names if str(p).strip())
    size = _batch(batch)
    url = f"/v1/forecast-contents/{quote(fid, safe='')}/model-variables"
    out: List[dict] = []
    for start in range(0, len(sel), size):
        chunk = sel[start:start + size]
        body = [{"IndicatorCode": i, "GroupCode": g} for i, g in chunk]
        records = as_records(client.post(url, json=body, params={"onlyProps": only} if only else None))
        for j, item in enumerate(records):
            rec = dict(item)
            if j < len(chunk):
                if not rec.get("IndicatorCode"):
                    rec["IndicatorCode"] = chunk[j][0]
                if not rec.get("GroupCode"):
                    rec["GroupCode"] = chunk[j][1]
            out.append(rec)
    log.info("model-variables: %d records for %d pairs", len(out), len(sel))
    return out


def equation_text(payload) -> str:
    """Readable text for an Equations payload, whatever its shape.

    Args: payload is a string, a list of strings, a dict or a list of dicts. For a dict the
    first non-empty value under Equation, Definition, Expression, Formula or Text (any case)
    is used, otherwise the dict is written as JSON. Strings in a list are joined by newlines;
    a list holding dicts is joined with a "---" line between entries.
    Returns the text ("" for None or an empty payload).
    """
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload.strip()
    if isinstance(payload, Mapping):
        lower = {str(k).lower(): v for k, v in payload.items()}
        for key in TEXT_KEYS:
            text = equation_text(lower.get(key.lower()))
            if text:
                return text
        return json.dumps(payload, indent=2, ensure_ascii=False, default=str) if payload else ""
    if isinstance(payload, (list, tuple)):
        parts = [p for p in (equation_text(x) for x in payload) if p]
        sep = "\n" if all(isinstance(x, str) for x in payload) else "\n---\n"
        return sep.join(parts)
    return json.dumps(payload, default=str)


def metadata_text(meta) -> str:
    """Metadata dict as compact JSON text ("" when there is none)."""
    if meta is None or (isinstance(meta, (dict, list, str)) and not meta):
        return ""
    return json.dumps(meta, ensure_ascii=False, default=str)


def is_private_field(key) -> bool:
    """True for metadata fields that hold personal data of the vendor's staff (Contact...)
    or internal record ids. Tables and exports leave them out unless asked to keep them."""
    k = re.sub(r"[^a-z]", "", str(key).lower())
    return k.startswith("contact") or k == "internalid"


def drop_private(meta, *, keep_contacts: bool = False):
    """Metadata without contact fields and internal ids, nested dicts included."""
    if keep_contacts or not isinstance(meta, Mapping):
        return meta
    return {k: (drop_private(v) if isinstance(v, Mapping) else v)
            for k, v in meta.items() if not is_private_field(k)}


def equations(client, forecast_id, *, groups, indicators=None, only_with_equations: bool = False,
              batch: int = MAX_BATCH, expand_meta: bool = False,
              keep_contacts: bool = False) -> pd.DataFrame:
    """Equations, residual types and metadata for indicators of some groups.

    Args: forecast_id is a forecast id (or the dict from resolve_release); groups is a list
    of group codes (or a comma-separated string); indicators is a list of codes, or None /
    "all" for the whole catalogue; only_with_equations drops identities and exogenous
    series (rows with no equation); batch is the number of selections per POST;
    expand_meta adds one column per metadata field (see expand_metadata); keep_contacts
    keeps the vendor's staff contact fields and internal ids in the metadata, which are
    left out by default (personal data; never share or commit output that keeps them).
    Returns a DataFrame with columns indicator, group, name, residual_type ("" if none),
    n_residuals, equation (text, "" if none) and metadata (JSON text), in request order.
    """
    fid = _forecast_id(forecast_id)
    grps = _codes(groups)
    if not grps:
        raise ValueError("Give at least one group code, e.g. groups=['US'] (list them with `oegem catalogue groups`).")
    cat = _catalogue_indicators(client, fid)
    names = dict(zip(cat["code"].astype(str), cat["name"].fillna("").astype(str)))
    if indicators is None or (isinstance(indicators, str) and indicators.strip().lower() == "all"):
        inds = list(names)
    else:
        inds = _codes(indicators)
    if not inds:
        raise ValueError("No indicators to ask for: pass codes, e.g. indicators=['AAA'], or None for all.")
    recs = fetch_model_variables(client, fid, [(i, g) for g in grps for i in inds], batch=batch)
    rows = []
    for rec in recs:
        ind, grp = str(rec.get("IndicatorCode") or ""), str(rec.get("GroupCode") or "")
        meta = drop_private(rec.get("Metadata"), keep_contacts=keep_contacts)
        name = names.get(ind) or ((meta.get("Name") or meta.get("Description"))
                                   if isinstance(meta, Mapping) else None) or ""
        residuals = rec.get("Residuals")
        rows.append({"indicator": ind, "group": grp, "name": str(name),
                     "residual_type": str(rec.get("ResidualType") or ""),
                     "n_residuals": len(residuals) if isinstance(residuals, (list, tuple)) else 0,
                     "equation": equation_text(rec.get("Equations")),
                     "metadata": metadata_text(meta)})
    df = pd.DataFrame(rows, columns=EQUATION_COLUMNS)
    if only_with_equations:
        df = df[df["equation"] != ""]
    df = df.reset_index(drop=True)
    df["n_residuals"] = df["n_residuals"].astype(int)
    log.info("equations: %d variables, %d with an equation", len(df), int((df["equation"] != "").sum()))
    return expand_metadata(df) if expand_meta else df


def _check(eq_df: pd.DataFrame, needed=("indicator", "group", "equation")) -> pd.DataFrame:
    missing = [c for c in needed if c not in getattr(eq_df, "columns", [])]
    if missing:
        raise ValueError(f"Expected an equations table (from equations()) with columns {list(needed)}; "
                         f"missing {missing}.")
    return eq_df


def _text(v) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    return str(v)


def expand_metadata(eq_df: pd.DataFrame, *, prefix: str = "meta_") -> pd.DataFrame:
    """Add one column per metadata field to an equations table.

    Args: eq_df is the table from equations() (its metadata column holds JSON text);
    prefix starts each new column name (field names are snake_cased).
    Returns a copy with the new columns appended; nested values stay JSON text.
    """
    _check(eq_df, ("metadata",))
    parsed = []
    for raw in eq_df["metadata"]:
        try:
            meta = json.loads(raw) if _text(raw) else {}
        except ValueError:
            meta = {}
        flat = {}
        for key, value in (meta.items() if isinstance(meta, dict) else []):
            simple = value is None or isinstance(value, (str, int, float, bool))
            flat[prefix + _snake(key)] = value if simple else json.dumps(value, ensure_ascii=False, default=str)
        parsed.append(flat)
    out = eq_df.copy()
    cols: List[str] = []
    for flat in parsed:
        cols += [c for c in flat if c not in cols and c not in out.columns]
    for col in cols:
        out[col] = [flat.get(col) for flat in parsed]
    return out


def residual_summary(eq_df: pd.DataFrame) -> pd.DataFrame:
    """Count variables per group and residual type ("none" when a variable has none).

    Returns columns group, residual_type, indicators (number of variables) and with_equation
    (how many of them returned an equation).
    """
    _check(eq_df, ("group", "residual_type", "equation"))
    if eq_df.empty:
        return pd.DataFrame(columns=RESIDUAL_SUMMARY_COLUMNS)
    df = pd.DataFrame({"group": eq_df["group"].map(_text),
                       "residual_type": eq_df["residual_type"].map(_text).replace("", "none"),
                       "has_eq": eq_df["equation"].map(lambda v: bool(_text(v).strip()))})
    out = df.groupby(["group", "residual_type"], sort=True).agg(
        indicators=("has_eq", "size"), with_equation=("has_eq", "sum")).reset_index()
    out["with_equation"] = out["with_equation"].astype(int)
    return out[RESIDUAL_SUMMARY_COLUMNS]


# ------------------------------------------------------------------ tokenizer

_TOKEN_RE = re.compile(
    r"(?P<ws>\s+)"
    r"|(?P<num>(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?)"
    r"|(?P<name>&?[A-Za-z_][A-Za-z0-9_]*(?::[A-Za-z_][A-Za-z0-9_]*)?)(?P<lag>\s*\[\s*[+-]?\s*\d+\s*\])?"
    r"|(?P<op>\*\*|[<>=!]=|[-+*/^=<>])"
    r"|(?P<punct>[(),])"
    r"|(?P<other>.)", re.DOTALL)


class _Tok:
    """One token: kind is num, ref, func, name, op, "(", ")", "," or other."""

    __slots__ = ("kind", "text", "start", "end", "lag")

    def __init__(self, kind: str, text: str, start: int, end: int, lag: Optional[int] = None):
        self.kind, self.text, self.start, self.end, self.lag = kind, text, start, end, lag


def _lag_value(text: str) -> int:
    s = re.sub(r"[\[\]\s]", "", text)
    return int(s) if s[0] in "+-" else -int(s)   # unsigned: a lag, as in the MATLAB converter


def _tokens(eq: str) -> List[_Tok]:
    toks: List[_Tok] = []
    for m in _TOKEN_RE.finditer(eq):
        if m.group("ws"):
            continue
        start, end = m.span()
        if m.group("num") is not None:
            toks.append(_Tok("num", m.group("num"), start, end))
        elif m.group("name") is not None:
            name, lag = m.group("name"), m.group("lag")
            toks.append(_Tok("ref" if ":" in name else "name", name, start, end,
                             _lag_value(lag) if lag else None))
        elif m.group("op") is not None:
            op = m.group("op")
            toks.append(_Tok("op", "^" if op == "**" else op, start, end))
        elif m.group("punct") is not None:
            toks.append(_Tok(m.group("punct"), m.group("punct"), start, end))
        else:
            toks.append(_Tok("other", m.group("other"), start, end))
    for i in range(len(toks) - 1):
        t = toks[i]
        if t.kind == "name" and not t.text.startswith("&") and t.lag is None and toks[i + 1].kind == "(":
            t.kind = "func"
    return toks


def _is(tok: Optional[_Tok], op: str) -> bool:
    return tok is not None and tok.kind == "op" and tok.text == op


def _match_close(toks: List[_Tok], i: int) -> int:
    depth = 0
    for k in range(i, len(toks)):
        depth += {"(": 1, ")": -1}.get(toks[k].kind, 0)
        if depth == 0:
            return k
    return len(toks) - 1


def _match_open(toks: List[_Tok], j: int) -> int:
    depth = 0
    for k in range(j, -1, -1):
        depth += {")": 1, "(": -1}.get(toks[k].kind, 0)
        if depth == 0:
            return k
    return 0


def _enclosing_open(toks: List[_Tok], a: int) -> Optional[int]:
    depth = 0
    for k in range(a - 1, -1, -1):
        if toks[k].kind == ")":
            depth += 1
        elif toks[k].kind == "(":
            if depth == 0:
                return k
            depth -= 1
    return None


def _factor_after(toks: List[_Tok], i: int) -> Optional[Tuple[int, int]]:
    """Token span of the factor starting at toks[i], with a ^ power of it; None if no factor."""
    if i >= len(toks):
        return None
    t = toks[i]
    if t.kind in ("ref", "name", "num"):
        k = i
    elif t.kind == "func":
        k = _match_close(toks, i + 1)
    elif t.kind == "(":
        k = _match_close(toks, i)
    else:
        return None
    if _is(toks[k + 1] if k + 1 < len(toks) else None, "^"):
        j = k + 2
        if j < len(toks) and toks[j].kind == "op" and toks[j].text in ("+", "-"):
            j += 1
        power = _factor_after(toks, j)
        if power is not None:
            k = power[1]
    return i, k


def _factor_before(toks: List[_Tok], j: int) -> Optional[Tuple[int, int]]:
    """Token span of the factor ending at toks[j] (with the base when it is a power); None if none."""
    if j < 0 or j >= len(toks):
        return None
    t = toks[j]
    if t.kind in ("ref", "name", "num"):
        i = j
    elif t.kind == ")":
        i = _match_open(toks, j)
        if i > 0 and toks[i - 1].kind == "func":
            i -= 1
    else:
        return None
    if i >= 2 and _is(toks[i - 1], "^"):
        base = _factor_before(toks, i - 2)
        if base is not None:
            i = base[0]
    return i, j


def _span(text: str, toks: List[_Tok], i: int, k: int) -> str:
    return text[toks[i].start:toks[k].end]


# ------------------------------------------------------------------ references


@dataclass(frozen=True)
class Ref:
    """A variable reference in an equation: lag < 0 is a lag, > 0 a lead; is_residual for &X:G."""

    indicator: str
    group: str
    lag: int = 0
    is_residual: bool = False

    @property
    def key(self) -> str:
        """ "IND:GRP" without lag or residual marker."""
        return f"{self.indicator}:{self.group}"

    @property
    def text(self) -> str:
        """The reference as equation syntax, e.g. "&AAA:ALPHA" or "AAA:ALPHA[-1]"."""
        lag = f"[{self.lag:+d}]" if self.lag else ""
        return f"{'&' if self.is_residual else ''}{self.key}{lag}"


def _rhs_start(toks: List[_Tok]) -> int:
    depth = 0
    for k, t in enumerate(toks):
        depth += {"(": 1, ")": -1}.get(t.kind, 0)
        if depth == 0 and _is(t, "="):
            return k + 1
    return 0


def parse_references(eq, *, unique: bool = True, rhs_only: bool = False) -> List[Ref]:
    """Variable references (MNEM:GROUP, with lag/lead and residual flag) in an equation.

    Args: eq is the equation text; unique drops repeats (same variable, lag and residual
    flag), keeping the order of first appearance; rhs_only skips everything up to the first
    top-level "=" when there is one. Function names and names without a group are not
    references. An unsigned bracket (X:G[2]) is read as a lag (-2).
    Returns a list of Ref.
    """
    toks = _tokens(str(eq or ""))
    refs: List[Ref] = []
    for t in toks[_rhs_start(toks) if rhs_only else 0:]:
        if t.kind != "ref":
            continue
        ind, grp = t.text.lstrip("&").split(":", 1)
        ref = Ref(ind, grp, t.lag or 0, t.text.startswith("&"))
        if not unique or ref not in refs:
            refs.append(ref)
    return refs


# ---------------------------------------------------------------- coefficients


@dataclass
class Coef:
    """A number in an equation: value (sign applied), the term it belongs to, its kind
    (constant, coefficient, exponent or argument) and its character offset in the text."""

    value: float
    term: str
    kind: str
    position: int


def parse_coefficients(eq) -> List[Coef]:
    """Numeric literals of an equation, classified by the heuristic in the module docstring.

    Args: eq is the equation text.
    Returns a list of Coef in text order (value with its sign, term, kind, position =
    offset of the number in the text).
    """
    text = str(eq or "")
    toks = _tokens(text)
    n = len(toks)
    out: List[Coef] = []
    for p, t in enumerate(toks):
        if t.kind != "num":
            continue
        value, sign, a = float(t.text), 1.0, p          # a = first token of the signed number
        if p > 0 and toks[p - 1].kind == "op" and toks[p - 1].text in ("+", "-"):
            sign = -1.0 if toks[p - 1].text == "-" else 1.0
            if p < 2 or toks[p - 2].kind in ("op", "(", ","):
                a = p - 1                                # a unary sign belongs to the number
        prev = toks[a - 1] if a > 0 else None
        nxt = toks[p + 1] if p + 1 < n else None

        if prev is not None and prev.kind in ("(", ",") and nxt is not None and nxt.kind in (",", ")"):
            opened = _enclosing_open(toks, a)
            if opened is not None and opened > 0 and toks[opened - 1].kind == "func":
                term = _span(text, toks, opened - 1, _match_close(toks, opened))
                out.append(Coef(sign * value, term, "argument", t.start))
                continue
        if _is(prev, "^"):
            base = _factor_before(toks, a - 2)
            out.append(Coef(sign * value, _span(text, toks, *base) if base else "", "exponent", t.start))
            continue
        if _is(prev, "*"):
            factor = _factor_before(toks, a - 2)
            if factor is not None:
                lead = -1.0 if factor[0] > 0 and _is(toks[factor[0] - 1], "-") else 1.0
                out.append(Coef(lead * sign * value, _span(text, toks, *factor), "coefficient", t.start))
                continue
        if _is(prev, "/"):
            factor = _factor_before(toks, a - 2)
            out.append(Coef(sign * value, _span(text, toks, factor[0] if factor else a - 1, p), "constant", t.start))
            continue

        q = p                                            # a number raised to a power: look past the power
        if _is(nxt, "^"):
            q = (_factor_after(toks, p) or (p, p))[1]
        after = toks[q + 1] if q + 1 < n else None
        if _is(after, "*"):
            j, s = q + 2, sign
            if j < n and toks[j].kind == "op" and toks[j].text in ("+", "-"):
                s = -s if toks[j].text == "-" else s
                j += 1
            factor = _factor_after(toks, j)
            if factor is not None:
                out.append(Coef(s * value, _span(text, toks, *factor), "coefficient", t.start))
                continue
        if _is(after, "/"):
            factor = _factor_after(toks, q + 2)
            out.append(Coef(sign * value, _span(text, toks, p, factor[1] if factor else q + 1), "constant", t.start))
            continue
        if value == 0.0 and q == p and _is(after, "-") and (prev is None or prev.kind in ("(", ",", "op")):
            continue                                     # the 0 of the "0 - x" idiom
        out.append(Coef(sign * value, "", "constant", t.start))
    return out


# ---------------------------------------------------------------------- tables


def _dependency_table(eq_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for ind, grp, eq in _check(eq_df)[["indicator", "group", "equation"]].itertuples(index=False, name=None):
        for ref in parse_references(_text(eq), rhs_only=True):
            rows.append((_text(ind), _text(grp), ref.indicator, ref.group, ref.lag, ref.is_residual))
    df = pd.DataFrame(rows, columns=DEPENDENCY_COLUMNS)
    df["lag"] = df["lag"].astype(int)
    df["is_residual"] = df["is_residual"].astype(bool)
    return df


def dependencies(eq_df: pd.DataFrame) -> pd.DataFrame:
    """One row per variable referenced on the right-hand side of each equation.

    Args: eq_df is the table from equations() (columns indicator, group, equation).
    Returns columns indicator, group (the equation's variable), ref_indicator, ref_group,
    lag (negative = lag, positive = lead) and is_residual (True for &X:G terms).
    """
    return _dependency_table(eq_df)


def _parameter_table(eq_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for ind, grp, eq in _check(eq_df)[["indicator", "group", "equation"]].itertuples(index=False, name=None):
        eq = _text(eq)
        if not looks_algebraic(eq):
            continue
        for k, c in enumerate(parse_coefficients(eq), start=1):
            rows.append((_text(ind), _text(grp), k, c.value, c.term, c.kind))
    df = pd.DataFrame(rows, columns=PARAMETER_COLUMNS)
    df["idx"] = df["idx"].astype(int)
    df["value"] = df["value"].astype(float)
    return df


def parameters(eq_df: pd.DataFrame) -> pd.DataFrame:
    """Numbers in each equation, classified by `parse_coefficients` (a documented heuristic).

    Args: eq_df is the table from equations(). Rows whose text does not look like an
    equation (prose or JSON) are skipped.
    Returns columns indicator, group, idx (1-based order in the equation), value, term, kind.
    """
    return _parameter_table(eq_df)


def used_by(dep_df: pd.DataFrame, indicator, group=None) -> pd.DataFrame:
    """Equations that refer to a variable (the reverse of the dependency table).

    Args: dep_df is the table from dependencies(); indicator is a code ("AAA") or a
    variable key ("AAA:ALPHA", a leading "&" is ignored); group optionally restricts the
    referenced group. Matching ignores case.
    Returns the matching rows of dep_df, sorted by group and indicator.
    """
    _check(dep_df, ("indicator", "group", "ref_indicator", "ref_group"))
    code = str(indicator).strip().lstrip("&")
    if group is None and ":" in code:
        code, group = code.split(":", 1)
    mask = dep_df["ref_indicator"].astype(str).str.upper() == code.upper()
    if group is not None and str(group).strip():
        mask &= dep_df["ref_group"].astype(str).str.upper() == str(group).strip().upper()
    return dep_df[mask].sort_values(["group", "indicator"], kind="stable").reset_index(drop=True)


# -------------------------------------------------------------- economy profile

PROFILE_COLUMNS = ["group", "n_variables", "n_with_equation", "n_with_residual", "share_external_refs",
                   "top_partners", "residual_types", "frequency", "suggested_class"]
PROFILE_CLASSES = ("full", "satellite", "annual-only", "aggregate", "unknown")
SATELLITE_EXTERNAL_SHARE = 0.5     # share of a group's equations that refer to other groups
SATELLITE_RESIDUAL_RATIO = 0.5     # equations with a residual, relative to the median group
AGGREGATE_SHARE = 0.5              # share of a group's equations that are weighted sums of other groups
MEDIAN_MIN_GROUPS = 3              # groups with equations needed before the median comparison applies
TOP_PARTNERS = 3


def _freq_code(value) -> str:
    s = _text(value).strip().upper()
    if not s or s in ("NAN", "NONE"):
        return ""
    if "Q" in s:
        return "Q"
    return "A" if s[0] in "AY" else s


def _group_frequencies(freq_map) -> Dict[str, str]:
    """Group -> "Q"/"A" from a dict, a long frame (group, freq) or a data.frequency_map() table."""
    if freq_map is None:
        return {}
    if isinstance(freq_map, pd.DataFrame):
        if {"group", "freq"} <= set(freq_map.columns):
            return {str(g): ("Q" if (sub["freq"].astype(str) == "Q").any() else "A")
                    for g, sub in freq_map.groupby("group")}
        out = {}
        for grp, row in freq_map.iterrows():
            codes = {_freq_code(v) for v in row.tolist()} - {""}
            if codes:
                out[str(grp)] = "Q" if "Q" in codes else "A"
        return out
    if isinstance(freq_map, Mapping):
        return {str(k): _freq_code(v) for k, v in freq_map.items()}
    raise ValueError("freq_map must be a dict {group: 'Q' or 'A'}, a long frame or the table from "
                     "oegem.data.frequency_map().")


def _is_weighted_sum(eq: str, group: str) -> bool:
    """True when the right-hand side only adds up other groups' variables with numeric weights."""
    toks = _tokens(eq)
    others = set()
    for t in toks[_rhs_start(toks):]:
        if t.kind == "ref":
            grp = t.text.split(":", 1)[1].upper()
            if t.text.startswith("&") or grp == group.upper():
                return False
            others.add(grp)
        elif t.kind in ("func", "name", "other") or (t.kind == "op" and t.text not in ("+", "-", "*", "/")):
            return False
    return len(others) >= 2


def group_profile(eq_df: pd.DataFrame, *, freq_map=None, external_share: float = SATELLITE_EXTERNAL_SHARE,
                  residual_ratio: float = SATELLITE_RESIDUAL_RATIO,
                  aggregate_share: float = AGGREGATE_SHARE) -> pd.DataFrame:
    """Profile of each group's equations, with a HEURISTIC economy class.

    The class is a heuristic read from equation text, NOT vendor metadata: the API does not
    flag satellite, aggregate or annual-only economies (the groups catalogue gives every
    group the same Type). Use it to decide where to look, and read the equations before
    relying on it.

    Args: eq_df is the table from equations() (columns indicator, group, residual_type,
    equation); freq_map optionally gives each group's data frequency: a dict
    {group: "Q"/"A"}, a long frame, or the table from oegem.data.frequency_map();
    external_share, residual_ratio and aggregate_share are the thresholds below.
    Returns one row per group (in order of appearance) with columns group, n_variables,
    n_with_equation, n_with_residual (rows with a residual type, read as behavioural
    equations; identities have none), share_external_refs (share of the equations whose
    right-hand side refers to another group), top_partners (the other groups referred to
    most, "CODE (n)", n = equations referring to it), residual_types (counts), frequency
    (from freq_map; "" when unknown) and suggested_class, set by the first rule that holds:

    1. "annual-only": freq_map says the group's data are annual.
    2. "unknown": no equations returned for the group.
    3. "aggregate": at least aggregate_share (0.5) of its equations are weighted sums of
       other groups: they refer to two or more other groups, never to the own group, and
       use only numbers, + - * / and parentheses (no functions, powers or residuals).
    4. "satellite": share_external_refs >= external_share (0.5), or, when at least three
       groups have equations, n_with_residual < residual_ratio (0.5) x the median
       n_with_residual of those groups.
    5. "full": everything else.

    The median comparison is relative to the groups in eq_df: profile comparable groups
    with the same indicator selection.
    """
    _check(eq_df, ("indicator", "group", "equation"))
    freqs = _group_frequencies(freq_map)
    group_col = eq_df["group"].map(_text)
    stats = []
    for grp in dict.fromkeys(group_col):
        sub = eq_df[group_col == grp]
        eqs = [e for e in (_text(v).strip() for v in sub["equation"]) if e]
        rtypes: List[str] = []
        if "residual_type" in sub.columns:
            rtypes = [r for r in (_text(v).strip() for v in sub["residual_type"]) if r and r.lower() != "none"]
        partners: Dict[str, int] = {}
        n_external = n_sum = 0
        for eq in eqs:
            others = {r.group for r in parse_references(eq, rhs_only=True) if r.group.upper() != grp.upper()}
            n_external += bool(others)
            n_sum += _is_weighted_sum(eq, grp)
            for other in others:
                partners[other] = partners.get(other, 0) + 1
        stats.append((grp, len(sub), len(eqs), len(rtypes), n_external, n_sum, partners, Counter(rtypes)))
    behavioural = [s[3] for s in stats if s[2] > 0]
    median = float(pd.Series(behavioural).median()) if len(behavioural) >= MEDIAN_MIN_GROUPS else None
    rows = []
    for grp, n_var, n_eq, n_res, n_ext, n_sum, partners, counts in stats:
        share = n_ext / n_eq if n_eq else 0.0
        freq = freqs.get(grp, "")
        if freq == "A":
            cls = "annual-only"
        elif n_eq == 0:
            cls = "unknown"
        elif n_sum / n_eq >= aggregate_share:
            cls = "aggregate"
        elif share >= external_share or (median is not None and n_res < residual_ratio * median):
            cls = "satellite"
        else:
            cls = "full"
        top = sorted(partners.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_PARTNERS]
        kinds = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        rows.append({"group": grp, "n_variables": n_var, "n_with_equation": n_eq, "n_with_residual": n_res,
                     "share_external_refs": round(share, 3),
                     "top_partners": ", ".join(f"{g} ({n})" for g, n in top),
                     "residual_types": ", ".join(f"{t} {n}" for t, n in kinds),
                     "frequency": freq, "suggested_class": cls})
    out = pd.DataFrame(rows, columns=PROFILE_COLUMNS)
    log.info("group profile: %d groups (heuristic classes: %s)", len(out),
             ", ".join(f"{c} {n}" for c, n in out["suggested_class"].value_counts().items()) or "none")
    return out


# ----------------------------------------------------------------------- LaTeX

_LATEX_TOKEN = re.compile(r"(?<![A-Za-z0-9_.])(?P<amp>&?)(?P<name>[A-Za-z][A-Za-z0-9_]*(?::[A-Za-z][A-Za-z0-9_]*)?)"
                          r"(?P<lag>\[\s*[+-]?\s*\d+\s*\])?(?P<paren>\()?")
_LATEX_FUNCS = {"LOG": r"\log(", "LN": r"\log(", "DLOG": r"\Delta\log(", "EXP": r"\exp(",
                "DIFF": r"\Delta(", "D": r"\Delta("}


def _latex_token(m: "re.Match") -> str:
    amp, name, lag, paren = m.group("amp"), m.group("name"), m.group("lag") or "", m.group("paren") or ""
    if paren and not amp and not lag and name.upper() in _LATEX_FUNCS:
        return _LATEX_FUNCS[name.upper()]
    base = r"\mathrm{" + name.replace("_", r"\_") + "}"
    if amp:
        base = r"\varepsilon_{" + base + "}"
    if lag:
        sub = re.sub(r"[\[\]\s]", "", lag)
        sub = sub if sub[0] in "+-" else "-" + sub
        base = ("{" + base + "}" if amp else base) + "_{t" + sub + "}"
    return base + paren


def to_latex(eq) -> str:
    """Equation text as LaTeX math (a port of the MATLAB converter oe_eq_latex).

    MNEM:GROUP becomes \\mathrm{MNEM:GROUP}; X:G[-1] gets the subscript t-1 (leads t+1);
    &X:G becomes \\varepsilon_{X:G}; LOG/LN, DLOG, EXP, DIFF/D become \\log, \\Delta\\log,
    \\exp, \\Delta; * becomes \\cdot and ^n becomes ^{n}; & % # $ left in the text are
    escaped. Other functions keep their names. The text is not checked for validity.
    Returns "" for empty input.
    """
    s = _text(eq).strip()
    if not s:
        return ""
    out = _LATEX_TOKEN.sub(_latex_token, s)
    out = re.sub(r"\s*\*\s*", lambda m: r" \cdot ", out)
    out = re.sub(r"\^\s*([+-]?[A-Za-z0-9.]+)", lambda m: "^{" + m.group(1) + "}", out)
    for ch in "&%#$":
        out = re.sub(r"(?<!\\)" + re.escape(ch), lambda m: "\\" + m.group(0), out)
    return out


def looks_algebraic(text) -> bool:
    """True for text that refers to MNEM:GROUP variables and does not read like prose or JSON."""
    s = _text(text).strip()
    return (bool(s) and s[0] not in "{[" and re.search(r"[A-Za-z][A-Za-z0-9_]*:[A-Za-z]", s) is not None
            and re.search(r" & | and |,\s*[a-z]", s) is None)


# --------------------------------------------------------------------- writers


def _out_path(path, default_name: str) -> Path:
    """Target file: path as given, <path>/<default_name> for a folder, or outputs/equations/<name>."""
    p = DEFAULT_DIR / default_name if path is None else Path(path)
    if path is not None and (p.is_dir() or not p.suffix):
        p = p / default_name
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _glossary(eq_df: pd.DataFrame, glossary) -> List[Tuple[str, str]]:
    """(code, name) for every indicator with a row or referenced in an equation, sorted by code."""
    names: Dict[str, str] = {}
    if isinstance(glossary, pd.DataFrame) and {"code", "name"} <= set(glossary.columns):
        names.update(zip(glossary["code"].map(_text), glossary["name"].map(_text)))
    elif isinstance(glossary, Mapping):
        names.update({_text(k): _text(v) for k, v in glossary.items()})
    if "name" in eq_df.columns:
        for code, name in zip(eq_df["indicator"].map(_text), eq_df["name"].map(_text)):
            if name and not names.get(code):
                names[code] = name
    codes = set(eq_df["indicator"].map(_text))
    for eq in eq_df["equation"]:
        codes.update(r.indicator for r in parse_references(_text(eq)))
    return [(c, names.get(c, "")) for c in sorted(codes - {""}, key=lambda c: (c.lower(), c))]


def _md_text(s) -> str:
    out = _text(s)
    for ch in ("\\", "$", "*", "_", "`"):
        out = out.replace(ch, "\\" + ch)
    return out


def _md_cell(s) -> str:
    return re.sub(r"\s*[\r\n]+\s*", " ", _md_text(s).replace("|", "\\|"))


def _fence(text: str) -> str:
    ticks = max([len(m) for m in re.findall(r"`+", text)] + [2]) + 1
    return f"{'`' * ticks}text\n{text}\n{'`' * ticks}"


def _residual_note(row: Mapping) -> str:
    parts = []
    if _text(row.get("residual_type")):
        parts.append(f"Residual: {_text(row.get('residual_type'))}")
    n = row.get("n_residuals")
    if n is not None and not (isinstance(n, float) and math.isnan(n)) and int(n) > 0:
        parts.append(f"{int(n)} residual entries")
    return "; ".join(parts)


def _by_group(eq_df: pd.DataFrame) -> Iterable[Tuple[str, List[dict]]]:
    records = eq_df.to_dict("records")
    order: List[str] = []
    for r in records:
        if _text(r.get("group")) not in order:
            order.append(_text(r.get("group")))
    for grp in order:
        yield grp, [r for r in records if _text(r.get("group")) == grp]


def _stamp(eq_df: pd.DataFrame) -> str:
    n_eq = int(eq_df["equation"].map(lambda v: bool(_text(v).strip())).sum())
    n_grp = eq_df["group"].nunique()
    return f"Written {datetime.now():%Y-%m-%d %H:%M}. {len(eq_df)} variables in {n_grp} group(s), {n_eq} with an equation."


def export_markdown(eq_df: pd.DataFrame, path=None, *, glossary=None, render_math: bool = False,
                    title: str = "Model equations") -> Path:
    """Write equations as Markdown: one section per group, one subsection per variable.

    Args: eq_df is the table from equations(); path is the .md file (a folder gets
    equations.md; default outputs/equations/equations.md); glossary None/False for none,
    True for a table of every indicator referenced (names from eq_df), or a dict code -> name
    or a catalogue DataFrame (code, name columns) to supply names; render_math adds a LaTeX
    rendering ($$ ... $$) above each equation that looks algebraic; title heads the file.
    Equations are shown as fenced code blocks. Returns the path written.
    """
    _check(eq_df)
    out = _out_path(path, "equations.md")
    lines = [f"# {_md_text(title)}", "", _stamp(eq_df), "", f"> {NOTICE}", ""]
    for grp, rows in _by_group(eq_df):
        lines += [f"## {_md_text(grp)}", ""]
        for r in rows:
            name = _text(r.get("name"))
            lines += [f"### {_md_text(r.get('indicator'))}" + (f": {_md_text(name)}" if name else ""), ""]
            note = _residual_note(r)
            if note:
                lines += [_md_text(note), ""]
            eq = _text(r.get("equation")).strip()
            if not eq:
                lines += ["_No equation returned (identity or exogenous series)._", ""]
                continue
            if render_math and looks_algebraic(eq):
                lines += ["$$", to_latex(eq), "$$", ""]
            lines += [_fence(eq), ""]
    if glossary is not None and glossary is not False:
        lines += ["## Mnemonic glossary", "", "| Mnemonic | Description |", "|---|---|"]
        lines += [f"| `{code}` | {_md_cell(name)} |" for code, name in _glossary(eq_df, glossary)]
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    log.info("equations: Markdown -> %s", out)
    return out


_TEX_SPECIAL = {"\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "$": r"\$", "&": r"\&", "%": r"\%",
                "#": r"\#", "_": r"\_", "^": r"\textasciicircum{}", "~": r"\textasciitilde{}"}


def _tex_text(s) -> str:
    return "".join(_TEX_SPECIAL.get(ch, ch) for ch in _text(s))


def export_latex(eq_df: pd.DataFrame, path=None, *, glossary=None, title: str = "Model equations") -> Path:
    """Write equations as a standalone LaTeX document (article class, amsmath, longtable).

    Args: eq_df is the table from equations(); path is the .tex file (a folder gets
    equations.tex; default outputs/equations/equations.tex); glossary as in export_markdown;
    title heads the document. Algebraic equations are typeset with to_latex in inline
    display style so long equations can break across lines; other text is set verbatim.
    Returns the path written.
    """
    _check(eq_df)
    out = _out_path(path, "equations.tex")
    lines = [r"\documentclass[11pt]{article}", r"\usepackage[T1]{fontenc}", r"\usepackage[margin=2cm]{geometry}",
             r"\usepackage{amsmath}", r"\usepackage{longtable}", r"\begin{document}",
             r"\section*{" + _tex_text(title) + "}", r"\noindent " + _tex_text(_stamp(eq_df)) + r"\\",
             r"\emph{" + _tex_text(NOTICE) + "}", ""]
    for grp, rows in _by_group(eq_df):
        lines += [r"\subsection*{" + _tex_text(grp) + "}", ""]
        for r in rows:
            name = _text(r.get("name"))
            head = _tex_text(r.get("indicator")) + (": " + _tex_text(name) if name else "")
            lines.append(r"\subsubsection*{" + head + "}")
            note = _residual_note(r)
            if note:
                lines.append(r"\noindent " + _tex_text(note) + ".")
            eq = _text(r.get("equation")).strip()
            if not eq:
                lines += [r"\noindent\textit{No equation returned (identity or exogenous series).}", ""]
            elif looks_algebraic(eq):
                lines += [r"\begin{flushleft}", "$\\displaystyle " + to_latex(eq) + "$", r"\end{flushleft}", ""]
            else:
                lines += [r"\begin{flushleft}\ttfamily", _tex_text(eq).replace("\n", r"\\" + "\n"),
                          r"\end{flushleft}", ""]
    if glossary is not None and glossary is not False:
        lines += [r"\section*{Mnemonic glossary}", r"\begin{longtable}{@{}lp{0.7\textwidth}@{}}",
                  r"\textbf{Mnemonic} & \textbf{Description}\\", r"\hline"]
        lines += [r"\texttt{" + _tex_text(code) + "} & " + _tex_text(name) + r"\\"
                  for code, name in _glossary(eq_df, glossary)]
        lines.append(r"\end{longtable}")
    lines += [r"\end{document}", ""]
    out.write_text("\n".join(lines), encoding="utf-8")
    log.info("equations: LaTeX -> %s", out)
    return out


def _excel_safe(df: pd.DataFrame) -> pd.DataFrame:
    """Copy safe for a spreadsheet: long text cut at Excel's cell limit, no text read as a formula."""
    def fix(v):
        if not isinstance(v, str):
            return v
        if len(v) > EXCEL_CELL_LIMIT:
            v = v[:EXCEL_CELL_LIMIT - 20] + " ...[truncated]"
        return " " + v if v.startswith("=") else v
    out = df.copy()
    for col in out.columns:
        if out[col].dtype == object:
            out[col] = out[col].map(fix)
    return out


def export_excel(eq_df: pd.DataFrame, path=None, *, dependencies=None, parameters=None) -> Path:
    """Write equations to a workbook: sheets Equations, Residual types, Dependencies, Parameters.

    Args: eq_df is the table from equations(); path is the .xlsx file (a folder gets
    equations.xlsx; default outputs/equations/equations.xlsx); dependencies and parameters
    are tables to include: None computes them from eq_df, False leaves the sheet out.
    Returns the path written.
    """
    from .report import to_excel

    _check(eq_df)
    out = _out_path(path, "equations.xlsx")
    tables = {"Equations": _excel_safe(eq_df), "Residual types": residual_summary(eq_df)}
    deps = _dependency_table(eq_df) if dependencies is None else dependencies
    pars = _parameter_table(eq_df) if parameters is None else parameters
    if deps is not False:
        tables["Dependencies"] = _excel_safe(deps)
    if pars is not False:
        tables["Parameters"] = _excel_safe(pars)
    to_excel(tables, out, decimals=None)
    log.info("equations: workbook -> %s", out)
    return out


def _jsonable(v):
    if v is None or isinstance(v, (str, bool)):
        return v
    if isinstance(v, float) and math.isnan(v):
        return None
    if hasattr(v, "item"):
        return v.item()
    return v


def export_json(eq_df: pd.DataFrame, path=None) -> Path:
    """Write equations as JSON: {"notice", "written", "equations": [one object per row]}.

    Args: eq_df is the table from equations(); path is the .json file (a folder gets
    equations.json; default outputs/equations/equations.json). The metadata JSON text is
    written back as an object. Returns the path written.
    """
    _check(eq_df)
    out = _out_path(path, "equations.json")
    records = []
    for row in eq_df.to_dict("records"):
        rec = {str(k): _jsonable(v) for k, v in row.items()}
        if "metadata" in rec:
            try:
                rec["metadata"] = json.loads(rec["metadata"]) if rec["metadata"] else {}
            except (TypeError, ValueError):
                pass
        records.append(rec)
    doc = {"notice": NOTICE, "written": datetime.now().isoformat(timespec="seconds"), "equations": records}
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    log.info("equations: JSON -> %s", out)
    return out


# ------------------------------------------------------------------------- DOT


def _dot_id(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _lag_label(lag: int) -> str:
    return "t" if lag == 0 else f"t{lag:+d}"


def to_dot(dep_df: pd.DataFrame, root=None, depth: int = 2, *, reverse: bool = False,
           include_residuals: bool = False) -> str:
    """Graphviz DOT text for the dependency graph (edges run from a referenced variable to
    the variable whose equation uses it; lags and leads label the edges).

    Args: dep_df is the table from dependencies(); root (a variable "AAA:ALPHA", or a code
    "AAA" for every group) limits the graph to what root depends on, `depth` steps upstream
    (reverse=True follows the other direction: the variables that use root); without root
    the whole table is drawn; include_residuals adds &X:G residual nodes (dashed).
    Returns the DOT text (render it with Graphviz, e.g. `dot -Tsvg deps.dot -o deps.svg`).
    Raises ValueError when root does not appear in the table.
    """
    _check(dep_df, DEPENDENCY_COLUMNS)
    edges: Dict[Tuple[str, str], set] = {}
    for ind, grp, rind, rgrp, lag, resid in dep_df[DEPENDENCY_COLUMNS].itertuples(index=False, name=None):
        if bool(resid) and not include_residuals:
            continue
        src = f"{'&' if resid else ''}{rind}:{rgrp}"
        edges.setdefault((src, f"{ind}:{grp}"), set()).add(int(lag))
    nodes = {n for e in edges for n in e} | {f"{i}:{g}" for i, g in zip(dep_df["indicator"], dep_df["group"])}
    roots: set = set()
    if root is not None:
        want = str(root).strip().lstrip("&").upper()
        roots = {n for n in nodes if not n.startswith("&")
                 and (n.upper() == want or (":" not in want and n.split(":", 1)[0].upper() == want))}
        if not roots:
            raise ValueError(f"{root!r} does not appear in the dependency table; check the code and group "
                             "(e.g. 'AAA:ALPHA') or fetch that variable's equations first.")
        keep, frontier = set(roots), set(roots)
        for _ in range(max(0, int(depth))):
            step = {(d if reverse else s) for s, d in edges if (s if reverse else d) in frontier}
            frontier = step - keep
            keep |= frontier
            if not frontier:
                break
        edges = {e: lags for e, lags in edges.items() if e[0] in keep and e[1] in keep}
        nodes = keep
    lines = ["digraph dependencies {", "  rankdir=LR;", '  node [shape=box, fontname="Helvetica"];']
    for node in sorted(nodes):
        style = []
        if node in roots:
            style.append("style=filled, fillcolor=lightgrey")
        elif node.startswith("&"):
            style.append("style=dashed")
        lines.append(f"  {_dot_id(node)}" + (f" [{', '.join(style)}]" if style else "") + ";")
    for (src, dst), lags in sorted(edges.items()):
        label = ", ".join(_lag_label(x) for x in sorted(lags, key=lambda x: (x != 0, -x)))
        attr = f' [label="{label}"]' if label != "t" else ""
        lines.append(f"  {_dot_id(src)} -> {_dot_id(dst)}{attr};")
    lines.append("}")
    return "\n".join(lines) + "\n"
