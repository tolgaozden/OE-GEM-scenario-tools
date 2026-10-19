"""Variable metadata: units, scaling, history end, annualisation type and base years.

The model-variables endpoint (``POST /v1/forecast-contents/<id>/model-variables`` with
``onlyProps=Metadata``) returns a ``Metadata`` dict for each INDICATOR:GROUP pair. Fields
seen include AnnualizationType, BaseYearIndex, BaseYearPrice, DerivedHistoryEnd,
Description, GroupName, HistoryEnd, IndicatorProperties (a dict), IsSeasonallyAdjusted,
OriginalSourceCode, OriginalSourceProvider, ScaleFactor, Scaling, Source, Unit and Units;
a release may send more or fewer, and every function here copes with missing fields.

* `metadata`: one row per pair, one column per field (API names kept; the
  IndicatorProperties dict is flattened into ``props_<key>`` columns).
* `history_end`: last historical period per pair (HistoryEnd, else DerivedHistoryEnd).
* `annualization` / `annualization_method`: "mean", "sum" or "last" per pair, used by
  the transform step ``annual``.
* `indicator_notes`: one line per indicator (unit, scaling, history end by group), used
  by report READMEs.
* `base_year_changes`: pairs whose BaseYearIndex or BaseYearPrice differ between two
  metadata tables (two releases): level comparisons across a base-year change are not
  meaningful, growth rates are unaffected.
* `save_metadata` / `load_metadata`: the run folder's ``metadata.csv``.

Personal data: a release's metadata can name the vendor's contact person for a series
(ContactName, ContactEmail) and carry internal record ids (InternalId). `metadata` drops
those fields, and any other field whose name starts with "Contact", unless
keep_contacts=True; output that keeps them must not be shared or committed. Metadata
describes licensed model content: treat exports like the data themselves.
"""
from __future__ import annotations

import json
import logging
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

import pandas as pd

from .data import _parse_pairs, _selection
from .equations import _forecast_id, fetch_model_variables, is_private_field
from .periods import freq_of, normalize_period, period_key

log = logging.getLogger("oegem")

METADATA_FILE = "metadata.csv"
DEFAULT_BATCH = 200
PROPS_FIELD = "IndicatorProperties"
PROPS_PREFIX = "props_"
PRIVATE_FIELDS = ("ContactName", "ContactEmail", "InternalId")
BASE_YEAR_FIELDS = ("BaseYearIndex", "BaseYearPrice")
BASE_YEAR_COLUMNS = ["indicator", "group", "field", "a", "b"]
ANNUAL_METHODS = ("mean", "sum", "last")
_ANNUAL_WORDS = {
    "average": "mean", "avg": "mean", "mean": "mean",
    "sum": "sum", "total": "sum",
    "end": "last", "endofperiod": "last", "endperiod": "last", "last": "last", "close": "last",
}

Pair = Tuple[str, str]


# ------------------------------------------------------------------- helpers
def _is_private(key) -> bool:
    """Contact fields (personal data of the vendor's staff) and internal record ids."""
    return is_private_field(key)


def _blank(v) -> bool:
    if v is None or v is pd.NA:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    return isinstance(v, str) and v.strip().lower() in ("", "nan", "none", "null")


def _text(v) -> str:
    """A cell as display text: "" when blank; 2015.0 and "2015.0" become "2015"."""
    if _blank(v):
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    s = str(v).strip()
    return s.split(".")[0] if re.fullmatch(r"-?\d+\.0+", s) else s


def _cell(value):
    """A metadata value as a table cell: scalars as they are, anything nested as JSON text."""
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def _as_dict(meta) -> Dict[str, Any]:
    if isinstance(meta, str) and meta.strip():
        try:
            meta = json.loads(meta)
        except ValueError:
            return {}
    return dict(meta) if isinstance(meta, Mapping) else {}


def _period(v) -> Optional[str]:
    text = _text(v)
    if not text:
        return None
    try:
        return normalize_period(text)
    except (TypeError, ValueError):
        return None


def _end_key(period: str) -> int:
    """period_key of the last quarter covered by a history end ("2025" covers 2025Q4)."""
    return period_key(period) + (3 if freq_of(period) == "A" else 0)


def _frame(meta) -> pd.DataFrame:
    if isinstance(meta, (str, Path)):
        return load_metadata(meta)
    if not isinstance(meta, pd.DataFrame) or not {"indicator", "group"} <= set(meta.columns):
        raise ValueError("Expected the metadata table from oegem.metadata.metadata() (columns indicator, group, "
                         "then the metadata fields), or the path of a metadata.csv.")
    return meta


# ------------------------------------------------------------------ fetching
def metadata(client, forecast_id, pairs=None, *, indicators=None, groups=None, batch: int = DEFAULT_BATCH,
             keep_contacts: bool = False) -> pd.DataFrame:
    """Metadata of INDICATOR:GROUP pairs as a table, one row per pair.

    Args: forecast_id is a forecast id (or the dict from resolve_release); pairs is a list
    of "IND:GRP" strings or (ind, grp) tuples, or None to use the cross product of
    indicators and groups (lists of codes, or "all" for the whole catalogue); batch is the
    number of selections per POST (at most 400); keep_contacts keeps ContactName,
    ContactEmail and InternalId, which are dropped by default because they are personal
    data of the vendor's staff and internal ids.
    Returns a DataFrame with columns indicator, group, then one column per metadata field
    (API names, sorted), then props_<key> per IndicatorProperties entry. Nested values are
    JSON text; a pair without metadata has empty cells. Raises ValueError when nothing is
    selected and OEError when the API fails.
    """
    fid = _forecast_id(forecast_id)
    if pairs is not None:
        items = [pairs] if isinstance(pairs, str) else list(pairs)
        sel = _parse_pairs([p.strip().lstrip("&") if isinstance(p, str) else p for p in items])
    else:
        sel = _selection(client, fid, indicators, groups, None)
    if not sel:
        raise ValueError("Give pairs=['GDP:US', ...] or indicators and groups (check codes with `oegem catalogue`).")
    records = fetch_model_variables(client, fid, sel, props=("Metadata",), batch=batch)
    rows: List[Dict[str, Any]] = []
    dropped = set()
    for rec in records:
        row: Dict[str, Any] = {"indicator": str(rec.get("IndicatorCode") or ""),
                               "group": str(rec.get("GroupCode") or "")}
        for key, value in _as_dict(rec.get("Metadata")).items():
            key = str(key)
            if not keep_contacts and _is_private(key):
                dropped.add(key)
                continue
            if key.lower() == PROPS_FIELD.lower():
                if isinstance(value, Mapping):
                    for k, v in value.items():
                        if not keep_contacts and _is_private(k):
                            dropped.add(f"{key}.{k}")
                            continue
                        row[PROPS_PREFIX + str(k)] = _cell(v)
                elif not _blank(value):
                    row[key] = _cell(value)
                continue
            row[key] = _cell(value)
        rows.append(row)
    fields = sorted({k for r in rows for k in r} - {"indicator", "group"},
                    key=lambda c: (c.startswith(PROPS_PREFIX), c.lower()))
    df = pd.DataFrame(rows, columns=["indicator", "group"] + fields, dtype=object)
    if dropped:
        log.info("metadata: left out %s (personal data / internal ids; keep_contacts=True keeps them)",
                 ", ".join(sorted(dropped)))
    log.info("metadata: %d pairs, %d fields", len(df), len(fields))
    return df


def save_metadata(df: pd.DataFrame, path) -> Path:
    """Write a metadata table as CSV (folders created); returns the path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _frame(df).to_csv(path, index=False)
    return path


def load_metadata(path) -> pd.DataFrame:
    """Read a metadata CSV written by save_metadata (all cells as text, blanks as None)."""
    path = Path(path)
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    if not {"indicator", "group"} <= set(df.columns):
        raise ValueError(f"{path} is not a metadata table (it needs indicator and group columns).")
    return df.astype(object).where(df.ne(""), None)


# ------------------------------------------------------------------- helpers
def history_end(meta_df) -> Dict[Pair, str]:
    """Last historical period per (indicator, group): HistoryEnd, else DerivedHistoryEnd.

    Args: meta_df is the table from metadata() or load_metadata() (or a metadata.csv path).
    Periods are normalised ("2026Q2", "2025"); pairs with neither field readable are left out.
    Returns {(indicator, group): period}.
    """
    df = _frame(meta_df)
    cols = [c for c in ("HistoryEnd", "DerivedHistoryEnd") if c in df.columns]
    out: Dict[Pair, str] = {}
    for row in df[["indicator", "group"] + cols].itertuples(index=False, name=None):
        for value in row[2:]:
            period = _period(value)
            if period:
                out[(str(row[0]), str(row[1]))] = period
                break
    return out


def annualization_method(value) -> str:
    """ "mean", "sum" or "last" for an AnnualizationType value (or one of those three words).

    Average/Avg/Mean -> mean; Sum/Total -> sum; End/EndOfPeriod/Last/Close -> last (case,
    spaces, hyphens and underscores ignored). Anything else, or nothing, -> mean.
    """
    if _blank(value):
        return "mean"
    key = re.sub(r"[^a-z]", "", str(value).lower())
    if key not in _ANNUAL_WORDS:
        log.debug("unknown annualisation type %r: using the mean", value)
    return _ANNUAL_WORDS.get(key, "mean")


def annualization(meta_df) -> Dict[Pair, str]:
    """Annualisation method per (indicator, group) from AnnualizationType.

    Args: meta_df is the table from metadata(). Every row gets an entry; a missing or
    unknown AnnualizationType gives "mean" (see annualization_method).
    Returns {(indicator, group): "mean" | "sum" | "last"}.
    """
    df = _frame(meta_df)
    values = df["AnnualizationType"] if "AnnualizationType" in df.columns else [None] * len(df)
    return {(str(i), str(g)): annualization_method(v) for i, g, v in zip(df["indicator"], df["group"], values)}


def _by_value(pairs: List[Tuple[str, str]], *, always_groups: bool = False, order=None) -> str:
    """'v' when every group shares one value, else 'v1 (G1, G2); v2 (G3)'."""
    groups_by: Dict[str, List[str]] = {}
    for grp, value in pairs:
        if value:
            groups_by.setdefault(value, []).append(grp)
    if not groups_by:
        return ""
    if len(groups_by) == 1 and not always_groups:
        return next(iter(groups_by))
    values = sorted(groups_by, key=order) if order else list(groups_by)
    return "; ".join(f"{v} ({', '.join(groups_by[v])})" for v in values)


def indicator_notes(meta_df, groups=None) -> Dict[str, str]:
    """One line per indicator for report READMEs: unit, scaling and the history end by group.

    Args: meta_df is the table from metadata(); groups limits the groups considered (None:
    all). Values that differ between groups are listed with their groups.
    Returns {indicator: "unit: Index | scaling: Units | history ends: 2025 (BETA); 2026Q2 (ALPHA, US)"}.
    """
    df = _frame(meta_df)
    if groups is not None:
        df = df[df["group"].astype(str).isin({str(g) for g in groups})]
    ends = history_end(df)
    out: Dict[str, str] = {}
    for ind, sub in df.groupby(df["indicator"].astype(str), sort=False):
        grps = [str(g) for g in sub["group"]]

        def column(name: str) -> List[Tuple[str, str]]:
            return list(zip(grps, (_text(v) for v in sub[name]))) if name in sub.columns else []

        unit = _by_value(column("Unit")) or _by_value(column("Units"))
        long_units = _by_value(column("Units"))
        scaling = _by_value(column("Scaling"))
        hist = _by_value([(g, ends.get((str(ind), g), "")) for g in grps], always_groups=True, order=_end_key)
        parts = []
        if unit:
            parts.append(f"unit: {unit}" + (f" ({long_units})" if long_units and long_units != unit else ""))
        if scaling:
            parts.append(f"scaling: {scaling}")
        if hist:
            parts.append(f"history ends: {hist}")
        out[str(ind)] = " | ".join(parts) or "no unit or history information"
    return out


def base_year_changes(meta_a, meta_b, fields=BASE_YEAR_FIELDS) -> pd.DataFrame:
    """Pairs whose base year differs between two metadata tables (e.g. two releases).

    Args: meta_a and meta_b are tables from metadata(); fields are the columns compared
    (default BaseYearIndex and BaseYearPrice). A pair counts only when both tables have a
    value and the values differ (2015, 2015.0 and "2015" are the same).
    Returns columns indicator, group, field, a, b (values as text), sorted.
    """
    a, b = _frame(meta_a), _frame(meta_b)
    rows = []
    for name in fields:
        if name not in a.columns or name not in b.columns:
            continue
        left = a[["indicator", "group", name]].astype({"indicator": str, "group": str})
        right = b[["indicator", "group", name]].astype({"indicator": str, "group": str})
        merged = left.merge(right, on=["indicator", "group"], suffixes=("_a", "_b"))
        for ind, grp, va, vb in merged.itertuples(index=False, name=None):
            ta, tb = _text(va), _text(vb)
            if ta and tb and ta != tb:
                rows.append((ind, grp, name, ta, tb))
    return pd.DataFrame(sorted(rows), columns=BASE_YEAR_COLUMNS)
