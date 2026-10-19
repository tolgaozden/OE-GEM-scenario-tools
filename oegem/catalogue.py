"""Model catalogue: indicators (mnemonics) and groups (economies, regions), search, a
shock-variable finder, and a cached wrapper.

Catalogues are licensed model content. The cache (default ``.oegem_cache``) belongs
on your machine only: keep it out of version control.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Union
from urllib.parse import quote

import pandas as pd

from .client import as_records

log = logging.getLogger("oegem")

SHOCK_PATTERN = r"shock|residual|add[\s_-]*factor|dummy"
_ALIASES = {"code": ("code", "indicator_code", "group_code", "mnemonic"), "name": ("name", "description", "title")}


def _snake(key) -> str:
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(key)).replace(" ", "_").lower()


def _frame(records: List[dict], first: Sequence[str]) -> pd.DataFrame:
    rows = []
    for rec in records:
        row = {}
        for key, value in rec.items():
            if value is None or isinstance(value, (str, int, float, bool)):
                row[_snake(key)] = value
        for target, aliases in _ALIASES.items():
            if target not in row:
                alias = next((a for a in aliases if a in row), None)
                if alias is not None:
                    row[target] = row.pop(alias)
        rows.append(row)
    df = pd.DataFrame(rows)
    for col in first:
        if col not in df.columns:
            df[col] = ""
    df = df[list(first) + [c for c in df.columns if c not in first]]
    df["code"] = df["code"].astype(str)
    return df.drop_duplicates("code").reset_index(drop=True)


def indicators(client, forecast_id) -> pd.DataFrame:
    """Indicator catalogue of a forecast: columns code, name, then any extra scalar fields."""
    payload = client.get(f"/v1/forecast-contents/{quote(str(forecast_id), safe='')}/indicators")
    return _frame(as_records(payload), ("code", "name"))


def groups(client, forecast_id) -> pd.DataFrame:
    """Group catalogue of a forecast: columns code, name, type, then any extra scalar fields."""
    payload = client.get(f"/v1/forecast-contents/{quote(str(forecast_id), safe='')}/groups")
    return _frame(as_records(payload), ("code", "name", "type"))


def search(df: pd.DataFrame, pattern: str, *, fields: Union[str, Iterable[str]] = ("code", "name"),
           regex: bool = True, case: bool = False) -> pd.DataFrame:
    """Rows of a catalogue frame where any of fields contains pattern.

    Args: pattern is a regular expression (regex=True) or a plain substring; case=False
    ignores case. Returns the matching rows with a fresh index.
    """
    wanted = [fields] if isinstance(fields, str) else list(fields)
    cols = [f for f in wanted if f in df.columns]
    if not cols:
        raise ValueError(f"None of the fields {wanted} are columns of the frame (columns: {list(df.columns)}).")
    if regex:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"Invalid regular expression {pattern!r}: {exc}. "
                             "Pass regex=False for a plain substring search.") from None
    mask = pd.Series(False, index=df.index)
    for col in cols:
        mask |= df[col].astype(str).str.contains(pattern, case=case, regex=regex, na=False)
    return df[mask].reset_index(drop=True)


def shock_variables(indicators_df: pd.DataFrame) -> pd.DataFrame:
    """Indicators whose code or name mentions shock, residual, add factor or dummy."""
    return search(indicators_df, SHOCK_PATTERN, fields=("code", "name"), regex=True, case=False)


class Catalogue:
    """Cached view of one forecast's catalogue.

    The indicator and group lists are fetched once, kept in memory and, unless cache_dir
    is None, stored as JSON in ``<cache_dir>/<forecast_id>_indicators.json`` and
    ``_groups.json`` so later sessions skip the download. Delete the files (or call
    refresh()) to fetch again.
    """

    def __init__(self, client, forecast_id, cache_dir: Optional[str] = ".oegem_cache"):
        self.client = client
        self.forecast_id = str(forecast_id)
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self._data = {}

    def _cache_file(self, kind: str) -> Optional[Path]:
        if self.cache_dir is None:
            return None
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", self.forecast_id)
        return self.cache_dir / f"{safe}_{kind}.json"

    def _get(self, kind: str) -> pd.DataFrame:
        if kind in self._data:
            return self._data[kind]
        path = self._cache_file(kind)
        if path is not None and path.exists():
            df = pd.DataFrame(json.loads(path.read_text(encoding="utf-8")))
            log.debug("catalogue %s for %s read from %s", kind, self.forecast_id, path)
        else:
            df = indicators(self.client, self.forecast_id) if kind == "indicators" else groups(self.client, self.forecast_id)
            if path is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(df.to_json(orient="records"), encoding="utf-8")
        self._data[kind] = df
        return df

    @property
    def indicators(self) -> pd.DataFrame:
        """Indicator catalogue (code, name, ...)."""
        return self._get("indicators")

    @property
    def groups(self) -> pd.DataFrame:
        """Group catalogue (code, name, type, ...)."""
        return self._get("groups")

    @property
    def shocks(self) -> pd.DataFrame:
        """Indicators that look like shock, residual, add-factor or dummy variables."""
        return shock_variables(self.indicators)

    def refresh(self) -> None:
        """Forget cached lists (memory and disk) so the next access downloads again."""
        self._data.clear()
        for kind in ("indicators", "groups"):
            path = self._cache_file(kind)
            if path is not None and path.exists():
                path.unlink()

    def search(self, pattern: str, kind: str = "indicators", **kw) -> pd.DataFrame:
        """search() on the indicator (default) or group list."""
        return search(self.groups if kind == "groups" else self.indicators, pattern, **kw)

    @staticmethod
    def _lookup(df: pd.DataFrame, code: str) -> str:
        hit = df.loc[df["code"] == code, "name"]
        return str(hit.iloc[0]) if len(hit) and str(hit.iloc[0]) else code

    def indicator_name(self, code: str) -> str:
        """Name of an indicator, or the code itself if unknown."""
        return self._lookup(self.indicators, str(code).strip())

    def group_name(self, code: str) -> str:
        """Name of a group, or the code itself if unknown."""
        return self._lookup(self.groups, str(code).strip())

    def describe(self, code: str) -> str:
        """Readable label for "GDP", "GDP:US" or "&GDP:US", e.g. "GDP:US: Real GDP, United States"."""
        code = str(code).strip()
        if ":" not in code:
            return f"{code}: {self.indicator_name(code.lstrip('&'))}"
        ind, grp = code.lstrip("&").split(":", 1)
        prefix = "residual of " if code.startswith("&") else ""
        return f"{code}: {prefix}{self.indicator_name(ind)}, {self.group_name(grp)}"

    def to_excel(self, path) -> Path:
        """Write sheets Indicators, Groups and Shocks to an .xlsx file; returns the path."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with pd.ExcelWriter(path, engine="openpyxl") as xw:
            self.indicators.to_excel(xw, sheet_name="Indicators", index=False)
            self.groups.to_excel(xw, sheet_name="Groups", index=False)
            self.shocks.to_excel(xw, sheet_name="Shocks", index=False)
        return path
