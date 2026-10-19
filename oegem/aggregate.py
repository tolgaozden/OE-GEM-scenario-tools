"""Weighted country groupings (aggregates) for long frames.

Aggregate rates, growth rates or deviations, never raw levels. Levels of different
economies are in different currencies and units, so a weighted mean of them means
nothing: transform first (for example ``transforms.apply(df, "annual_avg|yoy")`` or a
``dev_pct`` step), then aggregate. Weights are usually shares of a common-currency
series, such as nominal GDP in US dollars, which you fetch yourself and turn into
weights with `weights_from_values`.

A groupings file maps aggregate names to member groups and weights. YAML::

    ASIA_SAMPLE:            # aggregate name (must not clash with a group code)
      CHINA: 0.6
      INDIA: 0.4
    MAJOR: [US, EURO_11, JAPAN]   # a list means equal weights

or CSV with columns ``aggregate,group,weight`` (weight optional, default 1). Weights need
not sum to one. Check every group code in your own catalogue (`oegem catalogue search`).
"""
from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Dict, Iterable, Optional

import numpy as np
import pandas as pd
import yaml

from .data import LONG_COLUMNS, as_long_frame, empty_frame, sort_long
from .periods import normalize_period

log = logging.getLogger("oegem")

Groupings = Dict[str, Dict[str, float]]
_KEYS = ["forecast", "indicator", "period", "freq", "measure"]


def _weight(agg, grp, w) -> float:
    try:
        x = float(1.0 if w is None or (isinstance(w, str) and not w.strip()) else w)
    except (TypeError, ValueError):
        raise ValueError(f"Weight of {grp} in {agg} must be a number, got {w!r}.") from None
    if math.isnan(x) or x < 0:
        raise ValueError(f"Weight of {grp} in {agg} must be zero or positive, got {w!r}.")
    return x


def as_groupings(obj, base_dir=None) -> Groupings:
    """Normalise a groupings spec into {aggregate: {group: weight}}.

    Args: obj is a dict ({AGG: {GRP: weight}} or {AGG: [GRP, ...]} for equal weights; a
    single top-level key "aggregates" or "groupings" is unwrapped) or a path to a YAML,
    JSON or CSV file, resolved against base_dir when relative.
    Returns the normalised dict. Raises ValueError with a hint when malformed.
    """
    if isinstance(obj, (str, Path)):
        path = Path(obj)
        if base_dir is not None and not path.is_absolute():
            path = Path(base_dir) / path
        return load_groupings(path)
    if isinstance(obj, dict) and len(obj) == 1 and str(next(iter(obj))).lower() in ("aggregates", "groupings"):
        obj = next(iter(obj.values()))
    if not isinstance(obj, dict) or not obj:
        raise ValueError("Groupings must map aggregate names to members, e.g. "
                         "{'ASIA_SAMPLE': {'CHINA': 0.6, 'INDIA': 0.4}} or {'MAJOR': ['US', 'JAPAN']}.")
    out: Groupings = {}
    for agg, members in obj.items():
        if isinstance(members, str):
            members = [m for m in members.split(",")]
        if isinstance(members, (list, tuple)):
            members = {str(m).strip(): 1.0 for m in members if str(m).strip()}
        if not isinstance(members, dict) or not members:
            raise ValueError(f"Aggregate {agg!r} needs members: a mapping group -> weight or a list of groups.")
        weights = {str(g).strip(): _weight(agg, g, w) for g, w in members.items()}
        if sum(weights.values()) <= 0:
            raise ValueError(f"Aggregate {agg!r} has no positive weight.")
        out[str(agg).strip()] = weights
    return out


def load_groupings(path) -> Groupings:
    """Read groupings from YAML/JSON ({AGG: {GRP: weight}}) or CSV (aggregate,group,weight).

    Args: path to the file. Returns {aggregate: {group: weight}}.
    """
    path = Path(path)
    if not path.exists():
        raise ValueError(f"Groupings file not found: {path}")
    ext = path.suffix.lower()
    if ext in (".yaml", ".yml", ".json"):
        return as_groupings(yaml.safe_load(path.read_text(encoding="utf-8")))
    if ext == ".csv":
        table = pd.read_csv(path, dtype=str, keep_default_na=False)
        cols = {str(c).strip().lower(): c for c in table.columns}
        if "aggregate" not in cols or "group" not in cols:
            raise ValueError(f"{path.name}: a groupings CSV needs columns aggregate,group[,weight].")
        out: Dict[str, Dict[str, object]] = {}
        for _, row in table.iterrows():
            agg, grp = str(row[cols["aggregate"]]).strip(), str(row[cols["group"]]).strip()
            if agg and grp:
                out.setdefault(agg, {})[grp] = row[cols["weight"]] if "weight" in cols else 1.0
        return as_groupings(out)
    raise ValueError(f"Unsupported groupings file {path.name}: use .yaml/.yml, .json or .csv.")


def weighted_mean(df: pd.DataFrame, groupings, *, renormalise: bool = True) -> pd.DataFrame:
    """Weighted means of member groups, one set of rows per aggregate.

    Args: df is a long frame of rates, growth rates or deviations (not levels: see the
    module docstring); groupings is a dict or a groupings file path; renormalise=True
    divides by the weights of the members that have a value in that period (missing
    members drop out), False divides by all weights and gives NaN unless every member
    has a value.
    Returns a long frame whose group column holds the aggregate names; the input rows
    are not included (concatenate them yourself if you want both).
    """
    groupings = as_groupings(groupings)
    data = as_long_frame(df)
    frames = []
    present = set(data["group"])
    for agg, members in groupings.items():
        if agg in present:
            raise ValueError(f"Aggregate name {agg!r} is also a group in the data; rename the aggregate.")
        missing = [g for g in members if g not in present]
        if missing:
            log.warning("aggregate %s: no data for member(s) %s", agg, ", ".join(missing))
        sub = data[data["group"].isin(list(members))]
        if sub.empty:
            continue
        w = sub["group"].map(members).to_numpy(dtype=float)
        x = sub["value"].to_numpy(dtype=float)
        has = ~np.isnan(x)
        sub = sub.assign(_wx=np.where(has, w * np.where(has, x, 0.0), 0.0), _w=np.where(has, w, 0.0),
                         _n=has.astype(int))
        grouped = sub.groupby(_KEYS, sort=False)
        num, den, n = grouped["_wx"].sum(), grouped["_w"].sum(), grouped["_n"].sum()
        with np.errstate(divide="ignore", invalid="ignore"):
            if renormalise:
                value = num / den.where(den > 0)
            else:
                value = (num / sum(members.values())).where(n == len(members))
        res = value.rename("value").reset_index()
        res["group"] = agg
        frames.append(res[LONG_COLUMNS])
    if not frames:
        return empty_frame()
    return sort_long(pd.concat(frames, ignore_index=True))


def weights_from_values(df: pd.DataFrame, indicator: str, period, groups: Optional[Iterable[str]] = None,
                        *, forecast: Optional[str] = None) -> Dict[str, float]:
    """Weights proportional to one period of a series, e.g. nominal GDP in US dollars.

    Args: df is a long frame you fetched; indicator and period pick the values; groups
    limits (and orders) the members; forecast picks the forecast label when the frame has
    several (default "baseline" if present).
    Returns {group: share} with shares summing to one. Missing, NaN or negative values
    are left out with a warning.
    """
    data = as_long_frame(df)
    p = normalize_period(period)
    sub = data[(data["indicator"] == str(indicator)) & (data["period"] == p)]
    labels = list(pd.unique(sub["forecast"]))
    if forecast is None and len(labels) > 1:
        if "baseline" not in labels:
            raise ValueError(f"Several forecasts in the frame ({', '.join(labels)}); pass forecast=<label>.")
        forecast = "baseline"
    if forecast is not None:
        sub = sub[sub["forecast"] == forecast]
    if sub["measure"].nunique() > 1:
        sub = sub[sub["measure"] == "level"] if (sub["measure"] == "level").any() else sub.iloc[0:0]
        if sub.empty:
            raise ValueError("Several measures in the frame; filter one measure before computing weights.")
    values = sub.groupby("group", sort=False)["value"].first()
    wanted = list(groups) if groups is not None else list(values.index)
    out: Dict[str, float] = {}
    for g in wanted:
        v = values.get(g, np.nan)
        if pd.isna(v) or v < 0:
            log.warning("weights_from_values: no usable %s value for %s in %s; left out", indicator, g, p)
            continue
        out[g] = float(v)
    total = sum(out.values())
    if total <= 0:
        raise ValueError(f"No positive {indicator} values in {p} for the requested groups; check the codes and period.")
    return {g: v / total for g, v in out.items()}
