"""Confidentiality guard: find credentials and licensed model content before git does.

The GEM is a licensed, confidential model, so this repository holds code and
documentation only. This module scans text, files and git content for what must
never be committed and reports every hit as a :class:`Finding`. It uses the
standard library only, so the git hook runs with a bare Python.

Rules (``--list-rules`` prints the one-line explanations):

* ``jwt``: JWT-like tokens, ``eyJ<header>.<payload>.<signature>``.
* ``bearer``: ``Bearer`` followed by a token-like value of 20+ characters
  (contains a digit, or both upper- and lower-case letters).
* ``credential-assignment``: a name ending in password, passwd, secret, token,
  client_id, client_secret, api_key or apikey (any case, so ``OE_TOKEN`` and
  ``clientSecret`` count, ``TOKEN_ENV`` does not) assigned a quoted literal of
  6+ characters with ``=``, ``:``, ``:=``, ``=>`` or ``<-``. Obvious placeholders
  are ignored: ``<...>``, ``{...}``, "your", "example", "***", "...", "xxx",
  "dummy", "fake", "placeholder", "redacted", "changeme", the words test, demo
  or sample, one repeated character, and environment lookups such as
  ``$OE_TOKEN``, ``${OE_TOKEN}``, ``%OE_TOKEN%``, ``$env:OE_TOKEN`` or a bare
  ``OE_TOKEN``-style name.
* ``auth-domain``: identity-provider tenant hosts (auth0.com with or without a
  region label, okta, b2clogin, onelogin, amazoncognito), unless the tenant part
  is a placeholder.
* ``email``: addresses, except example.org/.com/.net, the reserved test domains
  (.example, .invalid, .test, .localhost) and noreply addresses.
* ``uuid``: UUIDs, except obvious placeholders: at most four non-zero hex digits
  (e.g. the all-zero test value) or at most three distinct hex digits.
* ``equation-like``: two or more ``MNEM:GROUP`` references (``GDP:US``,
  ``&C:CHINA``, ``X:G[-1]``) plus a number with 3+ decimal places. References
  that use the fictional test codes (groups ALPHA, BETA, GAMMA, DELTA, EPSILON,
  OMEGA, XX, YY, ZZ, or a mnemonic of one repeated letter such as AAA) do not count.
* ``numeric-series``: six or more numbers with 3+ decimal places on one line.
* ``forbidden-file``: output formats of model runs (``FORBIDDEN_EXTENSIONS``;
  ``.3fs`` is allowed inside an ``examples`` directory). Checked in staged,
  tracked and history modes and for files named explicitly. A directory walk
  skips such files: in a working copy they are local, git-ignored results.
* ``large-file``: files over ``LARGE_FILE_BYTES`` (500 KiB). Their content is not scanned.
* ``deny-term``: terms from a local deny list, matched case-insensitively in
  file content and in repository-relative paths.

Deny list: one term per line, ``#`` starts a comment line. A term matches only
at letter/digit boundaries, and spaces, hyphens and underscores inside it match
any run of those characters (or none), so "Acme Widgets" also finds
``acme-widgets`` and ``ACME_WIDGETS``. A line ``re:<pattern>`` is a regular
expression. The list must live outside the tracked tree, so the sensitive words
are never committed. Lookup order: ``--deny FILE``, the ``OEGEM_DENY_FILE``
environment variable, then ``.git/info/oegem-deny.txt`` in the repository. With
no list the rule is skipped.

False positives: the comment ``leakcheck: allow`` on a line suppresses every
finding on that line. Use it sparingly; each use should be obvious to a reviewer.
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple, Union

__all__ = [
    "Finding", "RULES", "FORBIDDEN_EXTENSIONS", "LARGE_FILE_BYTES", "ALLOW_MARKER",
    "scan_text", "scan_paths", "scan_staged", "scan_tracked", "scan_history",
    "load_deny_terms", "default_deny_file", "main",
]

_log = logging.getLogger("oegem.leakcheck")

LARGE_FILE_BYTES = 500 * 1024
FORBIDDEN_EXTENSIONS = (
    ".3fs", ".xlsx", ".xls", ".csv", ".parquet", ".pq", ".json", ".mat", ".tex",
    ".dot", ".html", ".pdf", ".png", ".svg", ".pptx", ".docx", ".log",
)
# Directory walks never enter these: tool caches, environments and output folders.
SKIP_DIRS = frozenset({".git", "__pycache__", ".pytest_cache", "outputs", ".oegem_cache", ".venv", "venv"})
ALLOW_MARKER = "leakcheck: allow"
DENY_ENV_VAR = "OEGEM_DENY_FILE"
DENY_FILE_NAME = "oegem-deny.txt"
TEST_UUID = "00000000-0000-4000-8000-000000000000"
MAX_EXCERPT = 160
_COMMITS_SHOWN = 5
_READ_CHUNK_BYTES = 32 * 1024 * 1024   # bounds memory when reading many git blobs

RULES: Dict[str, str] = {
    "jwt": "JWT-like token; tokens come from the OE_TOKEN environment variable only",
    "bearer": "'Bearer' followed by a token value; never hard-code a token",
    "credential-assignment": "credential name (password, secret, token, client id, API key) "
                             "set to a literal; read it from the environment instead",
    "auth-domain": "identity-provider tenant host (e.g. <tenant>.auth0.com); "
                   "it belongs in OE_AUTH_DOMAIN, not in the repository",
    "email": "email address; personal or institutional contacts do not belong in the repository "
             "(placeholders at example.org/.com/.net are fine)",
    "uuid": f"UUID such as a release or forecast id; tests use {TEST_UUID}",
    "equation-like": "two or more MNEM:GROUP references and a number with 3+ decimals: "
                     "looks like a model equation with estimated coefficients",
    "numeric-series": "six or more numbers with 3+ decimals on one line: "
                      "looks like embedded model data such as a baseline path",
    "forbidden-file": "output format of model runs (data, catalogue, report, chart, scenario file); "
                      "keep it out of git",
    "large-file": "file over 500 KiB; code and documentation are small, large files are usually data",
    "deny-term": "term from the local deny list (organisation, project or workspace names)",
}

FIX_HINT = (
    "To fix: delete the content or keep it outside the repository (credentials in environment\n"
    "variables, model results under outputs/ or another ignored folder), then stage again.\n"
    "A deliberate false positive: add the comment 'leakcheck: allow' on that line (sparingly).\n"
    "Findings in history stay in every clone until the history is rewritten; rotate exposed tokens."
)

# ---- patterns ----------------------------------------------------------------

_ALLOW_RE = re.compile(r"leakcheck:\s*allow", re.IGNORECASE)
_JWT_RE = re.compile(r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]*")
_BEARER_RE = re.compile(r"\bbearer\s+(?P<tok>[A-Za-z0-9._~+/=-]{20,})", re.IGNORECASE)
_CRED_RE = re.compile(
    r"""
    (?:client_?id|client_?secret|password|passwd|api_?key|secret|token)
    (?![A-Za-z0-9_])                          # the name ends here: OE_TOKEN counts, TOKEN_ENV not
    ["'\]]*\s*                                # closing quote of a key, or the ] of an index
    (?::\s*[A-Za-z_][\w.\[\], ]*?\s*(?==))?   # optional type annotation
    (?:=>|:=|<-|=(?!=)|:)                     # assignment-like separator (not ==)
    \s*[bru]{0,2}                             # Python string prefixes
    (?:"(?P<dq>[^"\r\n]*)"|'(?P<sq>[^'\r\n]*)')
    """,
    re.IGNORECASE | re.VERBOSE,
)
_IDP_RE = re.compile(
    r"(?<![\w.-])(?P<tenant>(?:[a-z0-9-]+\.)+)"
    r"(?:auth0\.com|okta\.com|oktapreview\.com|okta-emea\.com|b2clogin\.com|onelogin\.com|amazoncognito\.com)"
    r"(?![\w-])",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(
    r"(?<![\w.%+-])(?P<local>[A-Za-z0-9._%+-]+)@(?P<domain>(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,})(?![\w-])"
)
_UUID_RE = re.compile(
    r"(?<![0-9A-Fa-f-])[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}"
    r"(?![0-9A-Fa-f-])"
)
_REF_RE = re.compile(r"(?<![A-Za-z0-9_&])&?(?P<mnem>[A-Z][A-Z0-9_]*):(?P<group>[A-Z][A-Z0-9_]*)(?![A-Za-z0-9_])")
_DECIMAL_RE = re.compile(r"(?<![\w.])\d*\.\d{3,}(?:[eE][-+]?\d+)?(?![\w.])")

_FICTIONAL_GROUPS = frozenset({"ALPHA", "BETA", "GAMMA", "DELTA", "EPSILON", "OMEGA", "XX", "YY", "ZZ"})
_PLACEHOLDER_PARTS = (
    "your", "example", "***", "...", "xxx", "dummy", "fake", "placeholder", "redacted",
    "changeme", "change-me", "change_me",
)
_PLACEHOLDER_WORD_RE = re.compile(r"(?<![a-z])(?:test|demo|sample)(?![a-z])", re.IGNORECASE)
_ANGLE_RE = re.compile(r"<[^<>]+>")
_TEMPLATE_RE = re.compile(r"\{[^{}]*\}")
_ENV_LOOKUP_RE = re.compile(
    r"^(?:\$\{?[A-Za-z_]\w*\}?|%[A-Za-z_]\w*%|\$(?:env|ENV|Env):[A-Za-z_]\w*|[A-Z][A-Z0-9]*_[A-Z0-9_]+)$"
)
_PLACEHOLDER_EMAIL_DOMAINS = ("example.org", "example.com", "example.net")
_RESERVED_TLDS = ("example", "invalid", "test", "localhost")


# ---- findings ------------------------------------------------------------------

@dataclass(frozen=True)
class Finding:
    """One hit of a rule.

    ``path`` is the file (repository-relative in git modes), ``line`` is 1-based,
    or 0 when the finding concerns the whole file (name, format or size). The
    ``excerpt`` is the offending line with credential values replaced by ``***``.
    ``commits`` lists, in history mode, the commits that introduced the blob.
    """

    path: str
    line: int
    rule: str
    excerpt: str
    commits: Tuple[str, ...] = ()

    @property
    def explanation(self) -> str:
        """The one-line explanation of this finding's rule."""
        return RULES.get(self.rule, "")

    def __str__(self) -> str:
        where = f"{self.path}:{self.line}" if self.line else self.path
        text = f"{where}: [{self.rule}] {self.excerpt}"
        if self.commits:
            shown = ", ".join(self.commits[:_COMMITS_SHOWN])
            more = f" and {len(self.commits) - _COMMITS_SHOWN} more" if len(self.commits) > _COMMITS_SHOWN else ""
            text += f"  (introduced in {shown}{more})"
        return text


# ---- line rules ----------------------------------------------------------------

def _is_placeholder(value: str) -> bool:
    """True for values that are obviously not real secrets (see the module docstring)."""
    v = value.strip()
    low = v.lower()
    return (
        not v
        or len(set(v)) == 1
        or any(part in low for part in _PLACEHOLDER_PARTS)
        or bool(_ANGLE_RE.search(v) or _TEMPLATE_RE.search(v) or _PLACEHOLDER_WORD_RE.search(v))
        or bool(_ENV_LOOKUP_RE.match(v))
    )


def _looks_like_token(value: str) -> bool:
    """Tokens carry digits or mixed case; prose after the word 'bearer' rarely does."""
    has_upper = any(c.isupper() for c in value)
    has_lower = any(c.islower() for c in value)
    return any(c.isdigit() for c in value) or (has_upper and has_lower)


def _is_placeholder_host(tenant: str) -> bool:
    low = tenant.lower()
    return low == "www." or "tenant" in low or _is_placeholder(tenant.rstrip("."))


def _is_placeholder_email(local: str, domain: str) -> bool:
    low_local, low_domain = local.lower(), domain.lower()
    if any(tag in text for tag in ("noreply", "no-reply") for text in (low_local, low_domain)):
        return True
    if any(low_domain == d or low_domain.endswith("." + d) for d in _PLACEHOLDER_EMAIL_DOMAINS):
        return True
    return low_domain.rsplit(".", 1)[-1] in _RESERVED_TLDS


def _is_placeholder_uuid(value: str) -> bool:
    digits = value.replace("-", "").lower()
    return sum(c != "0" for c in digits) <= 4 or len(set(digits)) <= 3


def _is_fictional_ref(mnemonic: str, group: str) -> bool:
    return group in _FICTIONAL_GROUPS or (len(mnemonic) >= 2 and len(set(mnemonic)) == 1)


def _credential_value(match: "re.Match[str]") -> str:
    return match.group("dq") if match.group("dq") is not None else match.group("sq")


def _line_hits(line: str, deny: Sequence[Tuple[str, "re.Pattern[str]"]]) -> List[Tuple[str, str]]:
    """Return (rule, matched text) pairs for one line, at most one per rule."""
    hits: List[Tuple[str, str]] = []
    match = _JWT_RE.search(line)
    if match:
        hits.append(("jwt", match.group(0)))
    for match in _BEARER_RE.finditer(line):
        token = match.group("tok")
        if _looks_like_token(token) and not _is_placeholder(token):
            hits.append(("bearer", match.group(0)))
            break
    for match in _CRED_RE.finditer(line):
        value = _credential_value(match)
        if len(value) >= 6 and not _is_placeholder(value):
            hits.append(("credential-assignment", match.group(0)))
            break
    for match in _IDP_RE.finditer(line):
        if not _is_placeholder_host(match.group("tenant")):
            hits.append(("auth-domain", match.group(0)))
            break
    for match in _EMAIL_RE.finditer(line):
        if not _is_placeholder_email(match.group("local"), match.group("domain")):
            hits.append(("email", match.group(0)))
            break
    for match in _UUID_RE.finditer(line):
        if not _is_placeholder_uuid(match.group(0)):
            hits.append(("uuid", match.group(0)))
            break
    decimals = _DECIMAL_RE.findall(line)
    if decimals:
        refs = [m for m in _REF_RE.finditer(line) if not _is_fictional_ref(m.group("mnem"), m.group("group"))]
        if len(refs) >= 2:
            hits.append(("equation-like", refs[0].group(0)))
        if len(decimals) >= 6:
            hits.append(("numeric-series", decimals[0]))
    for _term, pattern in deny:
        match = pattern.search(line)
        if match:
            hits.append(("deny-term", match.group(0)))
            break
    return hits


def _mask_credential(match: "re.Match[str]") -> str:
    group = "dq" if match.group("dq") is not None else "sq"
    start, end = match.span(group)
    if start == end:
        return match.group(0)
    whole, base = match.group(0), match.start()
    return whole[: start - base] + "***" + whole[end - base:]


def _redact(text: str) -> str:
    """Replace JWTs, bearer values and credential literals with ***."""
    text = _JWT_RE.sub("***", text)
    text = _BEARER_RE.sub(lambda m: m.group(0)[: m.start("tok") - m.start()] + "***", text)
    return _CRED_RE.sub(_mask_credential, text)


def _excerpt(line: str, hit: str = "") -> str:
    """The redacted line, cut to MAX_EXCERPT characters around the hit."""
    text = _redact(line).strip()
    if len(text) <= MAX_EXCERPT:
        return text
    anchor = text.find(_redact(hit).strip()) if hit else -1
    start = max(0, anchor - 40) if anchor > 0 else 0
    piece = text[start:start + MAX_EXCERPT]
    return ("..." if start else "") + piece + ("..." if start + MAX_EXCERPT < len(text) else "")


def _compile_deny(terms: Optional[Iterable[str]]) -> List[Tuple[str, "re.Pattern[str]"]]:
    compiled: List[Tuple[str, "re.Pattern[str]"]] = []
    for raw in terms or ():
        term = str(raw).strip()
        if not term or term.startswith("#"):
            continue
        if term.startswith("re:"):
            try:
                pattern = re.compile(term[3:], re.IGNORECASE)
            except re.error as exc:
                raise ValueError(f"deny list: invalid regular expression {term!r}: {exc}") from None
        else:
            parts = [re.escape(p) for p in re.split(r"[\s_-]+", term) if p]
            if not parts:
                continue
            pattern = re.compile(r"(?<![A-Za-z0-9])" + r"[\s_-]*".join(parts) + r"(?![A-Za-z0-9])", re.IGNORECASE)
        compiled.append((term, pattern))
    return compiled


def _scan_lines(text: str, path: str, deny: Sequence[Tuple[str, "re.Pattern[str]"]]) -> List[Finding]:
    found: List[Finding] = []
    for number, raw in enumerate(text.split("\n"), start=1):
        line = raw.rstrip("\r")
        if not line.strip() or _ALLOW_RE.search(line):
            continue
        for rule, hit in _line_hits(line, deny):
            found.append(Finding(path, number, rule, _excerpt(line, hit)))
    return found


def scan_text(text: str, path: str = "", deny_terms: Optional[Iterable[str]] = ()) -> List[Finding]:
    """Scan a string with the line rules.

    Args: text is the content, path is only copied into the findings, and
    deny_terms are deny-list terms (the deny rule runs only when terms are given;
    this function never reads a deny file).
    Returns: the findings, in line order.
    """
    return _scan_lines(text, path, _compile_deny(deny_terms))


# ---- files -----------------------------------------------------------------------

@dataclass
class _Record:
    """A file to scan: from disk (fs_path) or a git blob (data filled in batches)."""

    path: str                         # shown in findings
    rel: str                          # path used by the file-name rules ("" skips them)
    size: int
    check_format: bool                # apply the forbidden-file rule
    fs_path: Optional[Path] = None
    data: Optional[bytes] = None
    blob: str = ""

    def read(self) -> Optional[bytes]:
        if self.data is not None:
            return self.data
        return self.fs_path.read_bytes() if self.fs_path is not None else None


def _extension(path: str) -> str:
    return os.path.splitext(path.replace("\\", "/"))[1].lower()


def _is_forbidden_name(path: str) -> bool:
    ext = _extension(path)
    if ext not in FORBIDDEN_EXTENSIONS:
        return False
    # Illustrative scenario files are the one tracked .3fs exception (see .gitignore).
    return not (ext == ".3fs" and "examples" in path.replace("\\", "/").split("/")[:-1])


def _decode(data: Optional[bytes]) -> Optional[str]:
    """Bytes to text; None for binary content."""
    if data is None:
        return None
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    if b"\x00" in data[:8192]:
        return None
    return data.decode("utf-8", errors="replace").lstrip("﻿")


def _scan_record(rec: _Record, deny: Sequence[Tuple[str, "re.Pattern[str]"]]) -> List[Finding]:
    found: List[Finding] = []
    if rec.rel:
        for term, pattern in deny:
            if pattern.search(rec.rel):
                found.append(Finding(rec.path, 0, "deny-term", f"file path matches deny term {term!r}"))
                break
    # The shown path keeps parent folders (rel may be a bare name), which the
    # examples/ exception for .3fs needs.
    if rec.check_format and _is_forbidden_name(rec.path):
        ext = _extension(rec.path)
        note = " (allowed only inside examples/)" if ext == ".3fs" else ""
        found.append(Finding(rec.path, 0, "forbidden-file", f"{ext} file{note}"))
        return found
    if rec.size > LARGE_FILE_BYTES:
        found.append(Finding(rec.path, 0, "large-file",
                             f"{rec.size / 1024:.0f} KiB (limit {LARGE_FILE_BYTES // 1024} KiB)"))
        return found
    try:
        text = _decode(rec.read())
    except OSError as exc:
        _log.warning("leakcheck: cannot read %s: %s", rec.path, exc)
        return found
    if text:
        found.extend(_scan_lines(text, rec.path, deny))
    return found


def _scan_records(records: Iterable[_Record], deny) -> Tuple[List[Finding], int]:
    findings: List[Finding] = []
    count = 0
    for rec in records:
        count += 1
        findings.extend(_scan_record(rec, deny))
    return findings, count


def _walk(root: Path) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.endswith(".egg-info"))
        for name in sorted(filenames):
            yield Path(dirpath) / name


def _file_record(path: Path, cwd: Path, check_format: bool) -> _Record:
    try:
        shown = path.resolve().relative_to(cwd).as_posix()
        rel = shown
    except ValueError:
        # Outside the working directory: show the path as given, but apply the
        # name rules to the file name only (parent folders are not repo content).
        shown, rel = path.as_posix(), path.name
    return _Record(shown, rel, path.stat().st_size, check_format, fs_path=path)


def _path_records(paths: Sequence[Union[str, os.PathLike]]) -> Iterator[_Record]:
    items = [Path(p) for p in paths]
    missing = [str(p) for p in items if not p.exists()]
    if missing:
        raise FileNotFoundError(f"no such file or directory: {', '.join(missing)}")
    cwd = Path.cwd().resolve()
    for item in items:
        if item.is_file():
            yield _file_record(item, cwd, check_format=True)
            continue
        for path in _walk(item):
            # In a working copy, output formats are local results that git ignores;
            # --staged/--tracked/--history check what git would actually publish.
            if _is_forbidden_name(path.as_posix()):
                continue
            yield _file_record(path, cwd, check_format=False)


def load_deny_terms(path: Union[str, os.PathLike]) -> List[str]:
    """Read a deny list: one term per line, blank lines and lines starting with # skipped.

    Returns: the terms in file order.
    """
    terms = []
    for raw in Path(path).read_text(encoding="utf-8-sig").splitlines():
        term = raw.strip()
        if term and not term.startswith("#"):
            terms.append(term)
    return terms


def default_deny_file(repo: Union[str, os.PathLike] = ".") -> Optional[Path]:
    """Where the deny list is looked up when none is given explicitly.

    Returns: the OEGEM_DENY_FILE path if that variable is set, else
    ``<git dir>/info/oegem-deny.txt`` of the repository containing ``repo``,
    else None. The file may not exist; callers check.
    """
    env = os.environ.get(DENY_ENV_VAR, "").strip()
    if env:
        return Path(env)
    try:
        out = _git(Path(repo), "rev-parse", "--git-path", "info/" + DENY_FILE_NAME)
    except RuntimeError:
        return None
    path = Path(out.decode("utf-8", "replace").strip())
    return path if path.is_absolute() else Path(repo) / path


def _resolve_deny(deny_terms: Optional[Iterable[str]], repo) -> List[Tuple[str, "re.Pattern[str]"]]:
    if deny_terms is None:
        path = default_deny_file(repo)
        deny_terms = load_deny_terms(path) if path is not None and path.is_file() else []
    return _compile_deny(deny_terms)


def scan_paths(paths: Union[str, os.PathLike, Sequence[Union[str, os.PathLike]]],
               deny_terms: Optional[Iterable[str]] = None) -> List[Finding]:
    """Scan files and directories (recursively) on disk.

    Directory walks skip .git, __pycache__, .pytest_cache, outputs, .oegem_cache,
    .venv, venv and *.egg-info, and files in the forbidden formats (those are
    reported only for files named explicitly).
    Args: paths is one path or a list; deny_terms None means the default deny
    list of the current directory's repository, () switches the rule off.
    Returns: the findings. Raises FileNotFoundError for a missing path.
    """
    if isinstance(paths, (str, os.PathLike)):
        paths = [paths]
    return _scan_records(_path_records(paths), _resolve_deny(deny_terms, "."))[0]


# ---- git -------------------------------------------------------------------------

def _git(cwd: Path, *args: str, input: Optional[bytes] = None) -> bytes:
    try:
        proc = subprocess.run(["git", *args], cwd=str(cwd), input=input,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as exc:
        raise RuntimeError(f"cannot run git in {cwd}: {exc}") from None
    if proc.returncode != 0:
        message = proc.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"git {args[0]} failed: {message}")
    return proc.stdout


def _git_root(repo: Union[str, os.PathLike]) -> Optional[Path]:
    try:
        out = _git(Path(repo), "rev-parse", "--show-toplevel")
    except RuntimeError:
        return None
    text = out.decode("utf-8", "replace").strip()
    return Path(text) if text else None


def _require_repo(repo: Union[str, os.PathLike]) -> Path:
    root = _git_root(repo)
    if root is None:
        raise ValueError(f"not inside a git repository (or git is not installed): {repo}")
    return root


def _batch_check(root: Path, names: Sequence[str]) -> List[Optional[Tuple[str, str, int]]]:
    """(sha, type, size) per object name via one `git cat-file --batch-check`; None if missing."""
    out = _git(root, "cat-file", "--batch-check", input="".join(n + "\n" for n in names).encode("utf-8"))
    lines = out.decode("utf-8", "replace").split("\n")
    result: List[Optional[Tuple[str, str, int]]] = []
    for i in range(len(names)):
        parts = lines[i].split(" ") if i < len(lines) else []
        ok = len(parts) == 3 and parts[2].isdigit()
        result.append((parts[0], parts[1], int(parts[2])) if ok else None)
    return result


def _batch_read(root: Path, shas: Sequence[str]) -> List[bytes]:
    """Blob contents via one `git cat-file --batch` call."""
    out = _git(root, "cat-file", "--batch", input="".join(s + "\n" for s in shas).encode("utf-8"))
    contents, pos = [], 0
    for _ in shas:
        newline = out.index(b"\n", pos)
        header = out[pos:newline].decode("utf-8", "replace").split(" ")
        pos = newline + 1
        if len(header) != 3 or not header[2].isdigit():
            contents.append(b"")
            continue
        size = int(header[2])
        contents.append(out[pos:pos + size])
        pos += size + 1
    return contents


def _blob_records(root: Path, items: Sequence[Tuple[str, str]]) -> List[_Record]:
    """Records for (path, object name) pairs; reads only blobs whose content is scanned."""
    if not items:
        return []
    records: List[_Record] = []
    to_read: List[_Record] = []
    for (path, _name), meta in zip(items, _batch_check(root, [name for _, name in items])):
        if meta is None or meta[1] != "blob":
            continue
        rec = _Record(path, path, meta[2], True, blob=meta[0])
        records.append(rec)
        if meta[2] <= LARGE_FILE_BYTES and not _is_forbidden_name(path):
            to_read.append(rec)
    chunk: List[_Record] = []
    total = 0
    for rec in to_read + [None]:  # None flushes the last chunk
        if rec is not None:
            chunk.append(rec)
            total += rec.size
        if chunk and (rec is None or total >= _READ_CHUNK_BYTES):
            for item, data in zip(chunk, _batch_read(root, [r.blob for r in chunk])):
                item.data = data
            chunk, total = [], 0
    return records


def _staged_records(root: Path) -> List[_Record]:
    out = _git(root, "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
    paths = [p for p in out.decode("utf-8", "replace").split("\0") if p]
    return _blob_records(root, [(p, ":0:" + p) for p in paths])


def _tracked_records(root: Path) -> List[_Record]:
    out = _git(root, "ls-files", "-z")
    records = []
    for rel in sorted({p for p in out.decode("utf-8", "replace").split("\0") if p}):
        path = root / rel
        if path.is_file():  # skips files deleted in the working tree and submodules
            records.append(_Record(rel, rel, path.stat().st_size, True, fs_path=path))
    return records


def _introducing_commits(root: Path, blobs: Iterable[str]) -> Dict[str, Tuple[str, ...]]:
    """Map blob id -> short ids of the commits whose diff adds that content (one git log)."""
    wanted = set(blobs)
    if not wanted:
        return {}
    try:
        # --no-abbrev keeps the blob ids in the raw lines whole (it also un-abbreviates
        # %h, hence %H cut to 10 characters below).
        out = _git(root, "log", "--all", "--no-renames", "--raw", "--no-abbrev", "--format=commit %H")
    except RuntimeError:
        return {}
    found: Dict[str, List[str]] = {}
    commit = ""
    for line in out.decode("utf-8", "replace").splitlines():
        if line.startswith("commit "):
            commit = line[len("commit "):].strip()[:10]
        elif line.startswith(":") and commit:
            fields = line.split("\t", 1)[0].split()
            if len(fields) >= 5 and fields[3] in wanted and commit not in found.get(fields[3], []):
                found.setdefault(fields[3], []).append(commit)
    return {blob: tuple(ids) for blob, ids in found.items()}


def _history_scan(root: Path, deny) -> Tuple[List[Finding], int]:
    out = _git(root, "rev-list", "--all", "--objects")
    first_path: Dict[str, str] = {}
    for line in out.decode("utf-8", "replace").splitlines():
        sha, _, path = line.partition(" ")
        if path and sha not in first_path:
            first_path[sha] = path
    records = _blob_records(root, [(path, sha) for sha, path in first_path.items()])
    per_blob = []
    for rec in records:
        found = _scan_record(rec, deny)
        if found:
            per_blob.append((rec.blob, found))
    commits = _introducing_commits(root, [blob for blob, _ in per_blob])
    findings = [replace(f, commits=commits.get(blob, ())) for blob, found in per_blob for f in found]
    findings.sort(key=lambda f: (f.path, f.line, f.rule))
    return findings, len(records)


def scan_staged(repo: Union[str, os.PathLike] = ".", deny_terms: Optional[Iterable[str]] = None) -> List[Finding]:
    """Scan the staged version of every added, copied, modified or renamed file.

    Args: repo is any directory inside the repository; deny_terms None means the
    repository's default deny list, () switches the rule off.
    Returns: the findings (paths relative to the repository root).
    """
    root = _require_repo(repo)
    return _scan_records(_staged_records(root), _resolve_deny(deny_terms, root))[0]


def scan_tracked(repo: Union[str, os.PathLike] = ".", deny_terms: Optional[Iterable[str]] = None) -> List[Finding]:
    """Scan the working-tree content of every file git tracks (``git ls-files``).

    Args and Returns as for :func:`scan_staged`.
    """
    root = _require_repo(repo)
    return _scan_records(_tracked_records(root), _resolve_deny(deny_terms, root))[0]


def scan_history(repo: Union[str, os.PathLike] = ".", deny_terms: Optional[Iterable[str]] = None) -> List[Finding]:
    """Scan every blob reachable from any ref (``git rev-list --all --objects``).

    Each blob is scanned once and reported under the first path it was seen at;
    ``Finding.commits`` lists the commits that introduced it.
    Args and Returns as for :func:`scan_staged`.
    """
    root = _require_repo(repo)
    return _history_scan(root, _resolve_deny(deny_terms, root))[0]


# ---- command line ------------------------------------------------------------------

def _emit(text: str = "", stream=None) -> None:
    stream = stream or sys.stdout
    try:
        stream.write(text + "\n")
    except UnicodeEncodeError:  # e.g. a cp1252 console and a non-Latin excerpt
        encoding = getattr(stream, "encoding", None) or "ascii"
        stream.write((text + "\n").encode(encoding, "backslashreplace").decode(encoding))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check_confidential",
        description="Scan for credentials and licensed model content (equations, coefficients, "
                    "data, output files) before they reach git.",
        epilog="With no PATH and no mode: --tracked inside a git repository, else the current "
               "directory. Exit status: 0 clean, 1 findings, 2 usage error. Deny list lookup: "
               f"--deny, ${DENY_ENV_VAR}, .git/info/{DENY_FILE_NAME} (keep it out of the tracked "
               "tree). Suppress a deliberate false positive with the comment "
               "'leakcheck: allow' on that line.",
    )
    parser.add_argument("paths", nargs="*", metavar="PATH", help="files or directories to scan")
    parser.add_argument("--staged", action="store_true", help="scan the staged files (the pre-commit hook)")
    parser.add_argument("--tracked", action="store_true", help="scan every tracked file (working-tree content)")
    parser.add_argument("--history", action="store_true", help="scan every blob reachable from any ref")
    parser.add_argument("--deny", metavar="FILE", help="deny-term list to use")
    parser.add_argument("--repo", metavar="DIR", default=".",
                        help="repository for the git modes and the default deny list (default: .)")
    parser.add_argument("--list-rules", action="store_true", help="print the rules and exit")
    return parser


def _deny_for_cli(args: argparse.Namespace) -> Tuple[List[str], str]:
    if args.deny:
        if not Path(args.deny).is_file():
            raise ValueError(f"deny list not found: {args.deny}")
        terms = load_deny_terms(args.deny)
    else:
        path = default_deny_file(args.repo)
        if path is None or not path.is_file():
            if os.environ.get(DENY_ENV_VAR, "").strip():
                _emit(f"leakcheck: warning: {DENY_ENV_VAR} points to a missing file; deny-term rule skipped",
                      sys.stderr)
            return [], "deny list: none"
        terms = load_deny_terms(path)
    return terms, f"deny list: {len(terms)} term(s)"


def _report(findings: List[Finding], scanned: int, modes: List[str], deny_note: str) -> None:
    context = f"{', '.join(modes)}; {deny_note}"
    if not findings:
        _emit(f"leakcheck: no findings in {scanned} file(s) ({context}).")
        return
    files = len({f.path for f in findings})
    _emit(f"leakcheck: {len(findings)} finding(s) in {files} of {scanned} file(s) ({context})")
    _emit()
    for finding in findings:
        _emit("  " + str(finding))
    fired = [rule for rule in RULES if any(f.rule == rule for f in findings)]
    width = max(len(rule) for rule in fired)
    _emit()
    _emit("What the rules mean:")
    for rule in fired:
        _emit(f"  {rule:<{width}}  {RULES[rule]}")
    _emit()
    _emit(FIX_HINT)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Command-line entry point.

    Args: argv as for ``check_confidential.py`` (see ``--help``); None reads sys.argv.
    Returns: 0 when clean, 1 when there are findings, 2 on a usage error.
    """
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:  # argparse exits on --help (0) and on bad arguments (2)
        return 0 if exc.code in (0, None) else 2
    if args.list_rules:
        width = max(len(rule) for rule in RULES)
        for rule, text in RULES.items():
            _emit(f"{rule:<{width}}  {text}")
        return 0
    findings: List[Finding] = []
    scanned = 0
    modes: List[str] = []
    try:
        terms, deny_note = _deny_for_cli(args)
        deny = _compile_deny(terms)
        if not (args.paths or args.staged or args.tracked or args.history):
            if _git_root(args.repo) is not None:
                args.tracked = True
            else:
                args.paths = ["."]
        if args.paths:
            found, count = _scan_records(_path_records(args.paths), deny)
            findings += found
            scanned += count
            modes.append("paths")
        for enabled, label, records in (
            (args.staged, "staged", _staged_records),
            (args.tracked, "tracked", _tracked_records),
        ):
            if enabled:
                found, count = _scan_records(records(_require_repo(args.repo)), deny)
                findings += found
                scanned += count
                modes.append(label)
        if args.history:
            found, count = _history_scan(_require_repo(args.repo), deny)
            findings += found
            scanned += count
            modes.append("history")
    except (OSError, ValueError, RuntimeError) as exc:
        _emit(f"leakcheck: error: {exc}", sys.stderr)
        return 2
    _report(findings, scanned, modes, deny_note)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
