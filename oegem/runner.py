"""Batch runner: solve the scenarios of a run config, fetch the results, write a manifest.

`run()` goes through these steps:

1. resolve the release (`model.release`);
2. build and check every scenario and write it to ``<out>/scenarios/<name>.3fs``
   (with ``solve.resolve: levels`` the pct/abs/ratio shocks are first turned into SET
   levels from the release's own values);
3. ``dry_run=True`` stops here and returns the plan, without any solve request;
4. create the workspace folder ``<solve.output_folder>/<run_name>``;
5. solve the scenarios, up to ``solve.max_parallel`` at a time (no threads: in-flight
   operations are polled in turn). With ``resume=True`` a scenario that an earlier run
   in the same output folder solved with the same commands, release and solve range is
   not solved again; its forecast is reused. Scenarios left out by ``only`` keep their
   earlier manifest entries (with or without resume). A failed scenario is recorded and
   the run goes on. When the API answers HTTP 409 because the output path already
   exists (e.g. the same scenario solved twice within one second), the submit is retried
   as ``<path>-2`` and ``<path>-3``;
6. check that the forecasts of scenarios kept from an earlier manifest still exist; one
   that does not is marked "Missing" (with the reason) and left out of the results,
   instead of failing the whole fetch;
7. fetch the baseline and every succeeded scenario and write ``<out>/results.<fmt>``
   (long frame; forecast labels "baseline" and the scenario names) and
   ``<out>/manifest.json``;
8. fetch the variable metadata of the fetched pairs from the baseline (units, scaling,
   history end, annualisation type, base years; contact fields dropped) and write
   ``<out>/metadata.csv``. This step is best effort: a failure logs a warning and the
   run still succeeds.

The manifest records the package version, run name, timestamps, the release (name,
path, id), the solve and fetch settings, the files written ("outputs"), the metadata
file ("metadata", None when it could not be fetched) and per scenario its status, output
path, forecast id, seconds, number of commands, SHA-256 of the command text and any
failure text. It never contains the API token. The MATLAB runner writes the same keys
(without "metadata"), and `load_run()` reads either.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote

import pandas as pd

from .catalogue import groups as catalogue_groups
from .catalogue import indicators as catalogue_indicators
from .client import OEClient, OEError
from .config import RunConfig, load_config
from .data import empty_frame, fetch, fetch_many, load, save
from .metadata import METADATA_FILE, load_metadata, save_metadata
from .metadata import metadata as fetch_metadata
from .resources import ensure_folder_tree, exists, resolve_release
from .scenario import Scenario, level_targets, resolve_levels
from .solve import SolveJob, SolveResult, default_output_path, finish, poll, slug, submit, utc_now

log = logging.getLogger("oegem")

MANIFEST_NAME = "manifest.json"
RESULT_EXT = {"csv": ".csv", "xlsx": ".xlsx", "parquet": ".parquet"}
RESULT_FILES = ("results.csv", "results.parquet", "results.pq", "results.xlsx")
SUCCEEDED = "Succeeded"
NOT_RUN = "NotRun"
MISSING = "Missing"
SUBMIT_TRIES = 3          # the output path, then <path>-2 and <path>-3 after HTTP 409 (path exists)
ENTRY_KEYS = ("name", "description", "status", "operation_id", "output_path", "forecast_id", "seconds",
              "n_commands", "sha256", "failure", "solve_from", "solve_to", "file", "submitted_at",
              "resumed", "warnings")


@dataclass
class RunResult:
    """What run() and load_run() return.

    results is the long frame (baseline + succeeded scenarios; empty for a dry run),
    manifest the manifest dict (for a dry run: the plan, with "dry_run": true),
    out_dir the run's output folder, failed the names of scenarios that did not succeed
    (including "Missing" ones) and metadata the variable metadata table of the fetched
    pairs (metadata.csv; None when absent).
    """

    results: pd.DataFrame
    manifest: Dict[str, Any]
    out_dir: Path
    failed: List[str] = field(default_factory=list)
    metadata: Optional[pd.DataFrame] = None

    @property
    def scenarios(self) -> List[Dict[str, Any]]:
        """Per-scenario manifest entries."""
        return list(self.manifest.get("scenarios") or [])

    @property
    def succeeded(self) -> List[str]:
        """Names of the scenarios that solved."""
        return [e.get("name") for e in self.scenarios if e.get("status") == SUCCEEDED]

    @property
    def dry_run(self) -> bool:
        """True for the plan returned by run(..., dry_run=True)."""
        return bool(self.manifest.get("dry_run"))

    def forecast_ids(self) -> Dict[str, str]:
        """Label -> forecast id: "baseline" (the release) and each succeeded scenario."""
        out = {}
        rel = (self.manifest.get("release") or {}).get("id")
        if rel:
            out["baseline"] = rel
        for e in self.scenarios:
            if e.get("status") == SUCCEEDED and e.get("forecast_id"):
                out[e["name"]] = e["forecast_id"]
        return out


def _entry(**kw) -> Dict[str, Any]:
    out: Dict[str, Any] = {k: None for k in ENTRY_KEYS}
    out.update(failure="", resumed=False, warnings=[])
    out.update(kw)
    return out


def _select(cfg: RunConfig, only) -> List[Scenario]:
    if only is None:
        return list(cfg.scenarios)
    names = [n.strip() for n in (only.split(",") if isinstance(only, str) else only) if str(n).strip()]
    unknown = [n for n in names if n not in cfg.scenario_names]
    if unknown:
        raise ValueError(f"only: unknown scenario(s) {', '.join(unknown)}; the config has "
                         f"{', '.join(cfg.scenario_names)}.")
    return [sc for sc in cfg.scenarios if sc.name in names]


def _read_manifest(out_dir: Path) -> Optional[dict]:
    path = Path(out_dir) / MANIFEST_NAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        log.warning("ignoring unreadable %s: %s", path, exc)
        return None
    return normalise_manifest(data) if isinstance(data, dict) else None


def normalise_manifest(m: Dict[str, Any]) -> Dict[str, Any]:
    """Fill the standard keys of a manifest written by this package or the MATLAB runner.

    MATLAB writes started_at (copied to created_at) and tool (package_version stays None
    unless present); every scenario entry gets all standard keys.
    """
    out = dict(m)
    out.setdefault("created_at", out.get("started_at"))
    out.setdefault("package_version", None)
    for key in ("release", "solve", "fetch"):
        if not isinstance(out.get(key), dict):
            out[key] = {}
    entries = out.get("scenarios") or []
    if isinstance(entries, dict):  # a single struct written as an object
        entries = [entries]
    out["scenarios"] = [_entry(**{k: v for k, v in e.items()}) for e in entries if isinstance(e, dict)]
    for e in out["scenarios"]:
        e["failure"] = e.get("failure") or ""
    return out


def _reusable(prev: Optional[dict], entry: Dict[str, Any], release_id) -> Optional[dict]:
    """The earlier manifest entry that can stand in for this scenario, if any."""
    if not prev or str((prev.get("release") or {}).get("id")) != str(release_id):
        return None
    run_solve = prev.get("solve") or {}
    for old in prev.get("scenarios") or []:
        if (old.get("name") == entry["name"] and old.get("status") == SUCCEEDED and old.get("forecast_id")
                and old.get("sha256") == entry["sha256"]
                and (old.get("solve_from") or run_solve.get("from"), old.get("solve_to") or run_solve.get("to"))
                == (entry["solve_from"], entry["solve_to"])):
            return old
    return None


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def _catalogue_codes(client, release_id) -> Tuple[Any, Any]:
    try:
        return catalogue_indicators(client, release_id), catalogue_groups(client, release_id)
    except (OEError, ValueError) as exc:
        log.warning("catalogue check skipped (%s)", exc)
        return None, None


def _resolve_to_levels(client, cfg: RunConfig, release_id, scenarios: List[Scenario]) -> List[Scenario]:
    targets = level_targets(scenarios)
    if not targets:
        return scenarios
    log.info("resolve: levels -> fetching input-forecast values for %d variable(s)", len(targets))
    frame = fetch(client, release_id, pairs=targets, annual_fallback=cfg.annual_fallback, label="baseline")
    baseline = {f"{ind}:{grp}": dict(zip(sub["period"], sub["value"]))
                for (ind, grp), sub in frame.groupby(["indicator", "group"])}
    return [resolve_levels(sc, baseline) for sc in scenarios]


def _submit(client, input_path: str, sc: Scenario, lo: str, hi: str, workspace: str) -> SolveJob:
    """Submit one solve; when the output path exists (HTTP 409) retry as <path>-2, then <path>-3."""
    base = default_output_path(workspace, sc.name)
    for attempt in range(1, SUBMIT_TRIES + 1):
        path = base if attempt == 1 else f"{base}-{attempt}"
        try:
            return submit(client, input_path, sc, solve_from=lo, solve_to=hi, output_path=path)
        except OEError as exc:
            if exc.status != 409:
                raise
            if attempt == SUBMIT_TRIES:
                raise OEError(f"{exc} (tried {SUBMIT_TRIES} output paths, {base} to {path}, all taken)",
                              status=exc.status, url=exc.url, body=exc.body) from None
            log.warning("solve %r: output path %s is taken (HTTP 409); retrying as %s-%d",
                        sc.name, path, base, attempt + 1)
    raise ValueError(f"no output path tried for {sc.name!r}")   # not reached: the loop returns or raises


def _solve_queue(client, cfg: RunConfig, todo: List[Tuple[Scenario, str, str]], input_path: str, workspace: str,
                 poll_seconds: float,
                 done: Callable[[str, Optional[SolveResult], str, Optional[SolveJob]], None]) -> None:
    """Keep up to max_parallel solves in flight and poll them in turn (no threads).

    One operation in flight is long-polled (/await); several are checked with plain GETs.
    The next scenario is submitted as soon as a slot frees up.
    """
    queue = list(todo)
    inflight: List[SolveJob] = []
    while queue or inflight:
        while queue and len(inflight) < cfg.max_parallel:
            sc, lo, hi = queue.pop(0)
            try:
                inflight.append(_submit(client, input_path, sc, lo, hi, workspace))
            except (OEError, ValueError) as exc:
                done(sc.name, None, f"Submit failed: {exc}", None)
        if not inflight:
            continue
        t0 = time.monotonic()
        wait = len(inflight) == 1
        for job in list(inflight):
            try:
                if job.pending and job.elapsed() < cfg.timeout_seconds:
                    poll(client, job, wait=wait)
                if job.pending and job.elapsed() < cfg.timeout_seconds:
                    continue
                result = finish(client, job)
            except OEError as exc:
                inflight.remove(job)
                done(job.name, None, str(exc), job)
                continue
            inflight.remove(job)
            done(job.name, result, "", job)
        if inflight and poll_seconds > 0 and time.monotonic() - t0 < 2:
            time.sleep(poll_seconds)


def _forecast_exists(client, entry: Dict[str, Any]) -> bool:
    """Does the forecast of a manifest entry still exist? Answers other than 404/410 count as yes."""
    path, fid = entry.get("output_path"), entry.get("forecast_id")
    try:
        if path:
            return exists(client, path)
        if fid:
            client.get(f"/v1/forecast-contents/{quote(str(fid), safe='')}")
            return True
    except OEError as exc:
        if exc.status in (404, 410):
            return False
        log.warning("could not check the forecast of scenario %s (%s); keeping it", entry.get("name"), exc)
        return True
    return False


def _check_kept(client, entries: Dict[str, Dict[str, Any]], names: Sequence[str]) -> None:
    """Mark kept entries whose forecast no longer exists as Missing, so the fetch leaves them out."""
    for name in names:
        e = entries[name]
        if e.get("status") != SUCCEEDED or _forecast_exists(client, e):
            continue
        where = e.get("output_path") or e.get("forecast_id") or "(none recorded)"
        e.update(status=MISSING, failure=(f"The forecast {where} solved by an earlier run no longer exists "
                                          "(deleted, moved, or another workspace or backend); solve the "
                                          f"scenario again with only={name!r} (CLI: --only {name})."))
        log.warning("scenario %s: %s", name, e["failure"])


def _write_metadata(client, release_id, results: pd.DataFrame,
                    out_dir: Path) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
    """Fetch the metadata of the fetched pairs from the release and write metadata.csv.

    Best effort: any failure logs a warning and returns (None, None); the run goes on.
    """
    if results is None or not len(results):
        return None, None
    pairs = list(dict.fromkeys(zip(results["indicator"].astype(str), results["group"].astype(str))))
    try:
        meta = fetch_metadata(client, release_id, pairs=pairs)
        save_metadata(meta, Path(out_dir) / METADATA_FILE)
    except Exception as exc:  # metadata is an extra: never fail a finished run over it
        log.warning("variable metadata not saved (%s); the results are complete without it", exc)
        return None, None
    log.info("metadata for %d pairs -> %s", len(meta), Path(out_dir) / METADATA_FILE)
    return meta, METADATA_FILE


def run(config_or_path, *, client=None, dry_run: bool = False, only=None, resume: bool = True) -> RunResult:
    """Run a batch of scenarios (see the module docstring for the steps).

    Args: config_or_path is a RunConfig, a config file path or a config dict; client an
    OEClient (default OEClient.from_env()); dry_run builds, checks and writes the .3fs
    files and returns the plan without solving; only limits the run to some scenario
    names (a list or "a,b"; other scenarios keep their earlier manifest entries, also with
    resume=False); resume lets the selected scenarios reuse forecasts already solved with
    the same commands, release and solve range.
    Returns a RunResult. Raises ValueError for config problems and OEError when the API
    fails outside a solve (release lookup, folders, fetching results). A metadata failure
    only logs a warning.
    """
    cfg = config_or_path if isinstance(config_or_path, RunConfig) else load_config(config_or_path)
    client = client if client is not None else OEClient.from_env()
    selected = _select(cfg, only)
    out_dir = Path(cfg.out_dir)
    created = utc_now()

    release = resolve_release(client, cfg.release, root=cfg.root)
    rel = {"name": release.get("Name"), "path": release.get("Path"), "id": release.get("Id")}
    if cfg.resolve == "levels":
        selected = _resolve_to_levels(client, cfg, rel["id"], selected)
    known_ind, known_grp = _catalogue_codes(client, rel["id"])
    workspace = f"{cfg.output_folder.rstrip('/')}/{slug(cfg.run_name)}"
    # Always read the earlier manifest: scenarios left out by `only` keep their entries.
    # `resume` only decides whether the selected scenarios may reuse earlier solves.
    previous = _read_manifest(out_dir)

    entries: Dict[str, Dict[str, Any]] = {}
    todo: List[Tuple[Scenario, str, str]] = []
    kept: List[str] = []        # entries taken from the earlier manifest: checked before the fetch
    for sc in selected:
        lo, hi = sc.solve_from or cfg.solve_from, sc.solve_to or cfg.solve_to
        warnings = sc.validate(indicators=known_ind, groups=known_grp)
        for w in warnings:
            log.warning("%s", w)
        rel_file = f"scenarios/{slug(sc.name)}.3fs"
        sc.to_3fs(out_dir / rel_file, notes=[f"release: {rel['name']}", f"solve range: {lo}:{hi}",
                                             f"resolve: {cfg.resolve}"])
        entry = _entry(name=sc.name, description=sc.description, status="Planned", n_commands=len(sc.commands),
                       sha256=sc.sha256(), solve_from=lo, solve_to=hi, file=rel_file, warnings=warnings)
        old = _reusable(previous, entry, rel["id"]) if resume else None
        if old is not None and (dry_run or not old.get("output_path") or exists(client, old["output_path"])):
            entry.update({k: old.get(k) for k in ("operation_id", "output_path", "forecast_id", "seconds",
                                                  "submitted_at")})
            entry.update(status=SUCCEEDED if not dry_run else "Reuse", resumed=True)
            if not old.get("output_path"):
                kept.append(sc.name)            # no path to check above: check the forecast id later
        else:
            todo.append((sc, lo, hi))
        entries[sc.name] = entry
    same_release = bool(previous) and str(previous["release"].get("id")) == str(rel["id"])
    for sc in cfg.scenarios:  # scenarios left out by `only` keep their earlier entry
        if sc.name not in entries:
            old = next((e for e in (previous or {}).get("scenarios", []) if e.get("name") == sc.name), None)
            if old and same_release:
                entries[sc.name] = dict(old)
                kept.append(sc.name)
            else:
                entries[sc.name] = _entry(name=sc.name, status=NOT_RUN)

    def manifest(finished: Optional[str], outputs: Sequence[str] = (), extra: Optional[dict] = None) -> Dict[str, Any]:
        from . import __version__

        m = {"package_version": __version__, "run_name": cfg.run_name, "created_at": created,
             "finished_at": finished, "release": rel,
             "solve": {"from": cfg.solve_from, "to": cfg.solve_to, "output_folder": workspace,
                       "max_parallel": cfg.max_parallel, "resolve": cfg.resolve},
             "fetch": {"indicators": cfg.indicators, "groups": cfg.groups, "from": cfg.fetch_from,
                       "to": cfg.fetch_to, "annual_fallback": cfg.annual_fallback},
             "outputs": list(outputs),
             "scenarios": [entries[sc.name] for sc in cfg.scenarios]}
        m.update(extra or {})
        if dry_run:
            m["dry_run"] = True
        return m

    if dry_run:
        log.info("dry run %s: %d scenario(s) to solve, %d reusable; commands in %s",
                 cfg.run_name, len(todo), len(selected) - len(todo), out_dir / "scenarios")
        return RunResult(empty_frame(), manifest(None), out_dir, failed=[])

    if not rel["path"] and todo:
        raise ValueError(f"Release {cfg.release!r} resolved to an id without a path; solves need a path. "
                         "Use a release name, 'latest:5yr' or a full path.")
    ensure_folder_tree(client, workspace)
    manifest_path = out_dir / MANIFEST_NAME

    def done(name: str, result: Optional[SolveResult], error: str, job: Optional[SolveJob]) -> None:
        e = entries[name]
        if result is not None:
            e.update(status=result.status, operation_id=result.operation_id, output_path=result.output_path,
                     forecast_id=result.forecast_id, seconds=result.seconds, failure=result.failure,
                     submitted_at=result.submitted_at)
        else:
            e.update(status="Error", failure=error, forecast_id=None,
                     operation_id=job.operation_id if job else None, output_path=job.output_path if job else None,
                     submitted_at=job.submitted_at if job else None,
                     seconds=round(job.elapsed(), 3) if job else None)
        log.info("scenario %s: %s%s", name, e["status"], f" ({e['failure']})" if e["failure"] else "")
        _write_json(manifest_path, manifest(None))  # progress survives an interrupted run

    poll_seconds = cfg.poll_seconds if cfg.poll_seconds is not None else (
        0.0 if getattr(client, "is_demo", False) else 10.0)
    _solve_queue(client, cfg, todo, rel["path"], workspace, poll_seconds, done)
    _check_kept(client, entries, kept)

    forecasts = {"baseline": rel["id"]}
    forecasts.update({e["name"]: e["forecast_id"] for e in (entries[sc.name] for sc in cfg.scenarios)
                      if e.get("status") == SUCCEEDED and e.get("forecast_id")})
    results = fetch_many(client, forecasts, cfg.indicators, cfg.groups, start=cfg.fetch_from, end=cfg.fetch_to,
                         annual_fallback=cfg.annual_fallback)
    outputs = []
    for fmt in cfg.formats:
        save(results, out_dir / f"results{RESULT_EXT[fmt]}")
        outputs.append(f"results{RESULT_EXT[fmt]}")
    meta, meta_file = _write_metadata(client, rel["id"], results, out_dir)
    if meta_file:
        outputs.append(meta_file)
    final = manifest(utc_now(), outputs, {"metadata": meta_file})
    _write_json(manifest_path, final)
    failed = [e["name"] for e in final["scenarios"] if e.get("status") not in (SUCCEEDED, NOT_RUN)]
    log.info("run %s: %d of %d scenario(s) succeeded; results in %s", cfg.run_name,
             len(forecasts) - 1, len(cfg.scenarios), out_dir)
    return RunResult(results, final, out_dir, failed=failed, metadata=meta)


def load_run(path) -> RunResult:
    """Reload a run folder written by run() or by the MATLAB runner.

    Args: path is the run's output folder (or a file inside it). Reads manifest.json,
    the first of results.csv / .parquet / .xlsx found and metadata.csv when present.
    Returns a RunResult whose failed lists the scenarios recorded as not succeeded and
    whose metadata is None without a metadata file. Raises ValueError if neither the
    manifest nor a results file exists.
    """
    p = Path(path)
    out_dir = p.parent if p.is_file() else p
    if not out_dir.is_dir():
        raise ValueError(f"Run folder {out_dir} not found.")
    manifest = _read_manifest(out_dir)
    result_file = next((out_dir / f for f in RESULT_FILES if (out_dir / f).is_file()), None)
    if manifest is None and result_file is None:
        raise ValueError(f"{out_dir} has neither {MANIFEST_NAME} nor a results file; is it a run folder?")
    results = load(result_file) if result_file is not None else empty_frame()
    manifest = manifest if manifest is not None else normalise_manifest({})
    failed = [e["name"] for e in manifest["scenarios"] if e.get("status") not in (SUCCEEDED, NOT_RUN)]
    meta = None
    meta_name = manifest.get("metadata") if "metadata" in manifest else METADATA_FILE
    if meta_name and (out_dir / str(meta_name)).is_file():
        try:
            meta = load_metadata(out_dir / str(meta_name))
        except (OSError, ValueError) as exc:
            log.warning("ignoring unreadable %s: %s", out_dir / str(meta_name), exc)
    return RunResult(results, manifest, out_dir, failed=failed, metadata=meta)
