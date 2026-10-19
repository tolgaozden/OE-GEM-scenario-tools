"""Submit a scenario solve and wait for it.

A solve is ``POST /v1/operations/solve`` with the input forecast path, the solution
range, the command text and a NEW output forecast path. The call returns an operation
that is polled (long poll ``/await``, falling back to ``GET /v1/operations/<id>``) until
its status leaves Queued/InProgress. On success the new forecast's id is read from its
resource path. Solves usually take a minute or two.

The submit is sent exactly once (no automatic retry): a retried POST could start a
second, duplicate solve. A solve that the model reports as failed is returned as a
`SolveResult` with the status and failure text, not raised. `OEError` is raised when the
submit is rejected, or when contact with a submitted operation is lost; the operation
may then still be running, so check it (or the output path) before resubmitting.

Lower-level pieces (`submit`, `poll`, `finish`) let the batch runner keep several
solves in flight without threads.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Tuple
from urllib.parse import quote

from .client import OEError
from .periods import parse_range
from .scenario import Command, Scenario

log = logging.getLogger("oegem")

SOLVE_PATH = "/v1/operations/solve"
PENDING_STATUSES = ("queued", "inprogress", "running", "pending", "notstarted")
SUCCEEDED = "Succeeded"
_FAILURE_KEYS = ("FailureReason", "Error", "Message", "ErrorMessage")


@dataclass
class SolveResult:
    """Outcome of one solve.

    status is the final operation status ("Succeeded", "Failed", ...; still "Queued" or
    "InProgress" after a timeout, "Error" when the runner could not submit or lost
    contact). forecast_id is set on success. seconds counts from submit; failure holds
    the reason text when the solve did not succeed; submitted_at is UTC ISO time.
    """

    name: str
    status: str
    operation_id: Optional[str] = None
    output_path: str = ""
    forecast_id: Optional[str] = None
    seconds: Optional[float] = None
    failure: str = ""
    submitted_at: str = ""

    @property
    def ok(self) -> bool:
        """True if the solve succeeded."""
        return self.status == SUCCEEDED

    def to_dict(self) -> dict:
        """Plain dict of the fields."""
        return asdict(self)


@dataclass
class SolveJob:
    """A submitted solve that is being polled (see submit/poll/finish)."""

    name: str
    operation_id: str
    output_path: str
    submitted_at: str
    commands_text: str
    started: float
    status: str = "Queued"
    last: Any = None
    use_await: bool = True

    @property
    def pending(self) -> bool:
        """True while the operation is queued or running."""
        return is_pending(self.status)

    def elapsed(self) -> float:
        """Seconds since submit."""
        return time.monotonic() - self.started


def is_pending(status) -> bool:
    """True for Queued/InProgress (and similar) operation statuses."""
    return str(status or "").replace(" ", "").lower() in PENDING_STATUSES


def slug(name) -> str:
    """File- and path-safe form of a name: runs of other characters become '_'."""
    out = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(name or "").strip())
    return out or "scenario"


def utc_now() -> str:
    """Current UTC time as ISO text ("2026-10-16T09:30:00Z")."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def default_output_path(folder, name, when: Optional[datetime] = None) -> str:
    """f"{folder}/{slug(name)}-{YYYYmmdd-HHMMSS}" (local time): a fresh output forecast path.

    The API refuses an output path that already exists, hence the timestamp.
    """
    base = str(folder or "").strip().rstrip("/")
    if not base:
        raise ValueError("Give an output folder for solves, e.g. /me or /me/oegem-runs.")
    when = when or datetime.now()
    return f"{base}/{slug(name)}-{when:%Y%m%d-%H%M%S}"


def _prepare(scenario_or_commands, name: Optional[str]) -> Scenario:
    """Turn a Scenario, Command list, command text or a .3fs path into a Scenario."""
    x = scenario_or_commands
    if isinstance(x, Scenario):
        sc = x
    elif isinstance(x, Command):
        sc = Scenario(name or "commands", commands=[x])
    elif isinstance(x, Path) or (isinstance(x, str) and "\n" not in x and x.strip().lower().endswith(".3fs")):
        sc = Scenario.from_3fs(x, name=name)
    elif isinstance(x, str):
        sc = Scenario.from_text(x, name=name or "commands")
    elif isinstance(x, (list, tuple)):
        sc = Scenario(name or "commands").add(*x)
    else:
        raise ValueError("Pass a Scenario, a list of Command objects or lines, command text, or a .3fs path.")
    if not sc.commands:
        raise ValueError(f"No commands to solve in {sc.name!r}: the command list is empty after removing comments.")
    return sc


def _solve_range(sc: Scenario, solve_from, solve_to) -> Tuple[str, str]:
    lo = solve_from if solve_from is not None else sc.solve_from
    hi = solve_to if solve_to is not None else sc.solve_to
    if lo is None or hi is None:
        raise ValueError("Give solve_from and solve_to (e.g. '2026Q3' and '2031Q4'), or set them on the scenario.")
    return parse_range((lo, hi))


def _input_path(input_forecast) -> str:
    if isinstance(input_forecast, dict):
        path = input_forecast.get("Path")
        if not path:
            raise ValueError("The input forecast has no Path (an id alone is not enough to solve): "
                             "resolve it with resolve_release() from a name or path.")
        return str(path)
    text = str(input_forecast or "").strip()
    if not text:
        raise ValueError("Give the input forecast path (a release or forecast path).")
    return text


def _field(payload, *keys) -> Optional[str]:
    if isinstance(payload, dict):
        for k in keys:
            v = payload.get(k)
            if v not in (None, ""):
                return str(v)
    return None


def failure_text(op) -> str:
    """Reason text from an operation payload (FailureReason, Error, Message ...)."""
    if isinstance(op, dict):
        for key in _FAILURE_KEYS:
            v = op.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
            if v not in (None, "", [], {}):
                return json.dumps(v)[:800]
    return "no reason given"


def submit(client, input_forecast_path, scenario_or_commands, *, solve_from=None, solve_to=None,
           output_path=None, output_folder="/me", name=None) -> SolveJob:
    """Send one solve request (never retried) and return the SolveJob to poll.

    Args: input_forecast_path is a release/forecast path (or its resource dict);
    scenario_or_commands a Scenario, command lines/text or a .3fs path; the solve range
    defaults to the scenario's own; output_path defaults to default_output_path(output_folder, name).
    Raises ValueError for bad input and OEError if the API rejects the request.
    """
    sc = _prepare(scenario_or_commands, name)
    lo, hi = _solve_range(sc, solve_from, solve_to)
    out = str(output_path) if output_path else default_output_path(output_folder, sc.name)
    text = sc.commands_text()
    body = {"InputForecast": _input_path(input_forecast_path), "SolutionRange": {"From": lo, "To": hi},
            "Commands": text, "OutputForecast": out}
    submitted = utc_now()
    op = client.request("POST", SOLVE_PATH, json=body, retries=0)
    op_id = _field(op, "Id", "OperationId", "id")
    if not op_id:
        raise OEError(f"The solve request for {sc.name!r} returned no operation id; nothing to wait for.",
                      body=json.dumps(op)[:800] if op is not None else "")
    log.info("solve %r submitted: %d command(s), %s:%s -> %s (operation %s)",
             sc.name, len(sc.commands), lo, hi, out, op_id)
    return SolveJob(sc.name, op_id, out, submitted, text, time.monotonic(),
                    status=_field(op, "Status") or "Queued", last=op)


def poll(client, job: SolveJob, *, wait: bool = True) -> str:
    """Check a submitted operation once and return its status.

    wait=True uses the long poll (/await) and falls back to plain GET for good if the
    long poll fails; wait=False uses plain GET. Raises OEError if the operation cannot
    be read (the solve may still be running).
    """
    base = f"/v1/operations/{quote(job.operation_id, safe='')}"
    try:
        if wait and job.use_await:
            try:
                op = client.get(base + "/await")
            except OEError as exc:
                log.info("long poll unavailable for operation %s (%s); polling instead", job.operation_id, exc)
                job.use_await = False
                op = client.get(base)
        else:
            op = client.get(base)
    except OEError as exc:
        raise OEError(f"Lost contact with solve {job.name!r} (operation {job.operation_id}, output "
                      f"{job.output_path}); it may still be running, so check it before resubmitting: {exc}",
                      status=exc.status, url=exc.url, body=exc.body) from None
    if isinstance(op, dict):
        job.last = op
        job.status = _field(op, "Status") or job.status
    return job.status


def finish(client, job: SolveJob) -> SolveResult:
    """SolveResult for a job that ended (or is given up on); reads the new forecast id on success."""
    seconds = round(job.elapsed(), 3)
    if str(job.status).lower() == SUCCEEDED.lower():
        res = client.resource(job.output_path)
        fid = _field(res, "Id", "id")
        log.info("solve %r succeeded in %.0f s -> %s", job.name, seconds, job.output_path)
        return SolveResult(job.name, SUCCEEDED, job.operation_id, job.output_path, fid, seconds, "",
                           job.submitted_at)
    if job.pending:
        failure = (f"Still {job.status} after {seconds:.0f} s; check operation {job.operation_id} "
                   f"(output {job.output_path}) later.")
    else:
        failure = failure_text(job.last)
    log.warning("solve %r ended with status %s: %s", job.name, job.status, failure)
    return SolveResult(job.name, str(job.status), job.operation_id, job.output_path, None, seconds, failure,
                       job.submitted_at)


def solve(client, input_forecast_path, scenario_or_commands, *, solve_from=None, solve_to=None,
          output_path=None, output_folder="/me", poll_seconds: Optional[float] = None,
          timeout_seconds: float = 3600, name=None) -> SolveResult:
    """Submit one solve, wait for it, and return a SolveResult.

    Args: see submit(); poll_seconds is the pause between status checks when the long
    poll answers at once or is unavailable (default 10, or 0 with the demo client; 0 never
    sleeps); timeout_seconds is how long to wait before returning the still-pending status.
    A failed solve comes back as a result with status and failure text. Raises ValueError
    for bad input and OEError if the submit is rejected or contact with the operation is lost.
    """
    if poll_seconds is None:
        poll_seconds = 0 if getattr(client, "is_demo", False) else 10
    job = submit(client, input_forecast_path, scenario_or_commands, solve_from=solve_from, solve_to=solve_to,
                 output_path=output_path, output_folder=output_folder, name=name)
    while job.pending and job.elapsed() < timeout_seconds:
        t0 = time.monotonic()
        if not job.use_await and poll_seconds > 0:
            time.sleep(poll_seconds)
        poll(client, job, wait=True)
        if job.pending and job.use_await and poll_seconds > 0 and time.monotonic() - t0 < 2:
            time.sleep(poll_seconds)  # the long poll answered at once: do not spin
    return finish(client, job)
