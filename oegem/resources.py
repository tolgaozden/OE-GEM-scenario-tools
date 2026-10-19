"""Release tree and workspace: list and resolve model releases; create, move, archive
and delete folders and forecasts.

Release names look like ``MonYY[_n] <horizon>`` (e.g. "Sep26_2 5yr"); older ones sit
under a "Previous releases" folder. The tree is walked, never assumed to have a fixed
depth. In the workspace, deleting is allowed in your own area (``/me``); the API
refuses to delete shared resources unless they sit in an archive or temporary folder,
so shared items are archived (moved into ``<shared root>/$Archive``) instead. Test a
solve into ``/me`` before writing anywhere shared.
"""
from __future__ import annotations

import difflib
import logging
import re
from typing import List, Optional, Tuple
from urllib.parse import quote

import pandas as pd

from .client import OEError, quote_path

log = logging.getLogger("oegem")

GEM_ROOT = "oxford-economics/releases/Global Economic Model"
DIRECTORY_TYPES = ("directory", "folder", "dir")
WALK_COLUMNS = ["name", "path", "type", "id", "depth", "parent"]
RELEASE_COLUMNS = ["name", "path", "id", "horizon", "vintage", "is_previous"]
_CHILD_KEYS = ("Children", "Items", "Resources")
_MONTHS = {name: i for i, names in enumerate(
    [("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",), ("jun", "june"),
     ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"), ("oct", "october"),
     ("nov", "november"), ("dec", "december")], start=1) for name in names}
_RELEASE_RE = re.compile(r"^\s*([A-Za-z]+)(\d{2})(?:_(\d+))?(?=\s|$)")
_HORIZON_RE = re.compile(r"(\d+)\s*yr\b", re.IGNORECASE)
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _clean(path) -> str:
    text = str(path or "").strip()
    if not text.strip("/"):
        raise ValueError("Empty path: give a folder or forecast path such as /me/oegem-runs.")
    return text.rstrip("/")


def _is_dir(item: dict) -> bool:
    kind = str(item.get("Type") or item.get("ResourceType") or "").lower()
    if kind:
        return kind in DIRECTORY_TYPES
    return isinstance(item.get("Children"), list)


def _in_user_area(path) -> bool:
    return str(path).strip().strip("/").split("/")[0].lower() == "me"


def list_children(client, path) -> List[dict]:
    """Children of a folder as dicts with at least Name, Path, Type and Id.

    Tolerates payloads that list children under Children, Items or Resources; a child
    without a Path gets "<parent path>/<name>".
    """
    res = client.resource(path)
    if not isinstance(res, dict):
        return []
    kids = next((res[k] for k in _CHILD_KEYS if isinstance(res.get(k), list)), [])
    base = str(res.get("Path") or path).rstrip("/")
    out = []
    for child in kids:
        if not isinstance(child, dict):
            continue
        item = dict(child)
        item["Name"] = str(child.get("Name") or "")
        item["Path"] = str(child.get("Path") or f"{base}/{item['Name']}")
        item["Type"] = str(child.get("Type") or child.get("ResourceType") or ("Directory" if _is_dir(child) else ""))
        item["Id"] = child.get("Id")
        out.append(item)
    return out


def walk(client, path, max_depth: int = 4) -> pd.DataFrame:
    """Breadth-first listing of everything below path, down to max_depth levels.

    Returns a DataFrame with columns name, path, type, id, depth (1 = direct child) and
    parent. Sub-folders that cannot be read are skipped with a warning.
    """
    rows = []
    queue: List[Tuple[str, int]] = [(str(path), 0)]
    while queue:
        current, depth = queue.pop(0)
        try:
            children = list_children(client, current)
        except OEError as exc:
            if depth == 0:
                raise
            log.warning("skipping %s: %s", current, exc)
            continue
        for child in children:
            rows.append({"name": child["Name"], "path": child["Path"], "type": child["Type"],
                         "id": child["Id"], "depth": depth + 1, "parent": current})
            if _is_dir(child) and depth + 1 < max_depth:
                queue.append((child["Path"], depth + 1))
    return pd.DataFrame(rows, columns=WALK_COLUMNS)


def release_sort_key(name) -> Optional[Tuple[int, int, int]]:
    """(year, month, n) from a release name, e.g. "Sep26_2 5yr" -> (2026, 9, 2); None if undated.

    A missing "_n" counts as 0. A non-month prefix (such as "Demo") counts as month 0.
    """
    m = _RELEASE_RE.match(str(name or ""))
    if not m:
        return None
    month = _MONTHS.get(m.group(1).lower(), 0)
    return 2000 + int(m.group(2)), month, int(m.group(3) or 0)


def _vintage(key) -> Optional[str]:
    """ "YYYY-MM-n" from a release_sort_key; "YYYY-x-n" when the prefix is not a month; None if undated."""
    if key is None:
        return None
    month = f"{key[1]:02d}" if key[1] else "x"
    return f"{key[0]}-{month}-{key[2]}"


def _horizon(name) -> str:
    m = _HORIZON_RE.search(str(name or ""))
    return f"{int(m.group(1))}yr" if m else ""


def list_releases(client, root: str = GEM_ROOT, max_depth: int = 4) -> pd.DataFrame:
    """Forecast-like leaves (non-folders) below root, newest first.

    Columns: name, path, id, horizon ("5yr", "25yr" or ""), vintage ("YYYY-MM-n"; "YYYY-x-n"
    when the name's prefix is not a month; None if the name is not dated) and is_previous
    (under a "Previous releases" folder).
    Ties are ordered current before previous, then shorter horizon first.
    """
    tree = walk(client, root, max_depth=max_depth)
    rows = []
    for r in tree.itertuples(index=False):
        if str(r.type).lower() in DIRECTORY_TYPES:
            continue
        key = release_sort_key(r.name)
        rows.append({
            "name": r.name, "path": r.path, "id": r.id, "horizon": _horizon(r.name),
            "vintage": _vintage(key),
            "is_previous": any(seg.lower().startswith("previous") for seg in str(r.path).split("/")),
            "_k": -1 if key is None else key[0] * 10000 + key[1] * 100 + min(key[2], 99),
            "_h": int(_horizon(r.name)[:-2]) if _horizon(r.name) else 9999,
        })
    if not rows:
        return pd.DataFrame(columns=RELEASE_COLUMNS)
    df = pd.DataFrame(rows).sort_values(["_k", "is_previous", "_h", "name"], ascending=[False, True, True, True])
    return df[RELEASE_COLUMNS].reset_index(drop=True)


def _norm_name(x) -> str:
    return re.sub(r"\s+", " ", str(x)).strip().lower()


def resolve_release(client, spec, root: str = GEM_ROOT) -> dict:
    """Find a release (or any forecast) and return its resource dict (Id, Name, Path, ...).

    spec may be: "latest", "latest:5yr" or "latest:25yr" (newest dated release, optionally of
    one horizon); a bare release name searched in the tree ("Sep26_2 5yr"); a path relative
    to root ("Extension/Sep26_2 5yr"); a full path starting with "oxford-economics/" or "/";
    a workspace path ("/me/..."); or a forecast id (UUID), looked up when the API allows and
    otherwise returned as {"Id": spec}.
    """
    s = str(spec or "").strip()
    if not s:
        raise ValueError("Empty release spec: use 'latest', 'latest:5yr', a release name, a path or a forecast id.")
    low = s.lower()
    if low == "latest" or low.startswith("latest:"):
        horizon = s.split(":", 1)[1].strip().lower() if ":" in s else ""
        rel = list_releases(client, root)
        dated = rel[rel["vintage"].notna()]
        if horizon:
            dated = dated[dated["horizon"].str.lower() == horizon]
        if dated.empty:
            horizons = sorted({h for h in rel["horizon"] if h})
            raise ValueError(f"No dated release matches {s!r} under {root}. Horizons found: "
                             f"{', '.join(horizons) or 'none'}. Run `oegem releases` to list releases.")
        best = dated.iloc[0]
        others = [n for n in dated.loc[dated["vintage"] == best["vintage"], "name"] if n != best["name"]]
        if others:
            log.info("%s: also released in the same round: %s (pick one with latest:<horizon> or its name)",
                     s, ", ".join(others))
        res = client.resource(best["path"])
    elif _UUID_RE.match(s):
        try:
            res = client.get(f"/v1/forecast-contents/{quote(s, safe='')}")
        except OEError as exc:
            if exc.status is None or exc.status >= 500:
                raise
            log.warning("could not look up forecast id %s (HTTP %s); using the id as given", s, exc.status)
            res = None
        if not isinstance(res, dict):
            res = {"Id": s, "Name": s, "Path": None}
        res.setdefault("Id", s)
    elif s.startswith("/") or low.startswith("oxford-economics/") or low == "me" or low.startswith("me/"):
        res = client.resource(s)
    elif "/" in s:
        res = client.resource(f"{root.rstrip('/')}/{s}")
    else:
        rel = list_releases(client, root)
        hits = rel[rel["name"].map(_norm_name) == _norm_name(s)]
        if hits.empty:
            close = difflib.get_close_matches(s, list(rel["name"]), n=3)
            hint = f" Did you mean: {', '.join(close)}?" if close else ""
            raise ValueError(f"Release {s!r} not found under {root}.{hint} Run `oegem releases` to list names, "
                             "or pass 'latest', a full path or a forecast id.")
        res = client.resource(hits.iloc[0]["path"])
    log.info("release %r -> %s [%s]", s, res.get("Path") or res.get("Name"), res.get("Id"))
    return res


def _try_resource(client, path) -> Optional[dict]:
    try:
        return client.resource(path)
    except OEError as exc:
        if exc.status in (404, 410):
            return None
        raise


def exists(client, path) -> bool:
    """True if a resource exists at path (HTTP 404/410 mean no; other errors are raised)."""
    return _try_resource(client, path) is not None


def _create_folder(client, path: str) -> dict:
    name = path.rstrip("/").split("/")[-1]
    resp = client.put(f"/v1/resources/{quote_path(path)}",
                      json={"Name": name, "ResourceType": "Directory", "Type": "Directory"})
    log.info("created folder %s", path)
    return resp if isinstance(resp, dict) and resp else client.resource(path)


def make_folder(client, path, exist_ok: bool = True) -> dict:
    """Create one folder (its parent must exist) and return its resource dict.

    With exist_ok, an existing folder is returned unchanged; otherwise ValueError.
    """
    p = _clean(path)
    found = _try_resource(client, p)
    if found is not None:
        if exist_ok:
            return found
        raise ValueError(f"{p} already exists; pass exist_ok=True to reuse it.")
    return _create_folder(client, p)


def ensure_folder_tree(client, path) -> None:
    """Create path and any missing parents. The top-level root (e.g. /me) is never created."""
    segments = [seg for seg in _clean(path).split("/") if seg]
    lead = "/" if str(path).strip().startswith("/") else ""
    missing = False
    for i in range(2, len(segments) + 1):
        sub = lead + "/".join(segments[:i])
        if not missing and exists(client, sub):
            continue
        missing = True
        _create_folder(client, sub)


def move(client, path, new_parent) -> dict:
    """Move a folder or forecast into new_parent and return the moved resource dict."""
    p, parent = _clean(path), _clean(new_parent)
    resp = client.patch(f"/v1/resources/{quote_path(p)}", json={"Directory": parent})
    log.info("moved %s -> %s", p, parent)
    if isinstance(resp, dict) and resp:
        return resp
    return client.resource(f"{parent}/{p.split('/')[-1]}")


def archive(client, path, archive_folder) -> dict:
    """Move path into archive_folder (usually "<shared root>/$Archive") and return it.

    Use this for shared items, which the API will not delete directly.
    """
    folder = _clean(archive_folder)
    if not exists(client, folder):
        raise ValueError(f"Archive folder {folder} not found. Shared areas usually have one at "
                         "'<shared root>/$Archive'; create it with make_folder() if you have the rights.")
    return move(client, path, folder)


def delete(client, path, *, confirm: bool = False) -> None:
    """Delete a folder or forecast. confirm must be True; deletion cannot be undone.

    Raises OEError with an explanation when the API refuses because the item is shared.
    """
    p = _clean(path)
    if not confirm:
        raise ValueError(f"Refusing to delete {p} without confirm=True (CLI: --yes). Deletion cannot be undone.")
    if quote_path(p).lower() == "me":
        raise ValueError("Refusing to delete the workspace root /me.")
    try:
        client.delete(f"/v1/resources/{quote_path(p)}")
    except OEError as exc:
        if exc.status in (400, 403, 405, 409) and not _in_user_area(p):
            raise OEError(
                f"{exc} -- The API refuses to delete shared resources unless they sit in an archive or "
                "temporary folder. Move the item with archive(client, path, '<shared root>/$Archive') "
                "(CLI: oegem workspace archive) instead.",
                status=exc.status, url=exc.url, body=exc.body) from None
        raise
    log.info("deleted %s", p)


def list_forecasts(client, path="/me", max_depth: int = 3) -> pd.DataFrame:
    """Forecasts (non-folders) below path, sorted by path; columns as walk()."""
    tree = walk(client, path, max_depth=max_depth)
    leaves = tree[~tree["type"].astype(str).str.lower().isin(DIRECTORY_TYPES)]
    return leaves.sort_values("path").reset_index(drop=True)
