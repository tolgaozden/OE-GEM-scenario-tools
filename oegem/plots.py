"""Charts of scenario results: paths, deviations, small multiples and a PDF chart book.

Figures are drawn on matplotlib's Agg canvas without pyplot, so nothing opens a window
and the global backend is left alone. Save them with `save` (png, pdf or svg by
extension); in a notebook, display the returned Figure (or ``ax.figure``).

Style: the baseline is drawn first, dark grey and solid; scenarios take Okabe-Ito hues
in a fixed order (`PALETTE`) chosen so that neighbouring series stay distinct under
the common colour-vision deficiencies. A scenario keeps its colour on every page of a
chart book. Light horizontal gridlines, no top/right spines, a zero line on deviation
charts, a legend for two or more series and direct end labels when they do not collide.
Titles state the measure in words ("y/y %", "pp difference from baseline").
Quarterly series are lines; annual deviations are grouped bars. Given a history_end
mapping (e.g. from oegem.metadata.history_end), a chart draws a thin vertical line at the
last historical period and lightly shades the forecast period after it.
"""
from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence

import numpy as np
import pandas as pd
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import StrMethodFormatter

from . import transforms
from .data import as_long_frame
from .periods import normalize_period, parse_period, period_key, period_range

log = logging.getLogger("oegem")

# Okabe-Ito hues, ordered so adjacent pairs pass the CVD separation check; the orange is
# stepped slightly darker than the published value to sit inside the lightness band on white.
PALETTE = ("#0072B2", "#D55E00", "#009E73", "#56B4E9", "#CC79A7", "#D89400")
BASELINE_COLOR = "#3d3d3a"
INK, INK_2, MUTED = "#0b0b0b", "#52514e", "#6f6e69"
GRID, AXIS, ZERO, SURFACE = "#e1e0d9", "#c3c2b7", "#898781", "#ffffff"
_DASHES = ("-", (0, (5, 2)), (0, (1.5, 1.5)))
FORECAST_SHADE = "#f3f2ee"        # light wash behind the forecast period (after the history end)


# ------------------------------------------------------------------------ helpers
def _as_list(x) -> List[str]:
    if x is None:
        return []
    items = x.split(",") if isinstance(x, str) else list(x)
    return [str(i).strip() for i in items if str(i).strip()]


def forecast_styles(labels: Sequence[str], baseline: str = "baseline") -> Dict[str, dict]:
    """Line/bar style per forecast label: baseline dark grey, scenarios in PALETTE order.

    Args: labels in drawing order; baseline is the baseline's label. Past six scenarios
    the hues repeat with dashed and dotted lines (logged as a warning: consider fewer
    scenarios per chart). Returns {label: {color, linestyle, linewidth, zorder}}.
    """
    styles: Dict[str, dict] = {}
    k = 0
    for label in dict.fromkeys(labels):
        if label == baseline:
            styles[label] = {"color": BASELINE_COLOR, "linestyle": "-", "linewidth": 2.0, "zorder": 2}
            continue
        styles[label] = {"color": PALETTE[k % len(PALETTE)], "linestyle": _DASHES[(k // len(PALETTE)) % 3],
                         "linewidth": 1.8, "zorder": 3}
        k += 1
    if k > len(PALETTE):
        log.warning("%d scenarios on one chart: colours repeat with dashed lines; consider fewer per chart", k)
    return styles


def _figure(figsize) -> Figure:
    try:
        fig = Figure(figsize=figsize, layout="constrained")
    except TypeError:                                   # matplotlib < 3.5
        fig = Figure(figsize=figsize, constrained_layout=True)
    FigureCanvasAgg(fig)
    fig.set_facecolor(SURFACE)
    return fig


def _short(values) -> str:
    vals = [str(v) for v in values]
    return ", ".join(vals[:10]) + (", ..." if len(vals) > 10 else "")


def _is_dev(measure: str) -> bool:
    return any(s.startswith("dev_") for s in str(measure).split("|"))


def _select(df, indicator, group, measure=None) -> pd.DataFrame:
    data = as_long_frame(df)
    sub = data[(data["indicator"] == str(indicator)) & (data["group"] == str(group))]
    if sub.empty:
        raise ValueError(f"No rows for {indicator}:{group}; indicators present: {_short(pd.unique(data['indicator']))}; "
                         f"groups present: {_short(pd.unique(data['group']))}.")
    if measure is not None:
        sub = sub[sub["measure"] == measure]
        if sub.empty:
            raise ValueError(f"No rows with measure {measure!r} for {indicator}:{group}.")
    elif sub["measure"].nunique() > 1:
        raise ValueError(f"Several measures for {indicator}:{group} ({_short(pd.unique(sub['measure']))}); "
                         "pass measure=.")
    if sub["freq"].nunique() > 1:
        log.info("%s:%s has quarterly and annual rows; charting the quarterly ones", indicator, group)
        sub = sub[sub["freq"] == "Q"]
    return sub


def _order(present, forecasts, baseline) -> List[str]:
    present = list(dict.fromkeys(present))
    wanted = [f for f in _as_list(forecasts) if f in present] if forecasts is not None else present
    if baseline in wanted:
        wanted = [baseline] + [f for f in wanted if f != baseline]
    return wanted


def _x(p) -> float:
    year, quarter = parse_period(p)
    return year + (quarter - 1) / 4.0 if quarter else float(year)


def _xy(rows: pd.DataFrame):
    """x positions and values over the full period span, NaN in gaps so lines break."""
    keyed = rows.assign(_k=rows["period"].map(period_key)).sort_values("_k")
    periods = list(keyed["period"])
    full = period_range(periods[0], periods[-1])
    values = keyed.set_index("period")["value"].reindex(full).to_numpy(dtype=float)
    finite = np.flatnonzero(np.isfinite(values))
    if not len(finite):
        return np.array([]), np.array([])
    keep = slice(finite[0], finite[-1] + 1)             # trim leading/trailing gaps (e.g. no lag yet)
    return np.array([_x(p) for p in full])[keep], values[keep]


def _style_axes(ax, xs) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)
    ax.spines["bottom"].set_linewidth(0.8)
    ax.grid(True, axis="y", color=GRID, linewidth=0.6, linestyle="-")
    ax.grid(False, axis="x")
    ax.set_axisbelow(True)
    ax.tick_params(axis="y", length=0, labelsize=8, labelcolor=INK_2)
    ax.tick_params(axis="x", length=3, color=AXIS, labelsize=8, labelcolor=INK_2)
    ax.yaxis.set_major_formatter(StrMethodFormatter("{x:,g}"))
    x = np.asarray([v for v in xs if np.isfinite(v)], dtype=float)
    if len(x):
        first, last = int(math.floor(x.min())), int(math.floor(x.max()))
        span = last - first
        step = 1 if span <= 8 else 2 if span <= 16 else 5
        ticks = list(range(first, last + 1, step))
        ax.set_xticks(ticks)
        ax.set_xticklabels([str(t) for t in ticks])


def _title(ax, text: str, small: bool = False) -> None:
    ax.set_title(text, loc="left", fontsize=9 if small else 10, color=INK, fontweight="bold")


def _direct_labels(ax, ends) -> None:
    """Label line ends with the series name, unless more than four or any two collide."""
    ends = [(label, x, y) for label, x, y in ends if np.isfinite(y)]
    if not ends or len(ends) > 4:
        return
    lo, hi = ax.get_ylim()
    span = (hi - lo) or 1.0
    ys = sorted(y for _, _, y in ends)
    if any(b - a < 0.07 * span for a, b in zip(ys, ys[1:])):
        return                                          # converging ends: the legend carries identity
    for label, x, y in ends:
        ax.annotate(label, (x, y), xytext=(5, 0), textcoords="offset points", va="center", ha="left",
                    fontsize=8, color=INK_2, annotation_clip=False)


def _lines(ax, sub: pd.DataFrame, order: List[str], styles: Dict[str, dict], annual: bool) -> list:
    ends, xs = [], []
    for label in order:
        rows = sub[sub["forecast"] == label]
        if rows.empty:
            continue
        x, y = _xy(rows)
        if not len(x):
            continue
        style = styles.get(label) or forecast_styles([label])[label]
        extra = {"marker": "o", "markersize": 5, "markeredgecolor": SURFACE, "markeredgewidth": 1.0} if annual else {}
        ax.plot(x, y, label=label, solid_capstyle="round", solid_joinstyle="round", dash_capstyle="round",
                **style, **extra)
        finite = np.flatnonzero(np.isfinite(y))
        if len(finite):
            ends.append((label, x[finite[-1]], y[finite[-1]]))
        xs.extend(x)
    _style_axes(ax, xs)
    return ends


def _history_x(history_end, indicator, group, quarterly: bool) -> Optional[float]:
    """x position of a series' history end, or None.

    history_end is a period ("2026Q2"), or a mapping keyed by (indicator, group), "IND:GRP"
    or the group code. An annual history end on a quarterly chart sits at its fourth quarter.
    """
    if history_end is None or (isinstance(history_end, Mapping) and not history_end):
        return None
    if isinstance(history_end, Mapping):
        p = (history_end.get((str(indicator), str(group))) or history_end.get(f"{indicator}:{group}")
             or history_end.get(str(group)))
    else:
        p = history_end
    if p is None or (isinstance(p, float) and math.isnan(p)) or not str(p).strip():
        return None
    try:
        year, quarter = parse_period(normalize_period(p))
    except (TypeError, ValueError):
        return None
    if quarter:
        return year + (quarter - 1) / 4.0
    return year + 0.75 if quarterly else float(year)


def _mark_history(ax, x_end: Optional[float]) -> None:
    """Thin vertical line at the history end and a light shade over the forecast period."""
    if x_end is None:
        return
    lo, hi = ax.get_xlim()
    if x_end >= hi:
        return                                          # all history: nothing to mark
    ax.axvspan(max(x_end, lo), hi, facecolor=FORECAST_SHADE, edgecolor="none", linewidth=0, zorder=0)
    if x_end >= lo:
        ax.axvline(x_end, color=MUTED, linewidth=0.8, zorder=1.5)
    ax.set_xlim(lo, hi)


def _single_name(title: str, order: List[str]) -> str:
    return f"{title} ({order[0]})" if len(order) == 1 else title


# ------------------------------------------------------------------------- charts
def paths(df: pd.DataFrame, indicator: str, group: str, *, measure: Optional[str] = None, forecasts=None,
          ax=None, title: Optional[str] = None, baseline: str = "baseline", styles: Optional[dict] = None,
          legend: bool = True, direct_labels: bool = True, history_end=None):
    """Baseline and scenario paths of one indicator in one group.

    Args: df is a long frame; indicator and group pick the series; measure picks one
    measure when several are present; forecasts limits and orders the labels (baseline
    always drawn first); ax draws into an existing Axes (default: a new figure); title
    defaults to "<indicator> <group>: <measure in words>"; styles maps labels to styles
    (see forecast_styles) to keep colours fixed across charts; history_end (a period, or a
    mapping keyed by (indicator, group), "IND:GRP" or group, e.g. from
    oegem.metadata.history_end) draws a thin line at the last historical period and shades
    the forecast period.
    Returns the Axes (its figure is ``ax.figure``).
    """
    sub = _select(df, indicator, group, measure)
    order = _order(pd.unique(sub["forecast"]), forecasts, baseline)
    styles = styles or forecast_styles(order, baseline)
    standalone = ax is None
    if standalone:
        ax = _figure((6.4, 3.6)).add_subplot()
    ends = _lines(ax, sub, order, styles, annual=sub["freq"].iloc[0] == "A")
    _mark_history(ax, _history_x(history_end, indicator, group, quarterly=sub["freq"].iloc[0] == "Q"))
    words = transforms.measure_label(sub["measure"].iloc[0])
    _title(ax, title or _single_name(f"{indicator} {group}: {words}", order), small=not standalone)
    if legend and len(order) >= 2:
        ax.legend(frameon=False, fontsize=8, loc="best", handlelength=1.8)
    if direct_labels and len(order) >= 2:
        _direct_labels(ax, ends)
    return ax


def deviations(df: pd.DataFrame, indicator: str, group: str, *, ax=None, title: Optional[str] = None,
               measure: Optional[str] = None, baseline: str = "baseline", kind: str = "abs", forecasts=None,
               styles: Optional[dict] = None, legend: bool = True, direct_labels: bool = True,
               history_end=None):
    """Scenario deviations from the baseline: grouped bars for annual data, lines for quarterly.

    Args: df is a long frame holding either deviation rows (measure ending in a dev_ step)
    or values with a baseline, in which case deviations of kind "abs" or "pct" are
    computed first; the other arguments are as in `paths`. A zero line marks the baseline.
    Returns the Axes.
    """
    data = as_long_frame(df)
    sub = data[(data["indicator"] == str(indicator)) & (data["group"] == str(group))]
    if len(sub) and not sub["measure"].map(_is_dev).any():
        sub = transforms.deviation(sub, baseline=baseline, kind=kind)
    sub = _select(sub, indicator, group, measure)
    order = [f for f in _order(pd.unique(sub["forecast"]), forecasts, baseline) if f != baseline]
    styles = styles or forecast_styles([baseline] + order, baseline)
    standalone = ax is None
    if standalone:
        ax = _figure((6.4, 3.6)).add_subplot()
    if sub["freq"].iloc[0] == "A":
        finite = sub[np.isfinite(sub["value"].to_numpy(dtype=float))]
        years = sorted({int(p) for p in (finite if len(finite) else sub)["period"]})
        n = max(len(order), 1)
        width = min(0.8 / n, 0.28)
        for i, label in enumerate(order):
            rows = sub[sub["forecast"] == label].set_index("period")["value"]
            values = [rows.get(str(y), np.nan) for y in years]
            offset = (i - (n - 1) / 2.0) * width
            ax.bar(np.array(years, dtype=float) + offset, values, width=width * 0.86, label=label,
                   color=(styles.get(label) or {}).get("color", PALETTE[i % len(PALETTE)]), linewidth=0, zorder=3)
        _style_axes(ax, years)
        ends = []
    else:
        ends = _lines(ax, sub, order, styles, annual=False)
    _mark_history(ax, _history_x(history_end, indicator, group, quarterly=sub["freq"].iloc[0] == "Q"))
    ax.axhline(0.0, color=ZERO, linewidth=0.9, zorder=2.5)
    words = transforms.measure_label(sub["measure"].iloc[0])
    _title(ax, title or _single_name(f"{indicator} {group}: {words}", order), small=not standalone)
    if legend and len(order) >= 2:
        ax.legend(frameon=False, fontsize=8, loc="best", handlelength=1.8)
    if direct_labels and len(order) >= 2 and ends:
        _direct_labels(ax, ends)
    return ax


def _figure_legend(fig, labels: List[str], styles: Dict[str, dict], bars: bool) -> None:
    if len(labels) < 2:
        return
    handles = []
    for label in labels:
        st = styles.get(label) or {}
        if bars:
            handles.append(Patch(facecolor=st.get("color", BASELINE_COLOR), linewidth=0))
        else:
            handles.append(Line2D([0], [0], color=st.get("color", BASELINE_COLOR), linestyle=st.get("linestyle", "-"),
                                  linewidth=st.get("linewidth", 1.8)))
    kw = dict(frameon=False, fontsize=8, ncol=min(len(labels), 6), handlelength=1.8, columnspacing=1.4)
    try:                                                # below the panels: the title owns the top edge
        fig.legend(handles, labels, loc="outside lower center", **kw)
    except (ValueError, TypeError):                     # matplotlib < 3.7
        fig.legend(handles, labels, loc="lower center", **kw)


def small_multiples(df: pd.DataFrame, indicator: str, groups, *, kind: str = "paths", ncols: int = 3,
                    title: Optional[str] = None, measure: Optional[str] = None, forecasts=None,
                    baseline: str = "baseline", deviation: str = "abs", styles: Optional[dict] = None,
                    sharey: bool = False, history_end=None) -> Figure:
    """One panel per group for one indicator: paths or deviations, with one shared legend.

    Args: df is a long frame; groups lists the panels (codes or aggregate names); kind is
    "paths" or "deviations" (deviations of kind `deviation` are computed when df holds
    values); ncols is the panel columns; title heads the figure (default: indicator and
    measure in words); measure, forecasts, baseline and styles are as in `paths`; sharey
    puts every panel on one y scale; history_end marks the history end in each panel (see
    paths). Groups without data get an empty "no data" panel.
    Returns the Figure.
    """
    if kind not in ("paths", "deviations"):
        raise ValueError(f"kind must be 'paths' or 'deviations', got {kind!r}.")
    groups = _as_list(groups)
    if not groups:
        raise ValueError("Give at least one group for the panels.")
    data = as_long_frame(df)
    sub = data[data["indicator"] == str(indicator)]
    if kind == "deviations" and len(sub) and not sub["measure"].map(_is_dev).any():
        sub = transforms.deviation(sub, baseline=baseline, kind=deviation)
    if measure is not None:
        sub = sub[sub["measure"] == measure]
    order = _order(pd.unique(sub["forecast"]), forecasts, baseline)
    labels = [f for f in order if f != baseline] if kind == "deviations" else order
    styles = styles or forecast_styles([baseline] + [f for f in order if f != baseline], baseline)
    ncols = max(1, min(int(ncols), len(groups)))
    nrows = int(math.ceil(len(groups) / ncols))
    fig = _figure((3.3 * ncols + 0.3, 2.4 * nrows + 0.9))
    axes = fig.subplots(nrows, ncols, squeeze=False, sharey=sharey)
    draw = paths if kind == "paths" else deviations
    bars = False
    for i, group in enumerate(groups):
        ax = axes[i // ncols][i % ncols]
        try:
            draw(sub, indicator, group, measure=measure, forecasts=forecasts, ax=ax, title=group,
                 baseline=baseline, styles=styles, legend=False, direct_labels=False, history_end=history_end)
            bars = bars or bool(ax.containers)          # bar charts (the forecast shade is a patch too)
        except ValueError:
            _style_axes(ax, [])
            ax.set_yticks([])
            ax.text(0.5, 0.5, "no data", transform=ax.transAxes, ha="center", va="center", color=MUTED, fontsize=8)
            _title(ax, group, small=True)
    for j in range(len(groups), nrows * ncols):
        axes[j // ncols][j % ncols].set_visible(False)
    measures = list(pd.unique(sub["measure"]))
    words = transforms.measure_label(measures[0]) if len(measures) == 1 else ""
    head = title or (f"{indicator}: {words}" if words else str(indicator))
    fig.suptitle(_single_name(head, labels), x=0.01, ha="left", fontsize=11, color=INK, fontweight="bold")
    _figure_legend(fig, labels, styles, bars)
    return fig


def chart_book(df: pd.DataFrame, spec, path_pdf, *, meta=None, history_end=None) -> Path:
    """Multi-page PDF for a report config: per variable and frequency, values then deviations.

    Args: df is the long frame of levels (baseline + scenarios); spec is the report
    config (dict or YAML path, see oegem.report) and decides variables, chains, groups,
    aggregates and periods exactly as the report tables do; path_pdf is the output file;
    meta is the variable metadata table (for the `annual` step and the history end);
    history_end overrides the history ends read from meta.
    Returns the path. A config with nothing to chart yields a one-page PDF saying so.
    """
    from matplotlib.backends.backend_pdf import PdfPages

    from .report import load_report_config, plan_report, variable_frames

    if isinstance(spec, (str, Path)):
        spec, _ = load_report_config(spec)
    data = as_long_frame(df)
    plan = plan_report(data, spec, meta=meta)
    ends = history_end if history_end is not None else plan.history_end
    styles = forecast_styles(plan.forecasts, plan.baseline)
    path = Path(path_pdf)
    path.parent.mkdir(parents=True, exist_ok=True)
    pages = 0
    with PdfPages(path, metadata={"Title": plan.title}) as pdf:
        for var in plan.variables:
            for freq, word in (("Q", "quarterly"), ("A", "annual")):
                frames = variable_frames(data, plan, var, freq)
                if frames is None:
                    continue
                for kind, frame in (("paths", frames[0]), ("deviations", frames[1])):
                    if frame is None or frame.empty:
                        continue
                    present = set(frame["group"])
                    groups = [g for g in plan.row_groups if g in present]
                    measure = str(frame["measure"].iloc[0])
                    title = f"{var.label}, {word}: {transforms.measure_label(measure, rate=var.rate)}"
                    fig = small_multiples(frame, var.indicator, groups, kind=kind, title=title, measure=measure,
                                          forecasts=plan.forecasts, baseline=plan.baseline, styles=styles,
                                          history_end=ends or None)
                    pdf.savefig(fig)
                    pages += 1
        if not pages:
            fig = _figure((8.27, 2.5))
            fig.text(0.5, 0.5, "No data to chart for this report config.", ha="center", va="center", color=INK_2)
            pdf.savefig(fig)
    log.info("chart book: %d pages -> %s", max(pages, 1), path)
    return path


def save(fig, path, *, dpi: int = 150) -> Path:
    """Save a Figure (or the figure of an Axes) as png, pdf or svg by extension; returns the path."""
    fig = fig if isinstance(fig, Figure) else getattr(fig, "figure", None)
    if fig is None:
        raise ValueError("save() needs a matplotlib Figure or Axes.")
    path = Path(path)
    if path.suffix.lower() not in (".png", ".pdf", ".svg"):
        raise ValueError(f"Unsupported chart file type {path.suffix!r}: use .png, .pdf or .svg.")
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=dpi, facecolor=fig.get_facecolor())
    return path
