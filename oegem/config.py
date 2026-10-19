"""Run configuration for the batch runner (YAML or JSON).

    run_name: example_oil
    model:
      release: latest:5yr            # or a release name ("Sep26_2 5yr"), a full path, or a forecast id
      root: oxford-economics/releases/Global Economic Model    # optional
    solve:
      from: 2026Q3
      to: 2031Q4
      output_folder: /me/oegem-runs  # created if missing; solves go to <folder>/<run_name>/<scenario>-<stamp>
      max_parallel: 1                # 1..4 solves in flight (no threads; the runner polls them in turn)
      resolve: commands              # commands (default) | levels: turn pct/abs/ratio shocks into SET levels
      poll_seconds: 10               # optional pause between status checks
      timeout_seconds: 3600          # optional wait per solve
    fetch:
      indicators: [GDP, CPI, RSH]    # or "all"
      groups: [US, CHINA, WORLD]
      from: 2024Q1
      to: 2031Q4
      annual_fallback: true
    scenarios:                       # inline scenarios (schema in oegem.scenario) and/or
      - name: oil_up_20
        shocks:
          - {var: WPO_EQN:WORLD, type: pct, start: 2027Q1, values: [20, 20, 20, 20]}
    scenario_files: [scenarios/oil.yaml]   # relative to this file
    output:
      dir: outputs/{run_name}        # relative to this file
      formats: [csv, xlsx]           # results.<ext>; parquet also allowed

The mnemonics and shock sizes above are illustrative: check the mnemonic in your own
catalogue (`oegem catalogue search`).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Union

from .periods import normalize_period, parse_range
from .resources import GEM_ROOT
from .scenario import Scenario, load_scenarios, read_structured, scenarios_from_dicts
from .solve import slug

log = logging.getLogger("oegem")

TOP_KEYS = ("run_name", "description", "model", "solve", "fetch", "scenarios", "scenario_files", "output")
SECTION_KEYS = {
    "model": ("release", "root"),
    "solve": ("from", "to", "output_folder", "max_parallel", "resolve", "poll_seconds", "timeout_seconds"),
    "fetch": ("indicators", "groups", "from", "to", "annual_fallback"),
    "output": ("dir", "formats"),
}
RESOLVE_MODES = ("commands", "levels")
FORMATS = ("csv", "xlsx", "parquet")
MAX_PARALLEL = 4
RESERVED_NAMES = ("baseline",)


@dataclass
class RunConfig:
    """A validated run configuration (paths already resolved against the config file's folder).

    poll_seconds None means 10 s, or 0 with the demo backend.
    """

    run_name: str
    solve_from: str
    solve_to: str
    indicators: Union[str, List[str]]
    groups: Union[str, List[str]]
    scenarios: List[Scenario]
    out_dir: Path
    release: str = "latest:5yr"
    root: str = GEM_ROOT
    output_folder: str = "/me/oegem-runs"
    max_parallel: int = 1
    resolve: str = "commands"
    poll_seconds: Optional[float] = None
    timeout_seconds: float = 3600.0
    fetch_from: Optional[str] = None
    fetch_to: Optional[str] = None
    annual_fallback: bool = True
    formats: List[str] = field(default_factory=lambda: ["csv"])
    description: str = ""
    source: Optional[Path] = None

    @property
    def scenario_names(self) -> List[str]:
        """Names of the scenarios, in run order."""
        return [sc.name for sc in self.scenarios]

    def scenario(self, name: str) -> Scenario:
        """The scenario with this name (KeyError if absent)."""
        for sc in self.scenarios:
            if sc.name == name:
                return sc
        raise KeyError(f"No scenario {name!r} in run {self.run_name!r}; have {', '.join(self.scenario_names)}.")


def _section(d: Mapping[str, Any], key: str) -> Dict[str, Any]:
    value = d.get(key)
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{key}: must be a mapping with keys {', '.join(SECTION_KEYS[key])}.")
    unknown = sorted(set(map(str, value)) - set(SECTION_KEYS[key]))
    if unknown:
        raise ValueError(f"{key}: unknown key(s) {', '.join(unknown)}; allowed: {', '.join(SECTION_KEYS[key])}.")
    return dict(value)


def _codes(x, label: str) -> Union[str, List[str]]:
    if isinstance(x, str):
        if x.strip().lower() == "all":
            return "all"
        x = x.split(",")
    items = [str(c).strip() for c in (x or []) if str(c).strip()]
    if not items:
        raise ValueError(f"fetch.{label}: give a list of codes (e.g. [GDP, CPI] / [US, CHINA]) or 'all'.")
    return items


def _optional_period(x, label: str) -> Optional[str]:
    if x is None or str(x).strip() == "":
        return None
    try:
        return normalize_period(x)
    except ValueError as exc:
        raise ValueError(f"{label}: {exc}") from None


def _number(x, label: str, default, lo=0.0) -> float:
    if x is None:
        return default
    try:
        v = float(x)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a number of seconds, got {x!r}.") from None
    if v < lo:
        raise ValueError(f"{label} must be >= {lo}, got {x!r}.")
    return v


def config_from_dict(d: Mapping[str, Any], base_dir=None, source=None) -> RunConfig:
    """Validate a run-config mapping and return a RunConfig.

    Relative scenario_files, scenario file: entries and output.dir resolve against
    base_dir (default: the current folder). Raises ValueError with a hint on what to fix.
    """
    if not isinstance(d, Mapping):
        raise ValueError("A run config must be a mapping; see the example in oegem.config.")
    unknown = sorted(set(map(str, d)) - set(TOP_KEYS))
    if unknown:
        raise ValueError(f"Unknown run-config key(s) {', '.join(unknown)}; allowed: {', '.join(TOP_KEYS)}.")
    base = Path(base_dir) if base_dir is not None else Path.cwd()
    run_name = str(d.get("run_name") or "").strip()
    if not run_name:
        raise ValueError("run_name is required, e.g. run_name: example_oil.")
    model, solve, fetch, output = (_section(d, k) for k in ("model", "solve", "fetch", "output"))

    if solve.get("from") is None or solve.get("to") is None:
        raise ValueError("solve.from and solve.to are required, e.g. solve: {from: 2026Q3, to: 2031Q4}.")
    try:
        solve_from, solve_to = parse_range((solve["from"], solve["to"]))
    except ValueError as exc:
        raise ValueError(f"solve: {exc}") from None
    max_parallel = solve.get("max_parallel", 1)
    if isinstance(max_parallel, bool) or not isinstance(max_parallel, int) or not 1 <= max_parallel <= MAX_PARALLEL:
        raise ValueError(f"solve.max_parallel must be a whole number from 1 to {MAX_PARALLEL}, "
                         f"got {solve.get('max_parallel')!r}.")
    resolve = str(solve.get("resolve") or "commands").strip().lower()
    if resolve not in RESOLVE_MODES:
        raise ValueError(f"solve.resolve must be one of {', '.join(RESOLVE_MODES)}, got {solve.get('resolve')!r}.")
    output_folder = str(solve.get("output_folder") or "/me/oegem-runs").strip().rstrip("/")
    if not output_folder:
        raise ValueError("solve.output_folder must be a workspace folder such as /me/oegem-runs.")

    if "indicators" not in fetch or "groups" not in fetch:
        raise ValueError("fetch.indicators and fetch.groups are required, e.g. "
                         "fetch: {indicators: [GDP, CPI], groups: [US, CHINA]}.")
    indicators, groups = _codes(fetch["indicators"], "indicators"), _codes(fetch["groups"], "groups")
    fetch_from = _optional_period(fetch.get("from"), "fetch.from")
    fetch_to = _optional_period(fetch.get("to"), "fetch.to")

    scenarios: List[Scenario] = []
    for f in ([d["scenario_files"]] if isinstance(d.get("scenario_files"), str) else d.get("scenario_files") or []):
        path = (Path(f) if Path(f).is_absolute() else base / f).resolve()
        if not path.is_file():
            raise ValueError(f"scenario_files: {path} not found (paths are relative to the config file).")
        # files load in order, so include: may name scenarios of the files listed before
        scenarios.extend(load_scenarios(path, library={sc.name: sc for sc in scenarios}))
    inline = d.get("scenarios") or []
    if inline:
        library = {sc.name: sc for sc in scenarios}
        scenarios.extend(scenarios_from_dicts(inline, base_dir=base, library=library))
    if not scenarios:
        raise ValueError("No scenarios: add a scenarios: list or scenario_files: [...].")
    seen: Dict[str, str] = {}
    for sc in scenarios:
        if sc.name.lower() in RESERVED_NAMES:
            raise ValueError(f"Scenario name {sc.name!r} is reserved for the input forecast; rename it.")
        key = slug(sc.name).lower()
        if key in seen:
            raise ValueError(f"Scenario names {seen[key]!r} and {sc.name!r} clash (same file/path name); "
                             "make them differ in letters or digits.")
        seen[key] = sc.name

    formats = output.get("formats", ["csv"])
    formats = [formats] if isinstance(formats, str) else list(formats or [])
    formats = [str(f).strip().lower().lstrip(".") for f in formats]
    formats = ["parquet" if f == "pq" else f for f in formats]
    bad = [f for f in formats if f not in FORMATS]
    if bad or not formats:
        raise ValueError(f"output.formats must list some of {', '.join(FORMATS)}, got {output.get('formats')!r}.")
    out_text = str(output.get("dir") or "outputs/{run_name}")
    try:
        out_text = out_text.format(run_name=slug(run_name))
    except (KeyError, IndexError, ValueError):
        raise ValueError("output.dir may only use the {run_name} placeholder.") from None
    # resolve() folds "configs/../outputs" so deep folders stay under Windows' path limit
    out_dir = (Path(out_text) if Path(out_text).is_absolute() else base / out_text).resolve()

    return RunConfig(
        run_name=run_name, solve_from=solve_from, solve_to=solve_to, indicators=indicators, groups=groups,
        scenarios=scenarios, out_dir=out_dir, release=str(model.get("release") or "latest:5yr").strip(),
        root=str(model.get("root") or GEM_ROOT).strip(), output_folder=output_folder, max_parallel=max_parallel,
        resolve=resolve, poll_seconds=None if solve.get("poll_seconds") is None
        else _number(solve["poll_seconds"], "solve.poll_seconds", 10.0),
        timeout_seconds=_number(solve.get("timeout_seconds"), "solve.timeout_seconds", 3600.0),
        fetch_from=fetch_from, fetch_to=fetch_to, annual_fallback=bool(fetch.get("annual_fallback", True)),
        formats=list(dict.fromkeys(formats)), description=str(d.get("description") or ""),
        source=Path(source) if source is not None else None,
    )


def load_config(path_or_dict, *, base_dir=None) -> RunConfig:
    """Load and validate a run config from a .yaml/.yml/.json file (or a dict).

    Relative paths in a file resolve against the file's folder; for a dict, against
    base_dir (default: the current folder). Raises ValueError with what to fix.
    """
    if isinstance(path_or_dict, Mapping):
        return config_from_dict(path_or_dict, base_dir=base_dir)
    path = Path(path_or_dict)
    if not path.is_file():
        raise ValueError(f"Run config {path} not found.")
    data = read_structured(path)
    try:
        return config_from_dict(data, base_dir=base_dir or path.resolve().parent, source=path)
    except ValueError as exc:
        raise ValueError(f"{path}: {exc}") from None
