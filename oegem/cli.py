"""The ``oegem`` command line (also ``python -m oegem``).

Commands::

    auth status | auth token          check the API token, or fetch one (never printed unless asked)
    releases [resolve SPEC]           list model releases, or show which release a spec picks
    catalogue indicators|groups|shocks|search
    data                              values of a release as a long frame
    equations | params | deps         model introspection (licensed content: keep exports private)
    meta                              variable metadata: units, scaling, history end, base years
    profile                           economy profile per group, with a heuristic class
    scenario validate|build|show|diff
    run CONFIG                        solve the scenarios of a run config and fetch the results
    report CONFIG                     tables, workbook, markdown/html and charts from a report config
    plot                              small-multiple chart from a run folder or results file
    compare-releases A B              two releases side by side, plus the revision
    workspace ls|mkdir|mv|archive|rm  folders and forecasts in the workspace
    check-leaks                       scan files or git content for credentials and model content
    init DIR                          starter project with run, scenario, report and grouping configs

Global options: ``--demo`` (synthetic offline backend, same as OEGEM_DEMO=1), ``-v``/``-vv``
and ``--version``. Commands that use a release take ``--release SPEC`` (default: the
OEGEM_RELEASE variable, else ``latest:5yr``). Tables print to the terminal, or go to
``--out FILE`` in the format its extension names (.csv .xlsx .parquet .md .json).

Exit codes: 0 success; 1 the command ran but found problems (a solve failed, a scenario
file did not parse, leaks were found, the token is missing or expired, nothing matched);
2 usage, input or API errors.
"""
from __future__ import annotations

import argparse
import getpass
import logging
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional, Sequence

import pandas as pd

from . import __version__
from .catalogue import groups as catalogue_groups
from .catalogue import indicators as catalogue_indicators
from .catalogue import search as catalogue_search
from .catalogue import shock_variables
from .client import OEClient, OEError, redact
from .compare import compare_releases, diff_scenarios
from .config import load_config
from .data import fetch
from .data import save as save_long
from .equations import DEFAULT_DIR as EQUATIONS_DIR
from .equations import dependencies, export_excel, export_json, export_latex, export_markdown, parameters
from .equations import equations as fetch_equations
from .equations import group_profile, to_dot, used_by
from .metadata import metadata as fetch_metadata
from .report import build_report, load_report_config, load_results, to_markdown
from .report import table as period_table
from .resources import GEM_ROOT, archive, delete, ensure_folder_tree, list_releases, make_folder, move
from .resources import resolve_release, walk
from .runner import run as run_batch
from .scenario import Scenario, load_scenarios
from .solve import slug
from .transforms import apply as apply_transforms

log = logging.getLogger("oegem")

DEFAULT_RELEASE = "latest:5yr"
RELEASE_ENV = "OEGEM_RELEASE"
DEMO_ENV = "OEGEM_DEMO"
DEMO_NOTICE = "DEMO MODE: synthetic data (offline backend; numbers are NOT model output)"
LICENSED_NOTE = ("note: equations, coefficients and model data are licensed content: keep these exports out "
                 "of repositories and shared folders.")
TABLE_EXTS = (".csv", ".xlsx", ".parquet", ".pq", ".md", ".json")
CHART_EXTS = (".png", ".pdf", ".svg")
EQUATION_FORMATS = ("md", "tex", "xlsx", "json")
# (file in oegem/templates, name in the new project); package data cannot be a dotfile.
TEMPLATES = (("run.yaml", "run.yaml"), ("scenarios.yaml", "scenarios.yaml"), ("report.yaml", "report.yaml"),
             ("groupings.yaml", "groupings.yaml"), ("gitignore", ".gitignore"))
META_COLUMNS = ("indicator", "group", "Description", "Unit", "Scaling", "HistoryEnd", "AnnualizationType",
                "IsSeasonallyAdjusted", "BaseYearIndex", "BaseYearPrice")
CONTACTS_NOTE = ("note: --keep-contacts kept contact names, e-mail addresses and internal ids: personal data of "
                 "the vendor's staff. Do not share, publish or commit this output.")
MAX_ROWS = 60
MAX_COLS = 12
MAX_COLWIDTH = 70

EPILOG = """\
examples:
  oegem --demo releases                        try any command offline on synthetic data
  oegem auth status                            is OE_TOKEN set, valid and accepted?
  oegem catalogue search "oil price"           find mnemonics in the latest release
  oegem data --indicators GDP,CPI --groups US,CHINA --from 2024Q1 --out values.csv
  oegem init my_project                        starter run/report/scenario configs
  oegem run run.yaml && oegem report report.yaml

Mnemonics in these examples are illustrative: check them in your own catalogue.
environment: OE_TOKEN (API token), OEGEM_RELEASE (default --release), OEGEM_DEMO=1 (demo
mode), OE_TLS (auto|truststore|relaxed|default), OE_BASE_URL, OE_AUTH_* (auth token).
exit codes: 0 ok, 1 ran but found problems, 2 usage, input or API error."""


# --------------------------------------------------------------------------- helpers


class _Context:
    """Parsed arguments plus an API client that is only created when a command needs one."""

    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.demo = bool(getattr(args, "demo", False)) or _env_flag(DEMO_ENV)
        self._client: Optional[OEClient] = None

    def client(self) -> OEClient:
        """The demo client in demo mode, else a client with the OE_TOKEN token."""
        if self._client is None:
            self._client = OEClient.demo() if self.demo else OEClient()
        return self._client

    def release(self) -> dict:
        """Resource dict of --release (or OEGEM_RELEASE, or latest:5yr); notes the choice on stderr."""
        spec = getattr(self.args, "release", None) or os.environ.get(RELEASE_ENV, "").strip() or DEFAULT_RELEASE
        root = getattr(self.args, "root", None) or GEM_ROOT
        found = resolve_release(self.client(), spec, root=root)
        if not found.get("Id"):
            raise ValueError(f"Release {spec!r} has no forecast id; pick another with --release (see `oegem releases`).")
        where = f"  [{found['Path']}]" if found.get("Path") else ""
        _note(f"release: {found.get('Name') or spec}{where}")
        return found

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:  # closing is best effort
                pass


class _DropLibraryDemoBanner(logging.Filter):
    """The CLI prints its own demo notice, so the library's banner would repeat it."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not str(record.getMessage()).startswith("DEMO MODE")


def _configure_logging(verbosity: int) -> Callable[[], None]:
    """Send oegem log records to stderr for one CLI call; returns a function that undoes it."""
    logger = logging.getLogger("oegem")
    saved = (logger.level, logger.propagate)
    level = logging.WARNING if verbosity <= 0 else logging.INFO if verbosity == 1 else logging.DEBUG
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    handler.addFilter(_DropLibraryDemoBanner())
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False         # no second copy through handlers on the root logger

    def restore() -> None:
        logger.removeHandler(handler)
        logger.setLevel(saved[0])
        logger.propagate = saved[1]

    return restore


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _note(msg: str = "") -> None:
    """Status and hints go to stderr so stdout stays clean for tables and captured tokens."""
    print(msg, file=sys.stderr)


def _print(text: str = "") -> None:
    """print() that survives characters the console encoding cannot show."""
    try:
        print(text)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(str(text).encode(enc, errors="replace").decode(enc, errors="replace"))


def _one_line(exc: BaseException) -> str:
    return " ".join(redact(str(exc)).split())[:400] or type(exc).__name__


def _split(values) -> List[str]:
    """'A,B' (or a list of such strings) -> ['A', 'B'], blanks dropped."""
    if values is None:
        return []
    items = values if isinstance(values, (list, tuple)) else [values]
    out: List[str] = []
    for item in items:
        out.extend(part.strip() for part in str(item).split(",") if part.strip())
    return out


def _codes(text, flag: str = "--indicators"):
    """Codes from 'A,B', or the string 'all'."""
    if str(text).strip().lower() == "all":
        return "all"
    codes = _split(text)
    if not codes:
        raise ValueError(f"{flag} needs at least one code, e.g. {flag} GDP,CPI (or all).")
    return codes


def _optional_codes(text):
    return None if text is None or not str(text).strip() else _codes(text)


def _required(text, flag: str) -> List[str]:
    codes = _split(text)
    if not codes:
        raise ValueError(f"{flag} needs at least one code, e.g. {flag} US,CHINA.")
    return codes


def _steps(text) -> List[str]:
    """Transform chain from 'annual_avg,yoy' or 'annual_avg|yoy'; level when empty."""
    return _split(str(text).replace("|", ",")) if text else ["level"]


def _freq(text) -> Optional[str]:
    if text is None:
        return None
    t = str(text).strip().lower()
    if t in ("a", "annual", "y", "year", "yearly"):
        return "Annual"
    if t in ("", "q", "quarterly", "default"):
        return None
    raise ValueError(f"--freq {text}: use Annual, or leave it out for quarterly values where available.")


def _check_ext(path, allowed: Sequence[str], flag: str = "--out") -> Optional[Path]:
    """Fail early (before any API call) on an output file type the command cannot write."""
    if path is None:
        return None
    ext = Path(path).suffix.lower()
    if ext not in allowed:
        raise ValueError(f"{flag} {path}: unsupported file type {ext or '(none)'}; use {' '.join(allowed)}.")
    return Path(path)


def _frame_text(df: pd.DataFrame, *, max_rows: int = MAX_ROWS, max_cols: int = MAX_COLS) -> str:
    """A readable, truncated rendering of a table for the terminal."""
    if df is None or len(df) == 0:
        return "(no rows)"
    show_index = not isinstance(df.index, pd.RangeIndex)
    shown = df.copy()
    for i in range(shown.shape[1]):  # blank out None in text columns; na_rep covers numeric NaN
        if shown.iloc[:, i].dtype == object:
            shown.iloc[:, i] = shown.iloc[:, i].where(shown.iloc[:, i].notna(), "")
    text = shown.to_string(index=show_index, max_rows=max_rows, max_cols=max_cols,
                           max_colwidth=MAX_COLWIDTH, na_rep="")
    if len(df) > max_rows or df.shape[1] > max_cols:
        text += (f"\n[{len(df)} rows x {df.shape[1]} columns, shown truncated; "
                 "--out FILE writes everything]")
    return text


def _wide(df: pd.DataFrame) -> pd.DataFrame:
    """Long frame -> one row per series, one column per period (the terminal and .md view)."""
    return period_table(df, decimals=2)


def _write_table(df: pd.DataFrame, path, *, sheet: str = "data", long: bool = False) -> Path:
    """Write a table in the format named by the file extension.

    Long frames keep the long layout in .csv/.xlsx/.parquet (so oegem.data.load reads
    them back) and become a period table in .md.
    """
    path = Path(path)
    ext = path.suffix.lower()
    if ext not in TABLE_EXTS:
        raise ValueError(f"--out {path}: unsupported file type {ext or '(none)'}; use {' '.join(TABLE_EXTS)}.")
    path.parent.mkdir(parents=True, exist_ok=True)
    if long and ext in (".csv", ".xlsx", ".parquet", ".pq"):
        return save_long(df, path)
    keep_index = not isinstance(df.index, pd.RangeIndex)
    flat = df.reset_index() if keep_index else df
    if ext == ".csv":
        df.to_csv(path, index=keep_index)
    elif ext == ".xlsx":
        df.to_excel(path, sheet_name=str(sheet)[:31] or "data", index=keep_index)
    elif ext in (".parquet", ".pq"):
        try:
            flat.to_parquet(path, index=False)
        except ImportError:
            raise ValueError("Parquet files need a parquet engine (pip install pyarrow); "
                             "or write .csv or .xlsx instead.") from None
    elif ext == ".md":
        to_markdown(_wide(df) if long else df, path)
    else:
        path.write_text(flat.to_json(orient="records", indent=2, force_ascii=False) + "\n", encoding="utf-8")
    return path


def _emit(df: pd.DataFrame, out=None, *, sheet: str = "data", long: bool = False,
          columns: Optional[Sequence[str]] = None) -> None:
    """Write df to --out, or print it (a period table for long frames, else the chosen columns)."""
    if out:
        path = _write_table(df, out, sheet=sheet, long=long)
        _print(f"wrote {path} ({len(df)} rows)")
        return
    if long and len(df):
        view = _wide(df)
    else:
        view = df[[c for c in columns if c in df.columns]] if columns else df
    _print(_frame_text(view))


def _commands(n: int) -> str:
    return f"{n} command" if n == 1 else f"{n} commands"


def _duration(minutes: float) -> str:
    total = int(round(abs(minutes)))
    hours, mins = divmod(total, 60)
    return f"{hours} h {mins} min" if hours else f"{mins} min"


def _expiry(claims) -> Optional[datetime]:
    """UTC expiry from the JWT "exp" claim, or None."""
    exp = claims.get("exp") if isinstance(claims, dict) else None
    try:
        return datetime.fromtimestamp(float(exp), tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _expiry_line(claims) -> str:
    when = _expiry(claims)
    if when is None:
        return "unknown (the token is not a JWT with an exp claim; it may still work)"
    minutes = (when - datetime.now(timezone.utc)).total_seconds() / 60.0
    stamp = when.strftime("%Y-%m-%d %H:%M UTC")
    return f"{stamp} (EXPIRED {_duration(minutes)} ago)" if minutes <= 0 else f"{stamp} (in {_duration(minutes)})"


def _template(name: str) -> str:
    """Text of a starter-project template shipped in oegem/templates."""
    try:
        from importlib.resources import files
        return files("oegem").joinpath("templates").joinpath(name).read_text(encoding="utf-8")
    except (ImportError, AttributeError, FileNotFoundError, NotADirectoryError):
        return (Path(__file__).resolve().parent / "templates" / name).read_text(encoding="utf-8")


def _pick_scenario(spec: str) -> Scenario:
    """FILE (holding one scenario) or FILE::NAME -> that Scenario."""
    path, name = spec.rsplit("::", 1) if "::" in spec else (spec, None)
    scenarios = load_scenarios(path)
    names = [s.name for s in scenarios]
    if name:
        for s in scenarios:
            if s.name == name:
                return s
        raise ValueError(f"{path} has no scenario {name!r}; it holds: {', '.join(names)}.")
    if len(scenarios) == 1:
        return scenarios[0]
    raise ValueError(f"{path} holds {len(scenarios)} scenarios ({', '.join(names)}); pick one as {path}::NAME.")


# --------------------------------------------------------------------------- commands


def cmd_auth(ctx: _Context) -> int:
    """auth status | auth token."""
    if ctx.args.auth_command == "status":
        return _auth_status(ctx)
    return _auth_token(ctx)


def _auth_status(ctx: _Context) -> int:
    from .auth import clean_token, decode_jwt_claims, missing_token_message

    if ctx.demo:
        client = ctx.client()
        claims = client.token_claims
        source = "demo token built at runtime; not a credential"
    else:
        token = clean_token(os.environ.get("OE_TOKEN"))
        if not token:
            _print("token:    not set (the OE_TOKEN environment variable is empty)")
            _note(missing_token_message())
            return 1
        claims = decode_jwt_claims(token)
        source = "OE_TOKEN environment variable"
        client = None
    _print(f"token:    present ({source})")
    _print(f"expires:  {_expiry_line(claims)}")
    when = _expiry(claims)
    expired = when is not None and when <= datetime.now(timezone.utc)
    try:
        client = client or ctx.client()
        client.whoami()
        _print(f"/me:      reachable at {client.base_url} (TLS mode: {client.tls})")
        reachable = True
    except OEError as exc:
        _print(f"/me:      NOT reachable: {_one_line(exc)}")
        reachable = False
    if expired:
        _note("hint: the token has expired: set a fresh OE_TOKEN (tokens last about 24 hours); "
              "`oegem auth token` can fetch one.")
    return 0 if reachable and not expired else 1


def _auth_token(ctx: _Context) -> int:
    from .auth import decode_jwt_claims, fetch_token_password_grant

    a = ctx.args
    if ctx.demo:
        from .demo import make_demo_token

        token = make_demo_token()
        _note("demo mode: no request sent; this is a dummy token for the synthetic backend")
    else:
        password = getpass.getpass(f"Password for {a.username}: ")
        if not password:
            raise ValueError("No password entered.")
        token = fetch_token_password_grant(a.username, password)
    if a.print_token:
        print(token)                 # stdout carries the token alone, for capture into OE_TOKEN
        return 0
    _print(f"Token fetched; expires {_expiry_line(decode_jwt_claims(token))}. It was not printed.")
    _print("To put a fresh token in OE_TOKEN for this session, capture the output of --print:")
    _print(f"  PowerShell:  $env:OE_TOKEN = (oegem auth token --username {a.username} --print)")
    _print(f'  bash/zsh:    export OE_TOKEN="$(oegem auth token --username {a.username} --print)"')
    _print('  MATLAB:      setenv("OE_TOKEN", "<token>")')
    return 0


def cmd_releases(ctx: _Context) -> int:
    """releases [--root R] [--depth N] [--horizon H] [--out FILE] ; releases resolve SPEC."""
    a = ctx.args
    root = a.root or GEM_ROOT
    if getattr(a, "releases_command", None) == "resolve":
        found = resolve_release(ctx.client(), a.spec, root=root)
        for key in ("Name", "Path", "Id"):
            _print(f"{key.lower() + ':':6} {found.get(key) or ''}")
        return 0
    _check_ext(a.out, TABLE_EXTS)
    df = list_releases(ctx.client(), root=root, max_depth=a.depth)
    if a.horizon:
        df = df[df["horizon"].astype(str).str.lower() == a.horizon.strip().lower()].reset_index(drop=True)
    if df.empty:
        _note(f"no releases found under {root} (try a larger --depth or another --root)")
        return 1
    if a.out:
        _emit(df, a.out, sheet="releases")
    else:                            # paths relative to the root keep the distinguishing tail visible
        prefix = "/" + root.strip("/") + "/"
        view = df.assign(path=[p[len(prefix):] if str(p).startswith(prefix) else p for p in df["path"]])
        _emit(view, columns=["name", "horizon", "vintage", "is_previous", "path"])
        _note(f"paths relative to {root}")
    return 0


def cmd_catalogue(ctx: _Context) -> int:
    """catalogue indicators|groups|shocks [PATTERN] ; catalogue search PATTERN."""
    a = ctx.args
    _check_ext(a.out, TABLE_EXTS)
    pattern = a.search or a.pattern
    if a.kind == "search" and not pattern:
        raise ValueError('catalogue search needs a PATTERN, e.g. oegem catalogue search "oil price".')
    client, rel = ctx.client(), ctx.release()
    fid = rel["Id"]
    if a.kind == "search":
        kinds = ("indicators", "groups") if a.within == "both" else (a.within,)
        found = []
        for kind in kinds:
            df = catalogue_indicators(client, fid) if kind == "indicators" else catalogue_groups(client, fid)
            found.append((kind, catalogue_search(df, pattern, regex=not a.plain)))
        if a.out:
            frames = [hits.assign(kind=kind[:-1]) for kind, hits in found]
            combined = pd.concat(frames, ignore_index=True, sort=False)
            combined = combined[["kind"] + [c for c in combined.columns if c != "kind"]]
            _emit(combined, a.out, sheet="search")
        else:
            for i, (kind, hits) in enumerate(found):
                if i:
                    _print()
                _print(f"{kind}: {len(hits)} match(es) for {pattern!r}")
                if len(hits):
                    _print(_frame_text(hits))
        return 0
    df = catalogue_groups(client, fid) if a.kind == "groups" else catalogue_indicators(client, fid)
    if a.kind == "shocks":
        df = shock_variables(df)
    if pattern:
        df = catalogue_search(df, pattern, regex=not a.plain)
    _emit(df, a.out, sheet=a.kind)
    _note(f"{len(df)} {a.kind}")
    return 0


def cmd_data(ctx: _Context) -> int:
    """data --indicators A,B|all --groups X,Y [--from P] [--to P] [--freq Annual] [--out FILE]."""
    a = ctx.args
    _check_ext(a.out, TABLE_EXTS)
    indicators, groups, freq = _codes(a.indicators), _codes(a.groups, "--groups"), _freq(a.freq)
    client, rel = ctx.client(), ctx.release()
    df = fetch(client, rel["Id"], indicators, groups, start=a.start, end=a.end, freq=freq,
               annual_fallback=not a.no_annual_fallback, label=a.label or str(rel.get("Name") or "forecast"))
    if df.empty:
        _note("no values returned: check the codes (`oegem catalogue search`) and the period range.")
        return 1
    _emit(df, a.out, sheet="data", long=True)
    _note(f"{len(df)} values in {df.groupby(['indicator', 'group']).ngroups} series")
    return 0


def _equation_table(ctx: _Context, *, only_with_equations: bool = False):
    a = ctx.args
    groups = _required(a.groups, "--groups")
    client, rel = ctx.client(), ctx.release()
    eq_df = fetch_equations(client, rel["Id"], groups=groups, indicators=_optional_codes(a.indicators),
                            only_with_equations=only_with_equations)
    return client, rel, groups, eq_df


def cmd_equations(ctx: _Context) -> int:
    """equations --groups G[,G2] [--indicators ...] [--format md,tex,xlsx,json] [--out-dir D]."""
    a = ctx.args
    formats = [f.lower().lstrip(".") for f in _split(a.format)] or ["md"]
    formats = ["md" if f in ("markdown",) else "tex" if f in ("latex",) else f for f in formats]
    bad = [f for f in formats if f not in EQUATION_FORMATS]
    if bad:
        raise ValueError(f"--format {','.join(bad)}: use one or more of {', '.join(EQUATION_FORMATS)}.")
    client, rel, groups, eq_df = _equation_table(ctx, only_with_equations=a.only_with_equations)
    out_dir = Path(a.out_dir) if a.out_dir else EQUATIONS_DIR
    stem = slug(a.name) or "equations"
    glossary = catalogue_indicators(client, rel["Id"]) if a.glossary else None
    files = []
    for fmt in dict.fromkeys(formats):
        target = out_dir / f"{stem}.{fmt}"
        if fmt == "md":
            files.append(export_markdown(eq_df, target, glossary=glossary, render_math=a.math))
        elif fmt == "tex":
            files.append(export_latex(eq_df, target, glossary=glossary))
        elif fmt == "xlsx":
            files.append(export_excel(eq_df, target))
        else:
            files.append(export_json(eq_df, target))
    with_eq = int((eq_df["equation"].astype(str).str.strip() != "").sum()) if len(eq_df) else 0
    _print(f"{len(eq_df)} variables ({with_eq} with an equation) in {', '.join(groups)}")
    for path in files:
        _print(f"wrote {path}")
    _note(LICENSED_NOTE)
    return 0


def cmd_params(ctx: _Context) -> int:
    """params --groups G [--indicators ...] [--out FILE]."""
    _check_ext(ctx.args.out, TABLE_EXTS)
    _, _, _, eq_df = _equation_table(ctx)
    _emit(parameters(eq_df), ctx.args.out, sheet="parameters")
    _note(LICENSED_NOTE)
    return 0


def cmd_deps(ctx: _Context) -> int:
    """deps --groups G --indicator X [--reverse] [--dot FILE] [--depth N] [--out FILE]."""
    a = ctx.args
    _check_ext(a.out, TABLE_EXTS)
    target = a.indicator.strip().lstrip("&")
    code, group = target.split(":", 1) if ":" in target else (target, None)
    _, _, _, eq_df = _equation_table(ctx)
    dep = dependencies(eq_df)
    if a.reverse:
        table = used_by(dep, code, group)
        what = f"equation(s) that use {target}"
    else:
        mask = dep["indicator"].astype(str).str.upper() == code.upper()
        if group:
            mask &= dep["group"].astype(str).str.upper() == group.upper()
        table = dep[mask].reset_index(drop=True)
        what = f"reference(s) in the equation of {target}"
    _emit(table, a.out, sheet="dependencies")
    _note(f"{len(table)} {what}")
    if a.dot:
        text = to_dot(dep, root=target, depth=a.depth, reverse=a.reverse)
        dot_path = Path(a.dot)
        dot_path.parent.mkdir(parents=True, exist_ok=True)
        dot_path.write_text(text, encoding="utf-8")
        _print(f"wrote {dot_path} (render with Graphviz: dot -Tsvg {dot_path} -o deps.svg)")
    _note(LICENSED_NOTE)
    return 0


def cmd_meta(ctx: _Context) -> int:
    """meta --indicators A,B|all --groups X,Y [--keep-contacts] [--out FILE]."""
    a = ctx.args
    _check_ext(a.out, TABLE_EXTS)
    indicators, groups = _codes(a.indicators), _codes(a.groups, "--groups")
    client, rel = ctx.client(), ctx.release()
    df = fetch_metadata(client, rel["Id"], indicators=indicators, groups=groups, keep_contacts=a.keep_contacts)
    if df.empty:
        _note("no metadata returned: check the codes (`oegem catalogue search`).")
        return 1
    _emit(df, a.out, sheet="metadata", columns=None if a.out else [c for c in META_COLUMNS if c in df.columns])
    _note(f"{len(df)} variable(s), {df.shape[1] - 2} metadata field(s)"
          + ("" if a.out else " (main fields shown; --out FILE writes all)"))
    if a.keep_contacts:
        _note(CONTACTS_NOTE)
    _note(LICENSED_NOTE)
    return 0


def _group_frequencies(client, fid, groups: List[str], indicator) -> dict:
    """Group -> "Q"/"A" from one data fetch of one indicator (annual fallback on); {} if it fails."""
    code = str(indicator or "").strip()
    if not code:
        return {}
    try:
        df = fetch(client, fid, [code], groups, annual_fallback=True, label="frequency")
    except (OEError, ValueError) as exc:
        _note(f"frequency check with {code} failed ({_one_line(exc)}); the frequency column stays empty")
        return {}
    freq = {str(g): ("Q" if (sub["freq"] == "Q").any() else "A") for g, sub in df.groupby("group")}
    missing = [g for g in groups if g not in freq]
    if missing:
        _note(f"no {code} values for {', '.join(missing[:10])}{' ...' if len(missing) > 10 else ''}: frequency "
              "unknown there (try another series with --freq-indicator)")
    return freq


def cmd_profile(ctx: _Context) -> int:
    """profile --groups G1,G2|all [--indicators ...] [--freq-indicator CODE] [--out FILE]."""
    a = ctx.args
    _check_ext(a.out, TABLE_EXTS)
    groups = _codes(a.groups, "--groups")
    client, rel = ctx.client(), ctx.release()
    fid = rel["Id"]
    if groups == "all":
        groups = [str(g) for g in catalogue_groups(client, fid)["code"]]
    eq_df = fetch_equations(client, fid, groups=groups, indicators=_optional_codes(a.indicators))
    prof = group_profile(eq_df, freq_map=_group_frequencies(client, fid, groups, a.freq_indicator))
    _emit(prof, a.out, sheet="profile")
    counts = prof["suggested_class"].value_counts()
    _note("classes: " + ", ".join(f"{int(n)} {c}" for c, n in counts.items()))
    _note("suggested_class is a heuristic read from the equations, not vendor metadata; the rules are in "
          "help(oegem.equations.group_profile).")
    _note(LICENSED_NOTE)
    return 0


def cmd_scenario(ctx: _Context) -> int:
    """scenario validate|build|show|diff."""
    actions = {"validate": _scenario_validate, "build": _scenario_build, "show": _scenario_show,
               "diff": _scenario_diff}
    return actions[ctx.args.scenario_command](ctx)


def _scenario_validate(ctx: _Context) -> int:
    a = ctx.args
    indicators = groups = None
    if a.catalogue:
        client, rel = ctx.client(), ctx.release()
        indicators = list(catalogue_indicators(client, rel["Id"])["code"])
        groups = list(catalogue_groups(client, rel["Id"])["code"])
    not_parsed = n_scenarios = n_warnings = 0
    library = {}  # files are read in order, so include: may name scenarios of earlier files
    for f in a.files:
        try:
            scenarios = load_scenarios(f, library=library)
            library.update({s.name: s for s in scenarios})
        except Exception as exc:     # YAML, JSON and command syntax errors alike
            not_parsed += 1
            _print(f"FAIL  {f}: {_one_line(exc)}")
            continue
        for s in scenarios:
            warnings = s.validate(indicators=indicators, groups=groups)
            n_scenarios += 1
            n_warnings += len(warnings)
            _print(f"{'WARN' if warnings else 'OK  '}  {f} :: {s.name} ({_commands(len(s.commands))})")
            for w in warnings:
                _print(f"      - {w}")
    _print(f"{len(a.files)} file(s), {n_scenarios} scenario(s), {n_warnings} warning(s), "
           f"{not_parsed} file(s) not parsed")
    return 1 if not_parsed or (a.strict and n_warnings) else 0


def _scenario_build(ctx: _Context) -> int:
    a = ctx.args
    out_dir = Path(a.out_dir)
    for s in load_scenarios(a.file):
        for w in s.validate():
            _note(f"warning: {w}")
        path = out_dir / f"{slug(s.name)}.3fs"
        s.to_3fs(path)
        _print(f"wrote {path} ({_commands(len(s.commands))})")
    return 0


def _scenario_show(ctx: _Context) -> int:
    a = ctx.args
    scenarios = load_scenarios(a.file)
    if a.name:
        scenarios = [s for s in scenarios if s.name == a.name]
        if not scenarios:
            raise ValueError(f"{a.file} has no scenario {a.name!r}.")
    for i, s in enumerate(scenarios):
        if i:
            _print()
        _print(f"# scenario: {s.name}")
        if s.description.strip():
            _print(f"# description: {' '.join(s.description.split())}")
        if s.solve_from and s.solve_to:
            _print(f"# solve: {s.solve_from}:{s.solve_to}")
        text = s.commands_text().rstrip("\n")
        _print(text or "# (no commands)")
    return 0


def _scenario_diff(ctx: _Context) -> int:
    a = ctx.args
    _check_ext(a.out, TABLE_EXTS)
    df = diff_scenarios(_pick_scenario(a.a), _pick_scenario(a.b), changes_only=a.changes_only)
    _emit(df, a.out, sheet="diff")
    if len(df) and "status" in df.columns:
        counts = df["status"].value_counts()
        _print("summary: " + ", ".join(f"{int(n)} {status}" for status, n in counts.items()))
    return 0


def cmd_run(ctx: _Context) -> int:
    """run CONFIG [--dry-run] [--only a,b] [--no-resume]."""
    a = ctx.args
    config = load_config(a.config)               # config errors before any token or API problem
    result = run_batch(config, client=ctx.client(), dry_run=a.dry_run, only=a.only, resume=not a.no_resume)
    rows = []
    for e in result.scenarios:
        seconds, n = e.get("seconds"), e.get("n_commands")
        rows.append({"scenario": e.get("name"), "status": e.get("status"),
                     "commands": int(n) if isinstance(n, (int, float)) and n == n else "",
                     "seconds": round(float(seconds), 1) if isinstance(seconds, (int, float)) else "",
                     "output": e.get("output_path") or "", "failure": " ".join(str(e.get("failure") or "").split())})
    _print(_frame_text(pd.DataFrame(rows)))
    _print(f"output folder: {result.out_dir}")
    if result.dry_run:
        _print("dry run: scenarios built, checked and written as .3fs files; nothing was solved.")
    if result.failed:                # includes failures an --only run kept from earlier runs
        _note(f"{len(result.failed)} scenario(s) failed: {', '.join(map(str, result.failed))} "
              "(see the failure column and manifest.json)")
        return 1
    return 0


def cmd_report(ctx: _Context) -> int:
    """report CONFIG."""
    spec, _ = load_report_config(ctx.args.config)
    client = ctx.client() if spec.get("forecasts") else None   # an `input:` report needs no API
    result = build_report(ctx.args.config, client=client)
    names = [name for name in result["tables"] if name != "README"]
    _print(f"{len(names)} table(s): {', '.join(names)}")
    for path in result["files"]:
        _print(f"wrote {path}")
    return 0


def cmd_plot(ctx: _Context) -> int:
    """plot --input RUN_DIR|FILE --indicator X [--groups A,B] [--transforms ...] [--deviation ...] --out FILE."""
    from .plots import save as save_chart
    from .plots import small_multiples

    a = ctx.args
    _check_ext(a.out, CHART_EXTS)
    df = load_results(a.input)
    codes = df["indicator"].astype(str)
    indicator = a.indicator.strip()
    sub = df[codes == indicator]
    if sub.empty:
        sub = df[codes.str.upper() == indicator.upper()]
    if sub.empty:
        available = sorted(codes.unique())
        raise ValueError(f"No rows for indicator {indicator!r} in {a.input}; it holds: "
                         f"{', '.join(available[:30])}{' ...' if len(available) > 30 else ''}.")
    indicator = str(sub["indicator"].iloc[0])
    if a.forecasts:
        keep = set(_split(a.forecasts)) | {a.baseline}
        sub = sub[sub["forecast"].isin(keep)]
    sub = apply_transforms(sub, _steps(a.transforms), baseline=a.baseline)
    groups = _split(a.groups) or sorted(sub["group"].astype(str).unique())
    kind = "paths" if a.deviation == "none" else "deviations"
    fig = small_multiples(sub, indicator, groups, kind=kind, deviation=a.deviation if kind == "deviations" else "abs",
                          baseline=a.baseline, title=a.title, ncols=a.ncols)
    _print(f"wrote {save_chart(fig, a.out)}")
    return 0


def cmd_compare_releases(ctx: _Context) -> int:
    """compare-releases A B --indicators ... --groups ... [--transforms ...] [--from P] [--to P] [--out FILE]."""
    a = ctx.args
    _check_ext(a.out, TABLE_EXTS)
    df = compare_releases(ctx.client(), a.a, a.b, _codes(a.indicators), _codes(a.groups, "--groups"),
                          transforms=tuple(_steps(a.transforms)), start=a.start, end=a.end)
    _emit(df, a.out, sheet="compare", long=True)
    labels = [str(f) for f in pd.unique(df["forecast"]) if f != "revision"] if len(df) else []
    if labels:
        _note(f"compared {' and '.join(labels)}; the revision rows are B - A")
    return 0


def cmd_workspace(ctx: _Context) -> int:
    """workspace ls|mkdir|mv|archive|rm."""
    a = ctx.args
    action = a.workspace_command
    if action == "rm" and not a.yes:
        _note(f"refusing to delete {a.path} without --yes: deletion cannot be undone. "
              "Shared items cannot be deleted at all; use `oegem workspace archive` for those.")
        return 2
    if action == "ls":
        _check_ext(a.out, TABLE_EXTS)
        df = walk(ctx.client(), a.path, max_depth=a.depth)
        _emit(df, a.out, sheet="workspace", columns=["depth", "type", "name", "path"])
        return 0
    client = ctx.client()
    if action == "mkdir":
        if a.parents:
            ensure_folder_tree(client, a.path)
            found = client.resource(a.path)
        else:
            found = make_folder(client, a.path)
        _print(f"folder ready: {found.get('Path') or a.path}")
    elif action == "mv":
        found = move(client, a.path, a.new_parent)
        _print(f"moved {a.path} -> {found.get('Path') or a.new_parent}")
    elif action == "archive":
        found = archive(client, a.path, a.archive_folder)
        _print(f"archived {a.path} -> {found.get('Path') or a.archive_folder}")
    else:
        delete(client, a.path, confirm=True)
        _print(f"deleted {a.path}")
    return 0


def cmd_check_leaks(ctx: _Context) -> int:
    """check-leaks [PATHS...] [--staged] [--tracked] [--history] [--deny FILE] -> oegem.leakcheck."""
    a = ctx.args
    try:
        from . import leakcheck
    except ImportError as exc:
        raise ValueError(f"the leak checker is not available in this installation ({exc}).") from None
    argv = [str(p) for p in a.paths]
    for flag in ("staged", "tracked", "history", "list_rules"):
        if getattr(a, flag, False):
            argv.append("--" + flag.replace("_", "-"))
    if a.deny:
        argv += ["--deny", a.deny]
    if a.repo:
        argv += ["--repo", a.repo]
    return int(leakcheck.main(argv))


def cmd_init(ctx: _Context) -> int:
    """init DIR: starter project folder."""
    target = Path(ctx.args.dir)
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ValueError(f"{target} exists and is not empty; pick a new folder (init never overwrites files).")
    texts = [(dest, _template(src)) for src, dest in TEMPLATES]      # read all before writing any
    target.mkdir(parents=True, exist_ok=True)
    for dest, text in texts:
        (target / dest).write_text(text, encoding="utf-8")
    _print(f"created {target} with: {', '.join(dest for dest, _ in texts)}")
    _print("next steps:")
    _print(f"  cd {target}")
    _print("  oegem --demo run run.yaml            # try it offline on synthetic data")
    _print("  oegem --demo report report.yaml")
    _print("  oegem catalogue search <text>        # check every mnemonic against your own catalogue")
    _print("  oegem run run.yaml                   # real solves; needs OE_TOKEN (oegem auth status)")
    return 0


# --------------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    """The argparse parser behind `oegem` (exposed for documentation tools and tests)."""
    raw = argparse.RawDescriptionHelpFormatter

    # Global flags also work after the subcommand; SUPPRESS keeps a subcommand from
    # resetting what was given before it.
    common = argparse.ArgumentParser(add_help=False)
    group = common.add_argument_group("global options")
    group.add_argument("--demo", action="store_true", default=argparse.SUPPRESS,
                       help="synthetic offline backend (same as OEGEM_DEMO=1)")
    group.add_argument("-v", "--verbose", action="count", default=argparse.SUPPRESS,
                       help="log more (-v info, -vv debug and tracebacks)")

    release = argparse.ArgumentParser(add_help=False)
    release.add_argument("--release", metavar="SPEC",
                         help="model release: latest, latest:5yr, latest:25yr, a release name, a path or a "
                              f"forecast id (default: ${RELEASE_ENV} or {DEFAULT_RELEASE})")
    release.add_argument("--root", metavar="PATH", help="release tree to search (default: the GEM release root)")

    out = argparse.ArgumentParser(add_help=False)
    out.add_argument("--out", metavar="FILE",
                     help="write the table to FILE; the extension picks the format: .csv .xlsx .parquet .md "
                          ".json (default: print it)")

    parser = argparse.ArgumentParser(
        prog="oegem", formatter_class=raw, epilog=EPILOG,
        description="Oxford Economics Global Economic Model (GEM) web API toolkit: releases, catalogue, data, "
                    "scenarios, solves, reports and model introspection.")
    parser.add_argument("--demo", action="store_true",
                        help="synthetic offline backend; numbers are NOT model output (same as OEGEM_DEMO=1)")
    parser.add_argument("-v", "--verbose", action="count", default=0,
                        help="log more (-v info, -vv debug and tracebacks)")
    parser.add_argument("--version", action="version", version=f"oegem {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND", title="commands")

    def add(subparsers, name, handler, text, parents=(), **kw):
        p = subparsers.add_parser(name, help=text, description=kw.pop("description", text),
                                  parents=[common, *parents], formatter_class=raw, **kw)
        if handler is not None:
            p.set_defaults(handler=handler)
        return p

    # auth
    p = add(sub, "auth", cmd_auth, "check the API token or fetch a new one")
    actions = p.add_subparsers(dest="auth_command", metavar="ACTION", required=True)
    add(actions, "status", None, "is a token set, when does it expire, does /me answer? (never prints the token)")
    t = add(actions, "token", None, "fetch a token with the OAuth password grant (settings from OE_AUTH_DOMAIN, "
                                    "OE_AUTH_CLIENT_ID and OE_AUTH_AUDIENCE; the password is asked for)")
    t.add_argument("--username", required=True, help="your account user name")
    t.add_argument("--print", dest="print_token", action="store_true",
                   help="print only the token on stdout so a shell can capture it into OE_TOKEN")

    # releases
    p = add(sub, "releases", cmd_releases, "list model releases (newest first), or resolve a release spec",
            parents=[out])
    p.add_argument("--root", metavar="PATH", help="release tree to walk (default: the GEM release root)")
    p.add_argument("--depth", type=int, default=4, metavar="N", help="folder levels to walk (default: 4)")
    p.add_argument("--horizon", metavar="H", help="only this horizon, e.g. 5yr or 25yr")
    actions = p.add_subparsers(dest="releases_command", metavar="ACTION")
    r = add(actions, "resolve", None, "show the release a spec picks: name, path and forecast id")
    r.add_argument("spec", metavar="SPEC", help="latest, latest:5yr, latest:25yr, a release name, a path or an id")
    r.add_argument("--root", metavar="PATH", default=argparse.SUPPRESS, help="release tree to search")

    # catalogue
    p = add(sub, "catalogue", cmd_catalogue, "indicator and group catalogue of a release", parents=[release, out],
            epilog="examples:\n  oegem catalogue search \"oil price\"\n  oegem catalogue indicators --search "
                   "\"^GDP\" --out indicators.csv\n  oegem catalogue shocks")
    p.add_argument("kind", choices=("indicators", "groups", "shocks", "search"),
                   help="indicators, groups, shocks (shock/residual/add-factor/dummy variables) or search")
    p.add_argument("pattern", nargs="?", metavar="PATTERN",
                   help="text or regular expression matched against code and name (required for search)")
    p.add_argument("--search", metavar="REGEX", help="same as PATTERN")
    p.add_argument("--in", dest="within", choices=("indicators", "groups", "both"), default="both",
                   help="what `catalogue search` looks through (default: both)")
    p.add_argument("--plain", action="store_true", help="treat the pattern as plain text, not a regular expression")

    # data
    p = add(sub, "data", cmd_data, "fetch values (levels) of a release as a long frame", parents=[release, out])
    p.add_argument("--indicators", required=True, metavar="A,B|all", help="indicator codes, or all")
    p.add_argument("--groups", required=True, metavar="X,Y|all", help="group codes, or all")
    p.add_argument("--from", dest="start", metavar="PERIOD", help="first period, e.g. 2024Q1 or 2024")
    p.add_argument("--to", dest="end", metavar="PERIOD", help="last period")
    p.add_argument("--freq", metavar="FREQ", help="Annual for annual values everywhere (default: quarterly where "
                                                  "available)")
    p.add_argument("--label", help="forecast label in the output (default: the release name)")
    p.add_argument("--no-annual-fallback", action="store_true",
                   help="do not re-request series that come back empty at annual frequency")

    # equations / params / deps
    note = "Equations and coefficients are licensed model content: keep the exports out of repositories."
    p = add(sub, "equations", cmd_equations, "export the equations of some groups (md, tex, xlsx, json)",
            parents=[release], epilog=note)
    p.add_argument("--groups", required=True, metavar="G[,G2]", help="group codes")
    p.add_argument("--indicators", metavar="A,B", help="only these indicators (default: the whole catalogue)")
    p.add_argument("--format", default="md", metavar="FMT[,FMT]", help="md, tex, xlsx and/or json (default: md)")
    p.add_argument("--out-dir", metavar="DIR", help=f"output folder (default: {EQUATIONS_DIR.as_posix()})")
    p.add_argument("--name", default="equations", help="file name stem (default: equations)")
    p.add_argument("--math", action="store_true", help="markdown: add a LaTeX rendering of each algebraic equation")
    p.add_argument("--glossary", action="store_true", help="add a glossary of the indicators referenced")
    p.add_argument("--only-with-equations", action="store_true",
                   help="leave out identities and exogenous series that have no equation")

    p = add(sub, "params", cmd_params, "numbers in equations: constants, coefficients, exponents, arguments",
            parents=[release, out], epilog=note)
    p.add_argument("--groups", required=True, metavar="G[,G2]", help="group codes")
    p.add_argument("--indicators", metavar="A,B", help="only these indicators (default: the whole catalogue)")

    p = add(sub, "deps", cmd_deps, "what a variable's equation refers to, or (--reverse) which equations use it",
            parents=[release, out], epilog=note)
    p.add_argument("--groups", required=True, metavar="G[,G2]", help="groups whose equations are read")
    p.add_argument("--indicator", required=True, metavar="X", help="the variable: a code or CODE:GROUP")
    p.add_argument("--indicators", metavar="A,B", help="only read these equations (default: the whole catalogue)")
    p.add_argument("--reverse", action="store_true", help="list the equations that use the variable instead")
    p.add_argument("--dot", metavar="FILE", help="also write a Graphviz DOT graph around the variable")
    p.add_argument("--depth", type=int, default=2, metavar="N", help="steps the DOT graph follows (default: 2)")

    p = add(sub, "meta", cmd_meta, "variable metadata: units, scaling, history end, annualisation, base years",
            parents=[release, out],
            epilog="Contact names, e-mail addresses and internal ids are left out unless --keep-contacts. "
                   "Metadata describes licensed model content: keep exports out of repositories.")
    p.add_argument("--indicators", required=True, metavar="A,B|all", help="indicator codes, or all")
    p.add_argument("--groups", required=True, metavar="X,Y|all", help="group codes, or all")
    p.add_argument("--keep-contacts", action="store_true",
                   help="keep ContactName, ContactEmail and InternalId (personal data: never share the output)")

    p = add(sub, "profile", cmd_profile, "economy profile per group from its equations, with a heuristic class "
                                         "(full, satellite, annual-only, aggregate, unknown)",
            parents=[release, out], epilog=note)
    p.add_argument("--groups", required=True, metavar="G1,G2|all",
                   help="group codes, or all (every group: many requests)")
    p.add_argument("--indicators", metavar="A,B", help="only these indicators (default: the whole catalogue)")
    p.add_argument("--freq-indicator", default="GDP", metavar="CODE",
                   help="series fetched once to tell quarterly from annual-only groups (default: GDP; check the "
                        "mnemonic in your own catalogue)")

    # scenario
    p = add(sub, "scenario", cmd_scenario, "check, convert, show and compare scenario files (.yaml .json .3fs)")
    actions = p.add_subparsers(dest="scenario_command", metavar="ACTION", required=True)
    v = add(actions, "validate", None, "parse scenario files and list warnings (exit 1 if a file does not parse)",
            parents=[release])
    v.add_argument("files", nargs="+", metavar="FILE")
    v.add_argument("--catalogue", action="store_true",
                   help="also check mnemonics and groups against the catalogue of --release")
    v.add_argument("--strict", action="store_true", help="exit 1 on warnings too")
    b = add(actions, "build", None, "write each scenario of a YAML/JSON file as a .3fs command file")
    b.add_argument("file", metavar="FILE")
    b.add_argument("--out-dir", default=str(Path("outputs") / "scenarios"), metavar="DIR",
                   help="folder for the .3fs files (default: outputs/scenarios)")
    s = add(actions, "show", None, "print the command lines of the scenarios in a file")
    s.add_argument("file", metavar="FILE")
    s.add_argument("--name", help="only this scenario")
    d = add(actions, "diff", None, "compare two scenarios command by command", parents=[out])
    d.add_argument("a", metavar="A", help="scenario file holding one scenario, or FILE::NAME")
    d.add_argument("b", metavar="B", help="scenario file holding one scenario, or FILE::NAME")
    d.add_argument("--changes-only", action="store_true", help="leave out commands that are the same")

    # run / report / plot / compare-releases
    p = add(sub, "run", cmd_run, "solve the scenarios of a run config, fetch the results, write a manifest")
    p.add_argument("config", metavar="CONFIG", help="run config (.yaml or .json)")
    p.add_argument("--dry-run", action="store_true", help="build, check and write the .3fs files; no solves")
    p.add_argument("--only", metavar="A,B", help="solve only these scenarios (the others keep earlier results)")
    p.add_argument("--no-resume", action="store_true",
                   help="solve again even where an earlier run solved the same commands")

    p = add(sub, "report", cmd_report, "report tables, workbook, markdown/html and charts from a report config")
    p.add_argument("config", metavar="CONFIG", help="report config (.yaml or .json)")

    p = add(sub, "plot", cmd_plot, "chart one indicator across groups from a run folder or results file")
    p.add_argument("--input", required=True, metavar="RUN_DIR|FILE", help="run folder or results file")
    p.add_argument("--indicator", required=True, metavar="X")
    p.add_argument("--groups", metavar="A,B", help="one panel per group (default: every group in the data)")
    p.add_argument("--transforms", metavar="STEPS", help="e.g. annual_avg,yoy (default: level)")
    p.add_argument("--deviation", choices=("none", "abs", "pct"), default="none",
                   help="none draws paths; abs or pct draws differences from the baseline")
    p.add_argument("--baseline", default="baseline", metavar="LABEL", help="baseline label (default: baseline)")
    p.add_argument("--forecasts", metavar="A,B", help="only these scenarios (default: all)")
    p.add_argument("--title", help="figure title")
    p.add_argument("--ncols", type=int, default=3, metavar="N", help="panels per row (default: 3)")
    p.add_argument("--out", required=True, metavar="FILE", help="chart file: .png, .pdf or .svg")

    p = add(sub, "compare-releases", cmd_compare_releases, "two releases side by side, plus the revision (B - A)",
            parents=[out])
    p.add_argument("a", metavar="A", help="release spec A (e.g. a release name)")
    p.add_argument("b", metavar="B", help="release spec B (e.g. latest:5yr)")
    p.add_argument("--indicators", required=True, metavar="A,B|all")
    p.add_argument("--groups", required=True, metavar="X,Y|all", help="group codes, or all")
    p.add_argument("--transforms", metavar="STEPS", help="chain applied to both first, e.g. annual_avg,yoy")
    p.add_argument("--from", dest="start", metavar="PERIOD", help="first period kept (after the transforms)")
    p.add_argument("--to", dest="end", metavar="PERIOD", help="last period kept")

    # workspace
    p = add(sub, "workspace", cmd_workspace, "list and organise folders and forecasts in the workspace",
            epilog="Quote paths that contain $, e.g. '<shared root>/$Archive'. In Git Bash write me/... "
                   "instead of /me/... (MSYS turns arguments that start with / into Windows paths).")
    actions = p.add_subparsers(dest="workspace_command", metavar="ACTION", required=True)
    w = add(actions, "ls", None, "list a folder (default: /me)", parents=[out])
    w.add_argument("path", nargs="?", default="/me", metavar="PATH")
    w.add_argument("--depth", type=int, default=1, metavar="N", help="folder levels to list (default: 1)")
    w = add(actions, "mkdir", None, "create a folder")
    w.add_argument("path", metavar="PATH")
    w.add_argument("-p", "--parents", action="store_true", help="create missing parent folders too")
    w = add(actions, "mv", None, "move a folder or forecast into another folder")
    w.add_argument("path", metavar="PATH")
    w.add_argument("new_parent", metavar="NEW_PARENT")
    w = add(actions, "archive", None, "move an item into an archive folder (shared items cannot be deleted)")
    w.add_argument("path", metavar="PATH")
    w.add_argument("archive_folder", metavar="ARCHIVE_FOLDER")
    w = add(actions, "rm", None, "delete a folder or forecast in your own area (needs --yes; cannot be undone)")
    w.add_argument("path", metavar="PATH")
    w.add_argument("--yes", action="store_true", help="confirm the deletion")

    # check-leaks / init
    p = add(sub, "check-leaks", cmd_check_leaks, "scan files or git content for credentials and model content")
    p.add_argument("paths", nargs="*", metavar="PATH", help="files or folders (default: tracked files, or .)")
    p.add_argument("--staged", action="store_true", help="scan the staged files (what the pre-commit hook does)")
    p.add_argument("--tracked", action="store_true", help="scan every tracked file")
    p.add_argument("--history", action="store_true", help="scan every blob reachable from any ref")
    p.add_argument("--deny", metavar="FILE", help="deny-term list to use")
    p.add_argument("--repo", metavar="DIR", help="repository for the git modes (default: .)")
    p.add_argument("--list-rules", action="store_true", help="print the rules and exit")

    p = add(sub, "init", cmd_init, "create a starter project folder: run, scenario, report and grouping configs")
    p.add_argument("dir", metavar="DIR", help="new (or empty) folder")
    return parser


# --------------------------------------------------------------------------- entry point


def _api_hint(exc: OEError) -> str:
    status = getattr(exc, "status", None)
    if status == 401:
        return "set a fresh OE_TOKEN (tokens last about 24 hours); check it with `oegem auth status`."
    if status == 403:
        return "your account cannot reach this resource; check the path or release."
    if status == 404:
        return "check the path or release spec (`oegem releases`, `oegem workspace ls`)."
    if status is None and "OE_TOKEN" in str(exc):
        return "or try the command offline first with --demo."
    return "run with -v for request details, or try the command offline with --demo."


def _fail(exc: BaseException, verbosity: int, command: str) -> int:
    """Print an exception as one error line (plus any how-to lines and a hint); return 2."""
    if verbosity >= 2:
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)
    text = redact(str(exc)).strip() or type(exc).__name__
    first, _, rest = text.partition("\n")
    try:
        import yaml
        yaml_error = isinstance(exc, yaml.YAMLError)
    except ImportError:
        yaml_error = False
    if isinstance(exc, OEError):
        hint = _api_hint(exc)
    elif isinstance(exc, FileNotFoundError):
        name = str(exc.filename or first)
        first, rest = f"file not found: {name}", ""
        if os.name == "nt" and len(str(Path(name).resolve())) >= 260:
            hint = ("the full path is over Windows' 260-character limit; work in a shorter folder "
                    "or enable long paths in Windows.")
        else:
            hint = "check the path; relative paths start from the current folder."
    elif isinstance(exc, PermissionError):
        first, rest = f"cannot write or read {exc.filename or first}: permission denied", ""
        hint = "close the file if it is open in Excel or another program, then run the command again."
    elif yaml_error:
        first, rest = "could not parse YAML: " + " ".join(text.split())[:300], ""
        hint = 'check the indentation, and quote period ranges such as "2026:2030".'
    elif isinstance(exc, ValueError):
        hint = f"see `oegem {command} --help`." if command else "see `oegem --help`."
    elif isinstance(exc, ImportError):
        hint = "install the missing package, or pick another output format."
    else:
        first = f"unexpected {type(exc).__name__}: {first}"
        hint = "re-run with -vv to see the traceback."
    _note(f"error: {first}")
    if rest.strip():
        _note(rest.rstrip())
    _note(f"hint: {hint}")
    return 2


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the command line and return its exit code (the console script passes it to sys.exit).

    Args: argv is the argument list without the program name (None reads sys.argv).
    Returns 0 on success, 1 when a command ran but found problems, 2 on usage, input or
    API errors. Tracebacks are shown only with -vv.
    """
    parser = build_parser()
    try:
        args = parser.parse_args(None if argv is None else [str(x) for x in argv])
    except SystemExit as exc:        # --help and --version (0), usage errors (2)
        return exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 2)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 2
    verbosity = int(getattr(args, "verbose", 0) or 0)
    restore = _configure_logging(verbosity)
    ctx = _Context(args)
    try:
        if ctx.demo:
            _note(DEMO_NOTICE)
        return int(handler(ctx) or 0)
    except KeyboardInterrupt:
        _note("interrupted")
        return 130
    except Exception as exc:         # one line per error; tracebacks only with -vv
        return _fail(exc, verbosity, str(getattr(args, "command", "") or ""))
    finally:
        ctx.close()
        restore()
