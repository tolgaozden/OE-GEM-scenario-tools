"""Transforms on the long frame: growth rates, annual aggregation, deviations from the
baseline and the combination of marginal scenario runs.

Every function takes a long frame (see `oegem.data`) and returns a new one; the input
is never modified. Lags use period arithmetic, not row shifts: the value four quarters
before 2026Q3 is looked up at 2025Q3, so a missing period gives NaN instead of a
growth rate computed against the wrong quarter.

The ``measure`` column records what was done, steps joined by "|" in the order they
were applied. "annual_avg|yoy|dev_abs" is the annual average, then its growth on the
previous year, then the scenario-minus-baseline difference of that growth rate.

Steps understood by `apply`:

=============  ===================================================================
level          no change
yoy            % change on the same period a year earlier (annual rows: previous year)
qoq            % change on the previous quarter (NaN on annual rows)
qoq_ann        q/q % change compounded to an annual rate (alias qoq_annualised)
diff, diffN    change on the previous period (diffN: on N periods earlier), own units
annual_avg     calendar-year mean of quarterly values (also annual_sum, annual_last)
annual         calendar year with each series' own method (mean, sum or end of year) from
               variable metadata passed as apply(..., meta=...); mean where unknown
               (alias annual_auto; see annual_auto)
dev_pct        % difference from the baseline
dev_abs        scenario minus baseline (percentage points on a rate or growth rate)
=============  ===================================================================
"""
from __future__ import annotations

import logging
import re
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Union

import numpy as np
import pandas as pd

from .data import LONG_COLUMNS, as_long_frame, empty_frame, sort_long
from .periods import period_key

log = logging.getLogger("oegem")

STEPS = ("level", "yoy", "qoq", "qoq_ann", "diff", "annual_avg", "annual_sum", "annual_last", "annual",
         "dev_pct", "dev_abs")
ANNUAL_HOW = {"mean": "annual_avg", "sum": "annual_sum", "last": "annual_last"}
GROWTH_STEPS = ("yoy", "qoq", "qoq_ann", "dev_pct")
_ALIASES = {"levels": "level", "qoq_annualised": "qoq_ann", "qoq_annualized": "qoq_ann",
            "annual_mean": "annual_avg", "annual_auto": "annual"}
_DIFF_RE = re.compile(r"^diff(\d+)$")
_SERIES = ["forecast", "indicator", "group", "freq", "measure"]   # identifies one series
_MATCH = ["indicator", "group", "period", "freq", "measure"]      # scenario <-> baseline match
_UNIQUE = ["forecast", "indicator", "group", "period", "measure"]

_WORDS = {
    "yoy": "y/y %",
    "qoq": "q/q %",
    "qoq_ann": "q/q % annualised",
    "annual_avg": "annual average",
    "annual_sum": "annual sum",
    "annual_last": "end-year value",
    "dev_pct": "% difference from baseline",
}


# ------------------------------------------------------------------------- helpers
def _prep(df) -> pd.DataFrame:
    """Copy of df as a clean long frame; rows must be unique per series and period."""
    if not isinstance(df, pd.DataFrame):
        raise ValueError(f"Expected a long frame (pandas DataFrame with columns {', '.join(LONG_COLUMNS)}).")
    out = as_long_frame(df)
    dup = out.duplicated(_UNIQUE)
    if dup.any():
        ex = out.loc[dup].iloc[0]
        raise ValueError(f"Rows are not unique: {ex['forecast']} {ex['indicator']}:{ex['group']} {ex['period']} "
                         f"(measure {ex['measure']}) appears more than once; drop duplicates or filter one "
                         "measure first.")
    return out


def _chain(measure: str, step: str) -> str:
    if step == "level":
        return measure
    return step if measure in ("", "level") else f"{measure}|{step}"


def _relabel(measures: pd.Series, step: str) -> pd.Series:
    mapping = {m: _chain(str(m), step) for m in pd.unique(measures)}
    return measures.map(mapping).astype(object)


def _keys(df: pd.DataFrame) -> np.ndarray:
    mapping = {p: period_key(p) for p in pd.unique(df["period"])}
    return df["period"].map(mapping).to_numpy(dtype=np.int64)


def _lagged(df: pd.DataFrame, units: np.ndarray) -> np.ndarray:
    """Value of each row's own series `units` period-key steps earlier (NaN where absent).

    period_key counts quarters (a year is 4 steps, also for annual periods), so a lag of
    one quarter is 1 step and a lag of one year is 4 steps for either frequency.
    """
    if df.empty:
        return np.array([], dtype=float)
    keys = _keys(df)
    left = df[_SERIES].assign(_k=keys - units)
    right = df[_SERIES].assign(_k=keys, _lag=df["value"].to_numpy(dtype=float))
    merged = left.merge(right, on=_SERIES + ["_k"], how="left")
    return merged["_lag"].to_numpy(dtype=float)


def _finite(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    values[~np.isfinite(values)] = np.nan
    return values


def _growth(df, units_q: int, units_a: Optional[int], step: str, power: float = 1.0) -> pd.DataFrame:
    out = _prep(df)
    is_q = (out["freq"] == "Q").to_numpy()
    units = np.where(is_q, units_q, units_a if units_a is not None else 0)
    lag = _lagged(out, units)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        val = (np.power(out["value"].to_numpy(dtype=float) / lag, power) - 1.0) * 100.0
    val = _finite(val)
    if units_a is None and (~is_q).any():
        log.debug("%s is undefined for annual rows; %d rows set to NaN", step, int((~is_q).sum()))
        val[~is_q] = np.nan
    out["value"] = val
    out["measure"] = _relabel(out["measure"], step)
    return sort_long(out)


# ------------------------------------------------------------------- growth rates
def yoy(df: pd.DataFrame) -> pd.DataFrame:
    """Percent change on the same period a year earlier.

    Args: df is a long frame. Quarterly rows compare with four quarters earlier, annual
    rows with the previous year. Returns a long frame with measure "...|yoy"; rows whose
    lagged value is missing (or zero) get NaN.
    """
    return _growth(df, 4, 4, "yoy")


def qoq(df: pd.DataFrame) -> pd.DataFrame:
    """Percent change on the previous quarter (not annualised).

    Args: df is a long frame. Returns measure "...|qoq". Annual rows have no previous
    quarter and come back as NaN.
    """
    return _growth(df, 1, None, "qoq")


def qoq_annualised(df: pd.DataFrame) -> pd.DataFrame:
    """Quarter-on-quarter percent change compounded to an annual rate: ((x/x[-1])^4 - 1) * 100.

    Args: df is a long frame. Returns measure "...|qoq_ann"; annual rows come back as NaN.
    """
    return _growth(df, 1, None, "qoq_ann", power=4.0)


def diff(df: pd.DataFrame, lag: Optional[int] = None) -> pd.DataFrame:
    """Change on an earlier period, in the series' own units (pp for a rate).

    Args: df is a long frame; lag is the number of periods of each row's own frequency
    (default 1: previous quarter for quarterly rows, previous year for annual rows; use
    lag=4 for the change over a year on quarterly data). Returns measure "...|diff"
    (or "...|diffN" for lag N > 1).
    """
    n = 1 if lag is None else int(lag)
    if n < 1:
        raise ValueError(f"lag must be a positive number of periods, got {lag!r}.")
    out = _prep(df)
    units = np.where((out["freq"] == "Q").to_numpy(), 1, 4) * n
    out["value"] = _finite(out["value"].to_numpy(dtype=float) - _lagged(out, units))
    out["measure"] = _relabel(out["measure"], "diff" if n == 1 else f"diff{n}")
    return sort_long(out)


# -------------------------------------------------------------- annual conversion
def annual(df: pd.DataFrame, how: str = "mean", min_obs: int = 4) -> pd.DataFrame:
    """Convert quarterly rows to calendar years.

    Args: df is a long frame; how is "mean" (measure annual_avg), "sum" (annual_sum) or
    "last" (annual_last: the latest quarter with a value); min_obs is the number of
    quarters with values a year needs (default 4: complete years only, otherwise NaN).
    Annual rows (annual-only economies) pass through with their values unchanged and the
    same measure label, so the result is one consistent measure.
    Returns a long frame with freq "A".
    """
    if how not in ANNUAL_HOW:
        raise ValueError(f"how must be one of {', '.join(ANNUAL_HOW)}; got {how!r}.")
    min_obs = int(min_obs)
    if not 1 <= min_obs <= 4:
        raise ValueError(f"min_obs must be between 1 and 4 quarters, got {min_obs}.")
    out = _prep(df)
    step = ANNUAL_HOW[how]
    frames = []
    q = out[out["freq"] == "Q"]
    if len(q):
        q = q.assign(_year=q["period"].str[:4], _k=_keys(q)).sort_values("_k")
        grouped = q.groupby(["forecast", "indicator", "group", "measure", "_year"], sort=False)["value"]
        if how == "mean":
            values = grouped.mean()
        elif how == "sum":
            values = grouped.sum(min_count=1)
        else:
            values = grouped.last()
        values = values.where(grouped.count() >= min_obs)
        res = values.reset_index().rename(columns={"_year": "period"})
        res["freq"] = "A"
        res["measure"] = _relabel(res["measure"], step)
        frames.append(res[LONG_COLUMNS])
    a = out[out["freq"] == "A"]
    if len(a):
        a = a.assign(measure=_relabel(a["measure"], step))
        frames.append(a[LONG_COLUMNS])
    if not frames:
        return empty_frame()
    res = pd.concat(frames, ignore_index=True)
    dup = res.duplicated(_UNIQUE, keep="first")
    if dup.any():
        log.debug("annual(): %d annual rows already present were superseded by quarterly conversions",
                  int(dup.sum()))
        res = res[~dup]
    return sort_long(res)


def annual_methods(meta) -> Dict[object, str]:
    """Annualisation method per series for the `annual` step.

    Args: meta is None, the table from oegem.metadata.metadata() (its AnnualizationType
    column), or a dict keyed by (indicator, group), "IND:GRP" or an indicator code, with
    values mean/sum/last or the metadata words (Average, Sum, Total, End, EndOfPeriod,
    Last, Close). Returns {(indicator, group) or indicator: "mean" | "sum" | "last"}.
    """
    from .metadata import annualization, annualization_method

    if meta is None:
        return {}
    if isinstance(meta, pd.DataFrame):
        return dict(annualization(meta))
    if not isinstance(meta, Mapping):
        raise ValueError("meta must be the table from oegem.metadata.metadata() or a dict such as "
                         "{('GDP', 'US'): 'sum'} or {'CPI': 'mean'}.")
    out: Dict[object, str] = {}
    for key, value in meta.items():
        if isinstance(key, tuple) and len(key) == 2:
            out[(str(key[0]).strip(), str(key[1]).strip())] = annualization_method(value)
        elif isinstance(key, str) and ":" in key:
            ind, grp = key.split(":", 1)
            out[(ind.strip(), grp.strip())] = annualization_method(value)
        else:
            out[str(key).strip()] = annualization_method(value)
    return out


def annual_auto(df: pd.DataFrame, meta=None, min_obs: int = 4) -> pd.DataFrame:
    """Convert quarterly rows to calendar years, each series with its own method.

    Args: df is a long frame; meta gives the method per series (see annual_methods;
    AnnualizationType Average -> mean, Sum/Total -> sum, End/EndOfPeriod/Last/Close ->
    last); series without one use the mean; min_obs is as in annual().
    Returns a long frame with freq "A". Each series is labelled with the step it got
    (annual_avg, annual_sum or annual_last), so the measure chain stays explicit; annual
    rows pass through as in annual().
    """
    out = _prep(df)
    methods = annual_methods(meta)
    if meta is None:
        log.info("annual step without metadata: every series uses the mean (pass meta=...)")
    if out.empty:
        return out
    keys = list(zip(out["indicator"], out["group"]))
    chosen = {k: methods.get(k) or methods.get(k[0]) or "mean" for k in set(keys)}
    how = np.array([chosen[k] for k in keys], dtype=object)
    unknown = sum(1 for k in chosen if k not in methods and k[0] not in methods)
    if meta is not None and unknown:
        log.info("annual: %d of %d series have no annualisation metadata; they use the mean", unknown, len(chosen))
    frames = [annual(out[how == m], how=m, min_obs=min_obs) for m in ANNUAL_HOW if (how == m).any()]
    frames = [f for f in frames if len(f)]
    return sort_long(pd.concat(frames, ignore_index=True)) if frames else empty_frame()


# --------------------------------------------------------------------- deviations
def deviation(df: pd.DataFrame, baseline: str = "baseline", kind: str = "pct") -> pd.DataFrame:
    """Scenario values relative to the baseline, matched on indicator, group, period and measure.

    Args: df is a long frame holding the baseline and one or more scenarios in the same
    measure; baseline is the baseline's forecast label; kind is "pct" ((s / b - 1) * 100)
    or "abs" (s - b; a percentage-point difference when the measure is a rate or growth
    rate). Use "abs" for rates and growth rates: a percent change of a rate is rarely
    what you want.
    Returns the scenario rows only (baseline rows dropped) with measure "...|dev_pct" or
    "...|dev_abs"; a missing (or, for pct, zero) baseline value gives NaN.
    """
    kind = str(kind).strip().lower()
    if kind not in ("pct", "abs"):
        raise ValueError(f"kind must be 'pct' or 'abs', got {kind!r}.")
    out = _prep(df)
    labels = list(pd.unique(out["forecast"]))
    if baseline not in labels:
        raise ValueError(f"Baseline {baseline!r} not found; forecasts present: {', '.join(labels) or 'none'}. "
                         "Pass baseline=<label>.")
    base = out.loc[out["forecast"] == baseline, _MATCH + ["value"]].rename(columns={"value": "_base"})
    merged = out[out["forecast"] != baseline].merge(base, on=_MATCH, how="left")
    s = merged["value"].to_numpy(dtype=float)
    b = merged["_base"].to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        val = (s / b - 1.0) * 100.0 if kind == "pct" else s - b
    merged["value"] = _finite(val)
    merged["measure"] = _relabel(merged["measure"], "dev_" + kind)
    if merged.empty:
        return empty_frame()
    return sort_long(merged[LONG_COLUMNS])


# ---------------------------------------------------------------------- the chain
def parse_steps(spec) -> List[str]:
    """Normalise a transform spec ("annual_avg|yoy", "yoy,dev_abs" or a list) into step names.

    Raises ValueError naming the valid steps when a step is unknown. None or an empty
    spec means ["level"].
    """
    if spec is None:
        return ["level"]
    parts: Iterable = re.split(r"[|,]", spec) if isinstance(spec, str) else list(spec)
    steps: List[str] = []
    for part in parts:
        step = str(part).strip().lower()
        if not step:
            continue
        step = _ALIASES.get(step, step)
        if step not in STEPS and not _DIFF_RE.match(step):
            raise ValueError(f"Unknown transform step {part!r}; use one of: {', '.join(STEPS)} "
                             "(diffN = change on N periods earlier, e.g. diff4).")
        steps.append(step)
    return steps or ["level"]


def apply(df: pd.DataFrame, spec, *, baseline: str = "baseline", min_obs: int = 4, meta=None) -> pd.DataFrame:
    """Apply a chain of steps, left to right.

    Args: df is a long frame; spec is "level", "yoy", "annual_avg|yoy" or a list such as
    ["annual_avg", "yoy", "dev_abs"] (steps listed in the module docstring); baseline is
    the label used by dev_* steps; min_obs is passed to the annual steps; meta gives the
    annualisation method per series for the `annual` step (see annual_auto; the other
    steps ignore it).
    Returns the transformed long frame; its measure column records the chain.
    """
    out = _prep(df)
    for step in parse_steps(spec):
        if step == "level":
            continue
        if step == "yoy":
            out = yoy(out)
        elif step == "qoq":
            out = qoq(out)
        elif step == "qoq_ann":
            out = qoq_annualised(out)
        elif step == "diff" or _DIFF_RE.match(step):
            out = diff(out, int(step[4:] or 1))
        elif step == "annual":
            out = annual_auto(out, meta, min_obs=min_obs)
        elif step.startswith("annual_"):
            how = {v: k for k, v in ANNUAL_HOW.items()}[step]
            out = annual(out, how=how, min_obs=min_obs)
        else:
            out = deviation(out, baseline=baseline, kind=step[4:])
    return out


def measure_label(measure, *, rate: bool = False) -> str:
    """The measure chain in words, for titles and table notes.

    Args: measure is a chain such as "annual_avg|yoy|dev_abs"; rate=True says the
    underlying series is itself a rate (an interest or unemployment rate), so absolute
    differences of its level are percentage points too.
    Returns e.g. "annual average, y/y %, pp difference from baseline".
    """
    steps = [s for s in str(measure or "level").split("|") if s and s != "level"]
    if not steps:
        return "level"
    words, pct_units = [], bool(rate)
    for step in steps:
        m = _DIFF_RE.match(step)
        if step == "dev_abs":
            words.append("pp difference from baseline" if pct_units else "difference from baseline")
        elif step == "diff" or m:
            span = "previous period" if step == "diff" else f"{m.group(1)} periods earlier"
            words.append(f"{'pp ' if pct_units else ''}change on {span}")
        else:
            words.append(_WORDS.get(step, step))
        if step in GROWTH_STEPS:
            pct_units = True
    return ", ".join(words)


# -------------------------------------------------------------- marginal combining
def combine_marginals(df: pd.DataFrame, base: str, parts: Union[str, Sequence[str]], name: str,
                      kind: str = "abs") -> pd.DataFrame:
    """Approximate a joint scenario by adding up separately solved marginal scenarios.

    Args: df is a long frame holding the base forecast and each part; base is the base
    label (usually "baseline"); parts are the labels of the marginal runs; name is the
    label of the combined forecast; kind "abs" adds the level differences,
    name = base + sum(part - base), and kind "pct" compounds the percentage differences,
    name = base * prod(part / base). Both ignore interactions between the shocks, so
    compare with a joint solve when that matters.
    Returns df plus the combined rows (one per base row; NaN where any part is missing).
    """
    kind = str(kind).strip().lower()
    if kind not in ("abs", "pct"):
        raise ValueError(f"kind must be 'abs' or 'pct', got {kind!r}.")
    parts = [parts] if isinstance(parts, str) else list(parts)
    if not parts:
        raise ValueError("Give at least one part (a scenario label) to combine.")
    out = _prep(df)
    labels = set(out["forecast"])
    missing = [x for x in [base] + parts if x not in labels]
    if missing:
        raise ValueError(f"Forecast label(s) not found: {', '.join(missing)}; present: {', '.join(sorted(labels))}.")
    if name in labels:
        raise ValueError(f"Label {name!r} is already used in the frame; choose a new name for the combination.")
    rows = out.loc[out["forecast"] == base].reset_index(drop=True)
    b = rows["value"].to_numpy(dtype=float)
    acc = np.zeros(len(rows)) if kind == "abs" else np.ones(len(rows))
    for part in parts:
        p = rows[_MATCH].merge(out.loc[out["forecast"] == part, _MATCH + ["value"]], on=_MATCH, how="left")
        pv = p["value"].to_numpy(dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            acc = acc + (pv - b) if kind == "abs" else acc * (pv / b)
    combined = rows.assign(forecast=name, value=_finite(b + acc if kind == "abs" else b * acc))
    return sort_long(pd.concat([out, combined[LONG_COLUMNS]], ignore_index=True))
