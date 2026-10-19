"""Compare two releases (or any two forecasts), and compare two scenarios command by command.

* `compare_releases` fetches the same variables from two forecasts, applies the same
  transform chain to both and adds "revision" rows (B minus A), all in one long frame.
  It also compares the variables' base years (metadata BaseYearIndex and BaseYearPrice):
  where they differ, a level comparison mixes two bases and is not meaningful, so a
  warning is logged and the frame's ``attrs["notes"]`` says which indicators are
  affected. Growth rates are unaffected by a change of base year.
* `diff_scenarios` lists, per target and verb, which commands two scenarios share and
  where their periods or values differ.
"""
from __future__ import annotations

import logging
from typing import Dict, Iterable, List, Sequence, Tuple

import pandas as pd

from .client import OEError
from .data import LONG_COLUMNS, empty_frame, fetch, sort_long
from .metadata import base_year_changes
from .metadata import metadata as fetch_metadata
from .periods import in_range, normalize_period
from .resources import resolve_release
from .scenario import Command, Scenario
from .transforms import apply as apply_transforms
from .transforms import parse_steps

log = logging.getLogger("oegem")

REVISION_LABEL = "revision"
DIFF_COLUMNS = ["target", "verb", "in_a", "in_b", "values_differ", "status", "a", "b"]
GROWTH_STEPS = ("yoy", "qoq", "qoq_ann")
_MATCH = ["indicator", "group", "period", "freq", "measure"]


def _release_label(res: dict, spec) -> str:
    path = str(res.get("Path") or "").rstrip("/")
    return str(res.get("Name") or (path.rsplit("/", 1)[-1] if path else "") or res.get("Id") or spec)


def _base_year_notes(client, ids: Tuple[str, str], indicators, groups, steps: Sequence[str]) -> List[str]:
    """One note per indicator and base-year field that differs between the two forecasts."""
    try:
        changes = base_year_changes(fetch_metadata(client, ids[0], indicators=indicators, groups=groups),
                                    fetch_metadata(client, ids[1], indicators=indicators, groups=groups))
    except (OEError, ValueError) as exc:
        log.info("compare: base-year check skipped (%s)", exc)
        return []
    growth = any(s in GROWTH_STEPS for s in steps)
    notes = []
    for (ind, name), sub in changes.groupby(["indicator", "field"], sort=True):
        values = "; ".join(f"{a} -> {b}" for a, b in sorted(set(zip(sub["a"], sub["b"]))))
        note = (f"{ind}: {name} differs between the releases ({values}; groups {', '.join(sub['group'])}). "
                "Level comparisons across a base-year change are not meaningful; growth rates are unaffected.")
        notes.append(note)
        log.warning("compare: %s%s", note, " This comparison uses growth rates." if growth else "")
    return notes


def compare_releases(client, spec_a, spec_b, indicators, groups, *, transforms=("level",), start=None, end=None,
                     annual_fallback: bool = True, check_base_year: bool = True) -> pd.DataFrame:
    """Values of two releases side by side, plus their difference.

    Args: spec_a and spec_b are release specs as accepted by resolve_release ("latest:5yr",
    a release name, a path or a forecast id); indicators and groups are lists of codes (or
    "all" for indicators); transforms is the chain applied to both before comparing (e.g.
    ("annual_avg", "yoy"); dev_* steps are not allowed, the revision is the deviation);
    start/end filter periods after the transforms, so growth rates at the start have their
    history; annual_fallback as in data.fetch; check_base_year fetches both releases'
    metadata and warns where BaseYearIndex or BaseYearPrice differ.
    Returns a long frame with forecast labels "A:<release name>", "B:<release name>" and
    "revision" (B - A, absolute, same measure; only where both have a value). Its
    ``attrs["notes"]`` lists the base-year changes found (empty when none).
    """
    steps = parse_steps(transforms)
    if any(s.startswith("dev_") for s in steps):
        raise ValueError("compare_releases computes the revision (B - A) itself: drop the dev_pct/dev_abs "
                         f"steps from transforms (got {steps}).")
    res_a, res_b = resolve_release(client, spec_a), resolve_release(client, spec_b)
    if res_a.get("Id") and res_a.get("Id") == res_b.get("Id"):
        log.warning("compare_releases: %r and %r are the same forecast; all revisions are zero", spec_a, spec_b)
    lo = normalize_period(start) if start is not None else None
    hi = normalize_period(end) if end is not None else None
    frames = []
    for res, spec, tag in ((res_a, spec_a, "A"), (res_b, spec_b, "B")):
        if not res.get("Id"):
            raise ValueError(f"Release {spec!r} resolved to a resource without an Id; pass a forecast, not a folder.")
        label = f"{tag}:{_release_label(res, spec)}"
        df = fetch(client, res["Id"], indicators, groups, label=label, annual_fallback=annual_fallback)
        if len(df):
            df = apply_transforms(df, steps)
        if len(df) and (lo or hi):
            df = df[[in_range(p, lo, hi) for p in df["period"]]]
        frames.append((label, df))
    notes = (_base_year_notes(client, (res_a["Id"], res_b["Id"]), indicators, groups, steps)
             if check_base_year and res_a["Id"] != res_b["Id"] else [])
    (label_a, a), (label_b, b) = frames
    merged = b.merge(a[_MATCH + ["value"]], on=_MATCH, how="inner", suffixes=("", "_a"))
    revision = merged.assign(forecast=REVISION_LABEL, value=merged["value"] - merged["value_a"])[LONG_COLUMNS]
    parts = [f for f in (a, b, revision) if len(f)]
    out = sort_long(pd.concat(parts, ignore_index=True)[LONG_COLUMNS]) if parts else empty_frame()
    out.attrs["notes"] = notes
    log.info("compare: %s vs %s, %d revision rows", label_a, label_b, len(revision))
    return out


def _commands(x) -> List[Command]:
    return list(getattr(x, "commands", x) or [])


def _grouped(cmds: Iterable[Command]) -> Dict[Tuple[str, str], List[Command]]:
    out: Dict[Tuple[str, str], List[Command]] = {}
    for c in cmds:
        out.setdefault((c.target.upper(), c.verb), []).append(c)
    return out


def _signature(cmds: List[Command]) -> List[tuple]:
    return sorted((c.start or "", c.end or "", tuple(round(v, 10) for v in c.values)) for c in cmds)


def diff_scenarios(a: Scenario, b: Scenario, *, changes_only: bool = False) -> pd.DataFrame:
    """Compare two scenarios command by command, grouped by target and verb.

    Args: a and b are Scenario objects (or lists of Command); changes_only drops rows that
    are the same in both.
    Returns columns target, verb, in_a, in_b, values_differ (both have the target/verb but
    with different periods or values), status ("same", "changed", "only in a", "only in b"),
    and a / b (the command lines, "; "-joined). Rows follow the order of a, then b.
    """
    ga, gb = _grouped(_commands(a)), _grouped(_commands(b))
    keys = list(ga) + [k for k in gb if k not in ga]
    rows = []
    for key in keys:
        ca, cb = ga.get(key, []), gb.get(key, [])
        differ = bool(ca and cb) and _signature(ca) != _signature(cb)
        if ca and cb:
            status = "changed" if differ else "same"
        else:
            status = "only in a" if ca else "only in b"
        rows.append(((ca or cb)[0].target, key[1], bool(ca), bool(cb), differ, status,
                     "; ".join(c.to_line() for c in ca), "; ".join(c.to_line() for c in cb)))
    out = pd.DataFrame(rows, columns=DIFF_COLUMNS)
    if changes_only:
        out = out[out["status"] != "same"].reset_index(drop=True)
    return out
