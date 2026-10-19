"""Fetch forecast values into the long frame; reshape, save and load it.

The long frame is the interchange format of the whole package: a DataFrame with
columns ``forecast, indicator, group, period, freq, value, measure`` (in that order),
rows sorted by forecast, indicator, group, period. Values from the API are levels
(measure "level"). Some economies are annual-only: a pair that returns no values at
the default frequency is requested again with ``"Frequency": "Annual"`` (the annual
fallback), and its rows get freq "A".
"""
from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Union
from urllib.parse import quote

import pandas as pd

from .catalogue import groups as _catalogue_groups
from .catalogue import indicators as _catalogue_indicators
from .client import as_records
from .periods import freq_of, in_range, normalize_period, parse_period

log = logging.getLogger("oegem")

LONG_COLUMNS = ["forecast", "indicator", "group", "period", "freq", "value", "measure"]
MAX_BATCH = 400
_SORT = ["forecast", "indicator", "group", "period", "measure"]
_TEXT = ["forecast", "indicator", "group", "period", "freq", "measure"]

Pair = Tuple[str, str]


def empty_frame() -> pd.DataFrame:
    """An empty long frame with the standard columns."""
    return pd.DataFrame({c: pd.Series(dtype=float if c == "value" else object) for c in LONG_COLUMNS})


def sort_long(df: pd.DataFrame) -> pd.DataFrame:
    """Sort a long frame by forecast, indicator, group, period (then measure); fresh index."""
    return df.sort_values(_SORT).reset_index(drop=True) if len(df) else df.reset_index(drop=True)


def as_long_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce a DataFrame to the long-frame contract.

    Needs columns forecast, indicator, group, period and value. Periods are normalised,
    freq is recomputed from them, measure defaults to "level", value becomes float, extra
    columns are dropped and rows are sorted.
    """
    missing = [c for c in ("forecast", "indicator", "group", "period", "value") if c not in df.columns]
    if missing:
        raise ValueError(f"Not a long frame: missing columns {missing}; expected {LONG_COLUMNS}.")
    out = df.copy()
    for col in ("forecast", "indicator", "group"):
        out[col] = out[col].astype(str)
    mapping = {p: normalize_period(p) for p in pd.unique(out["period"])}
    out["period"] = out["period"].map(mapping).astype(object)
    out["freq"] = out["period"].map(lambda p: "Q" if "Q" in p else "A").astype(object)
    out["value"] = pd.to_numeric(out["value"], errors="coerce").astype(float)
    if "measure" not in out.columns:
        out["measure"] = "level"
    out["measure"] = out["measure"].where(out["measure"].notna() & (out["measure"].astype(str) != ""), "level")
    out["measure"] = out["measure"].astype(str)
    return sort_long(out[LONG_COLUMNS])


def _codes(x) -> List[str]:
    if x is None:
        return []
    items = x.split(",") if isinstance(x, str) else list(x)
    out: List[str] = []
    for item in items:
        code = str(item).strip()
        if code and code not in out:
            out.append(code)
    return out


def _parse_pairs(pairs) -> List[Pair]:
    out: List[Pair] = []
    for p in ([pairs] if isinstance(pairs, str) else pairs):
        if isinstance(p, (tuple, list)) and len(p) == 2:
            ind, grp = str(p[0]).strip(), str(p[1]).strip()
        else:
            text = str(p).strip()
            if text.startswith("&") or text.count(":") != 1:
                raise ValueError(f"Bad pair {p!r}: write 'INDICATOR:GROUP', e.g. 'GDP:US' (residuals have no values).")
            ind, grp = (s.strip() for s in text.split(":"))
        if not ind or not grp:
            raise ValueError(f"Bad pair {p!r}: write 'INDICATOR:GROUP', e.g. 'GDP:US'.")
        if (ind, grp) not in out:
            out.append((ind, grp))
    return out


def _selection(client, forecast_id, indicators, groups, pairs) -> List[Pair]:
    if pairs is not None:
        return _parse_pairs(pairs)
    if isinstance(indicators, str) and indicators.strip().lower() == "all":
        indicators = list(_catalogue_indicators(client, forecast_id)["code"])
    if isinstance(groups, str) and groups.strip().lower() == "all":
        groups = list(_catalogue_groups(client, forecast_id)["code"])
    inds, grps = _codes(indicators), _codes(groups)
    if not inds or not grps:
        raise ValueError("Give indicators and groups (lists of codes, or 'all'), or pairs=['GDP:US', ...].")
    return [(i, g) for i in inds for g in grps]


def _frequency(freq) -> Optional[str]:
    if freq is None:
        return None
    f = str(freq).strip().lower()
    if f in ("a", "annual", "y", "year", "yearly"):
        return "Annual"
    if f in ("", "q", "quarterly", "default"):
        return None
    raise ValueError(f"freq must be None (API default), 'Q' or 'Annual'; got {freq!r}.")


def _batch(batch) -> int:
    n = int(batch)
    if n < 1:
        raise ValueError("batch must be at least 1.")
    if n > MAX_BATCH:
        log.debug("batch %d capped at the API limit of %d selections", n, MAX_BATCH)
    return min(n, MAX_BATCH)


def _post_values(client, forecast_id, pairs: List[Pair], frequency: Optional[str], batch: int) -> Dict[Pair, list]:
    """POST the variables endpoint in batches; returns {(ind, grp): [(raw period, value), ...]}."""
    url = f"/v1/forecast-contents/{quote(str(forecast_id), safe='')}/variables"
    got: Dict[Pair, list] = {}
    for start in range(0, len(pairs), batch):
        chunk = pairs[start:start + batch]
        body = [dict({"IndicatorCode": i, "GroupCode": g}, **({"Frequency": frequency} if frequency else {}))
                for i, g in chunk]
        items = as_records(client.post(url, json=body, params={"onlyProps": "Values"}))
        wanted = {(i.upper(), g.upper()): (i, g) for i, g in chunk}
        for j, item in enumerate(items):
            ind, grp = item.get("IndicatorCode"), item.get("GroupCode")
            if ind is None or grp is None:
                if j >= len(chunk):
                    continue
                ind, grp = chunk[j]
            key = wanted.get((str(ind).upper(), str(grp).upper()), (str(ind), str(grp)))
            points = []
            for v in item.get("Values") or []:
                if not isinstance(v, dict) or v.get("Value") is None:
                    continue
                try:
                    x = float(v["Value"])
                except (TypeError, ValueError):
                    continue
                if not math.isnan(x):
                    points.append((v.get("Period"), x))
            if points:
                got[key] = points
    return got


def fetch(client, forecast_id, indicators=None, groups=None, *, start=None, end=None, freq=None,
          annual_fallback: bool = True, batch: int = MAX_BATCH, label: str = "forecast",
          pairs=None) -> pd.DataFrame:
    """Fetch values (levels) of a forecast as a long frame.

    Args: indicators and groups are lists of codes (or comma-separated strings, or "all"
    for the whole catalogue); pairs is an optional list of "IND:GRP" strings used instead of
    the cross product. start/end filter periods (an annual period is kept when its year
    lies within quarterly bounds). freq None asks for the API default (quarterly where
    available), "Annual" asks for annual values everywhere. annual_fallback re-requests
    pairs that came back empty at annual frequency. batch is the number of selections per
    POST (at most 400). label fills the forecast column.
    Returns the long frame; pairs with no values at all are logged and left out.
    """
    sel = _selection(client, forecast_id, indicators, groups, pairs)
    size = _batch(batch)
    frequency = _frequency(freq)
    got = _post_values(client, forecast_id, sel, frequency, size)
    if annual_fallback and frequency is None:
        empty = [p for p in sel if p not in got]
        if empty:
            more = _post_values(client, forecast_id, empty, "Annual", size)
            got.update(more)
            log.info("annual fallback: %d of %d series had no values at the default frequency; "
                     "%d returned annual values", len(empty), len(sel), len(more))
    absent = [p for p in sel if p not in got]
    if absent:
        log.warning("%d of %d series returned no values (e.g. %s)", len(absent), len(sel),
                    ", ".join(f"{i}:{g}" for i, g in absent[:5]))
    lo = normalize_period(start) if start is not None else None
    hi = normalize_period(end) if end is not None else None
    rows, seen = [], {}
    for (ind, grp), points in got.items():
        for raw, x in points:
            if raw not in seen:
                try:
                    seen[raw] = normalize_period(raw)
                except ValueError:
                    log.debug("ignoring unreadable period %r", raw)
                    seen[raw] = None
            p = seen[raw]
            if p is not None and in_range(p, lo, hi):
                rows.append((label, ind, grp, p, freq_of(p), x, "level"))
    if not rows:
        return empty_frame()
    return sort_long(pd.DataFrame(rows, columns=LONG_COLUMNS))


def fetch_many(client, forecasts: Dict[str, str], indicators=None, groups=None, **kw) -> pd.DataFrame:
    """fetch() for several forecasts; forecasts maps label -> forecast id. Returns one long frame."""
    if not isinstance(forecasts, dict) or not forecasts:
        raise ValueError("forecasts must be a non-empty dict of label -> forecast id.")
    if "label" in kw:
        raise ValueError("fetch_many takes its labels from the forecasts dict keys; drop label=.")
    frames = [fetch(client, fid, indicators, groups, label=str(label), **kw) for label, fid in forecasts.items()]
    frames = [f for f in frames if len(f)]
    return sort_long(pd.concat(frames, ignore_index=True)) if frames else empty_frame()


def frequency_map(df: pd.DataFrame) -> pd.DataFrame:
    """Group x indicator table of the frequencies present ("Q", "A", or "A+Q" if both)."""
    if df.empty:
        return pd.DataFrame()
    freq = df.groupby(["group", "indicator"])["freq"].agg(lambda s: "+".join(sorted(set(s))))
    return freq.unstack("indicator")


def to_wide(df: pd.DataFrame, *, index: str = "period",
            columns: Union[str, Sequence[str]] = ("forecast", "indicator", "group")) -> pd.DataFrame:
    """Pivot a long frame to wide: one row per index value, one column per columns combination.

    Raises ValueError if index + columns do not identify rows uniquely (e.g. several
    measures: add "measure" to columns or filter first). A period index is sorted in time.
    """
    cols = [columns] if isinstance(columns, str) else list(columns)
    keys = [index] + cols
    if df.duplicated(keys).any():
        raise ValueError(f"Rows are not unique by {keys}; add 'measure' (or 'freq') to columns or filter first.")
    wide = df.set_index(keys)["value"].unstack(cols)
    if index == "period":
        wide = wide.loc[sorted(wide.index, key=parse_period)]
    return wide


def save(df: pd.DataFrame, path) -> Path:
    """Write a frame by extension: .csv, .parquet/.pq or .xlsx (sheet "data"). Returns the path."""
    path = Path(path)
    ext = path.suffix.lower()
    path.parent.mkdir(parents=True, exist_ok=True)
    if ext == ".csv":
        df.to_csv(path, index=False)
    elif ext in (".parquet", ".pq"):
        try:
            df.to_parquet(path, index=False)
        except ImportError as exc:
            raise ImportError("Parquet files need a parquet engine: pip install pyarrow") from exc
    elif ext == ".xlsx":
        df.to_excel(path, sheet_name="data", index=False)
    else:
        raise ValueError(f"Unsupported file type {ext!r}: use .csv, .parquet/.pq or .xlsx.")
    return path


def load(path) -> pd.DataFrame:
    """Read a long frame written by save() (.csv, .parquet/.pq or .xlsx sheet "data")."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".csv":
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
    elif ext in (".parquet", ".pq"):
        try:
            df = pd.read_parquet(path)
        except ImportError as exc:
            raise ImportError("Parquet files need a parquet engine: pip install pyarrow") from exc
    elif ext == ".xlsx":
        df = pd.read_excel(path, sheet_name="data", dtype=str, keep_default_na=False)
    else:
        raise ValueError(f"Unsupported file type {ext!r}: use .csv, .parquet/.pq or .xlsx.")
    if "value" in df.columns and df["value"].dtype == object:
        df["value"] = pd.to_numeric(df["value"], errors="coerce")  # "" (missing) -> NaN
    return as_long_frame(df)
