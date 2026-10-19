"""Tests for oegem.leakcheck, the confidentiality checker.

Every sensitive-looking string here is assembled at run time from harmless
fragments, so no single line of this file trips the checker;
test_own_files_are_clean asserts exactly that.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from oegem.leakcheck import (
    FORBIDDEN_EXTENSIONS,
    LARGE_FILE_BYTES,
    RULES,
    Finding,
    load_deny_terms,
    main,
    scan_history,
    scan_paths,
    scan_staged,
    scan_text,
    scan_tracked,
)

ROOT = Path(__file__).resolve().parents[1]
HAS_GIT = shutil.which("git") is not None


def cat(*parts: str) -> str:
    """Join fragments at run time (keeps complete fake secrets out of this file)."""
    return "".join(parts)


FAKE_KEY = cat("Zq8Xw2", "Lm9Pk4", "Rt7Vb3")


def fake_jwt() -> str:
    head = cat("ey", "J", "hbGciOiJIUzI1NiJ9")
    body = cat("ey", "J", "zdWIiOiJ1bml0In0")
    return cat(head, ".", body, ".", "Qm9ndXNTaWduYXR1cmU")


def rules(text: str, **kwargs) -> list:
    return [f.rule for f in scan_text(text, **kwargs)]


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    """Empty default deny list, and no git repository discovered above tmp_path."""
    deny = tmp_path / "empty-deny.txt"
    deny.write_text("")
    monkeypatch.setenv("OEGEM_DENY_FILE", str(deny))
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))


# ---- rule table and findings -------------------------------------------------------

def test_rule_table():
    assert set(RULES) == {
        "jwt", "bearer", "credential-assignment", "auth-domain", "email", "uuid",
        "equation-like", "numeric-series", "forbidden-file", "large-file", "deny-term",
    }
    assert all(RULES.values())


def test_finding_formatting():
    hit = Finding("pkg/a.py", 3, "jwt", "value = ***")
    assert str(hit) == "pkg/a.py:3: [jwt] value = ***"
    assert hit.explanation == RULES["jwt"]
    whole = Finding("data.csv", 0, "forbidden-file", ".csv file", commits=("abc1234",))
    assert str(whole) == "data.csv: [forbidden-file] .csv file  (introduced in abc1234)"


# ---- one positive and one negative case per line rule ---------------------------

def test_jwt_flagged_and_redacted():
    found = scan_text(cat("value = '", fake_jwt(), "'"), path="x.py")
    assert [(f.path, f.line, f.rule) for f in found] == [("x.py", 1, "jwt")]
    assert fake_jwt() not in found[0].excerpt and "***" in found[0].excerpt


def test_jwt_negative():
    assert rules("a JWT looks like eyJ... (three base64url parts joined by dots)") == []


def test_bearer_flagged_and_redacted():
    found = scan_text(cat('headers = {"Authorization": "Bearer ', FAKE_KEY, FAKE_KEY, '"}'))
    assert [f.rule for f in found] == ["bearer"]
    assert FAKE_KEY not in found[0].excerpt


@pytest.mark.parametrize("line", [
    'headers = {"Authorization": f"Bearer {self._token}"}',
    "Missing or invalid bearer token",
    "Authorization: Bearer <OE_TOKEN>",
    "Authorization: Bearer $OE_TOKEN",
    "the bearer authentication-scheme-description",
])
def test_bearer_negative(line):
    assert "bearer" not in rules(line)


@pytest.mark.parametrize("template", [
    '{name} = "{value}"',          # Python, shell
    "opts.{name} = '{value}';",    # MATLAB struct field
    '{{"{name}": "{value}"}}',     # JSON or dict literal
    "{name}: str = '{value}'",     # annotated assignment
    '{name}: "{value}"',           # YAML
])
@pytest.mark.parametrize("name", ["password", "client_secret", "OE_TOKEN", "apiKey", "client_id"])
def test_credential_assignment_flagged(template, name):
    line = template.format(name=name, value=FAKE_KEY)
    found = scan_text(line)
    assert [f.rule for f in found] == ["credential-assignment"], line
    assert FAKE_KEY not in found[0].excerpt


@pytest.mark.parametrize("line", [
    'token = os.environ["OE_TOKEN"]',
    'password = "<your password>"',
    "client_secret = '***'",
    'api_key = "short"',
    'token = "${OE_TOKEN}"',
    "$env:OE_TOKEN = '<paste the token here>'",
    'token_env = "OE_TOKEN_VALUE"',
    'client_id = "your-client-id"',
    'password = "xxxxxxxx"',
    'TOKEN = "test-token-0123456789"',
    'if token == "abcdefgh":',
])
def test_credential_assignment_negative(line):
    assert "credential-assignment" not in rules(line)


def test_auth_domain_flagged():
    for host in (cat("acme-corp", ".auth0", ".com"), cat("acme-corp", ".eu", ".auth0", ".com"),
                 cat("acme", ".okta", ".com")):
        assert rules(cat("OE_AUTH_DOMAIN=https://", host, "/oauth/token")) == ["auth-domain"], host


@pytest.mark.parametrize("line", [
    "set OE_AUTH_DOMAIN to your tenant host, e.g. <tenant>.auth0.com",
    "https://your-tenant.eu.auth0.com/oauth/token",
    "https://auth.example.invalid/oauth/token",
])
def test_auth_domain_negative(line):
    assert rules(line) == []


def test_email_flagged():
    assert rules(cat("maintainer: jane.doe", "@", "acme-corp.org")) == ["email"]


@pytest.mark.parametrize("line", [
    "contact: someone@example.org",
    "ops@mail.example.com",
    "noreply@acme-corp.org",
    "user@host.invalid",
    "@pytest.fixture",
    "y = a@b.T",
    "SET X:Y 2027Q1 4@0.5",
])
def test_email_negative(line):
    assert rules(line) == []


def test_uuid_flagged():
    release_id = "-".join(["3f2b8c1d", "9a4e", "4c7b", "8e21", "5d6f7a8b9c0d"])
    assert rules(cat("release ", release_id)) == ["uuid"]


@pytest.mark.parametrize("line", [
    "00000000-0000-4000-8000-000000000000",
    "00000000-0000-0000-0000-000000000000",
    "00000000-0000-4000-8000-000000000042",
    "ffffffff-ffff-ffff-ffff-ffffffffffff",
])
def test_uuid_negative(line):
    assert rules(line) == []


def test_equation_like_flagged():
    coef = cat("0.", "512")
    equation = cat("DLOG(C:US) = ", coef, " * DLOG(YD:US) + 0.25 * DLOG(C:US[-1]) + &C:US")
    assert rules(equation) == ["equation-like"]


@pytest.mark.parametrize("line", [
    "DLOG(C:US) = 0.5 * DLOG(YD:US) + 0.25 * DLOG(C:US[-1])",   # no 3-decimal number
    "(EXP(0 - 1.25 + 0.5 * LN(S(AAA:ALPHA, 4)))) * &BBB:ALPHA",
    "LN(AAA:ALPHA) = 0.125 + 0.875 * LN(BBB:BETA[-1])",          # fictional test codes
    "GDP:US rises by 0.125 percent",                              # one reference
])
def test_equation_like_negative(line):
    assert rules(line) == []


def test_numeric_series_flagged():
    path = ", ".join(f"{100 + i / 8:.3f}" for i in range(8))
    assert rules(cat("baseline = [", path, "]")) == ["numeric-series"]


@pytest.mark.parametrize("line", [
    "values = [0.125, 0.250, 0.375, 0.500, 0.625]",            # five, below the threshold
    "values = [1.5, 2.25, 3.5, 4.75, 5.0, 6.25, 7.5]",          # two decimals at most
    "versions 1.2.345, 2.3.456, 3.4.567, 4.5.678, 5.6.789, 6.7.890",
])
def test_numeric_series_negative(line):
    assert rules(line) == []


def test_allow_marker_suppresses_one_line():
    line = cat("value = '", fake_jwt(), "'")
    assert rules(line) == ["jwt"]
    assert rules(line + "  # leakcheck: allow") == []
    assert rules(cat(line, "  # leakcheck: allow\n", line)) == ["jwt"]


# ---- file rules ----------------------------------------------------------------------

@pytest.mark.parametrize("ext", FORBIDDEN_EXTENSIONS)
def test_forbidden_file_flagged_when_named(tmp_path, ext):
    path = tmp_path / ("out" + ext)
    path.write_text("x\n")
    assert [(f.rule, f.line) for f in scan_paths([path], deny_terms=())] == [("forbidden-file", 0)]


def test_forbidden_file_negative(tmp_path):
    examples = tmp_path / "examples"
    examples.mkdir()
    scenario = examples / "oil_up.3fs"
    scenario.write_text("MULTIPLY WPO_EQN:WORLD 2027Q1 1.2, 1.2, 1.2, 1.2\n")
    code = tmp_path / "tool.py"
    code.write_text("x = 1\n")
    assert scan_paths([scenario, code], deny_terms=()) == []
    # A directory walk skips output formats and outputs/: in a working copy
    # they are local results that git ignores.
    (tmp_path / "table.csv").write_text("a,b\n")
    (tmp_path / "outputs").mkdir()
    (tmp_path / "outputs" / "notes.txt").write_text(cat("value = '", fake_jwt(), "'\n"))
    assert scan_paths([tmp_path], deny_terms=()) == []


def test_large_file(tmp_path):
    big = tmp_path / "big.txt"
    big.write_bytes(b"a" * (LARGE_FILE_BYTES + 1))
    small = tmp_path / "small.txt"
    small.write_bytes(b"a" * 1000)
    assert [f.rule for f in scan_paths([big], deny_terms=())] == ["large-file"]
    assert scan_paths([small], deny_terms=()) == []


def test_utf16_text_is_scanned_and_binary_skipped(tmp_path):
    text = cat("value = '", fake_jwt(), "'\n")
    (tmp_path / "a.txt").write_bytes(text.encode("utf-16"))
    (tmp_path / "b.bin").write_bytes(b"\x00\x01" + text.encode("utf-8"))
    assert [f.rule for f in scan_paths([tmp_path / "a.txt"], deny_terms=())] == ["jwt"]
    assert scan_paths([tmp_path / "b.bin"], deny_terms=()) == []


def test_deny_terms_from_file(tmp_path):
    deny = tmp_path / "deny.txt"
    deny.write_text("# local terms, never committed\nAcme Widgets\n\nre:proj[0-9]{2}\n", encoding="utf-8")
    terms = load_deny_terms(deny)
    assert terms == ["Acme Widgets", "re:proj[0-9]{2}"]
    assert rules("runs under /acme-widgets/oegem", deny_terms=terms) == ["deny-term"]
    assert rules("ACME_WIDGETS round", deny_terms=terms) == ["deny-term"]
    assert rules("the PROJ42 scenario", deny_terms=terms) == ["deny-term"]
    assert rules("acmewidgetsplus and project", deny_terms=terms) == []
    assert rules("runs under /acme-widgets/oegem") == []  # no list, no rule
    named = tmp_path / "acme_widgets_notes.md"
    named.write_text("nothing to see\n")
    assert [(f.rule, f.line) for f in scan_paths([named], deny_terms=terms)] == [("deny-term", 0)]


def test_own_files_are_clean():
    own = [Path(__file__), ROOT / "oegem" / "leakcheck.py", ROOT / "tools" / "check_confidential.py",
           ROOT / "tools" / "hooks" / "pre-commit"]
    assert scan_paths(own, deny_terms=()) == []


def test_hook_file_uses_lf_line_endings():
    data = (ROOT / "tools" / "hooks" / "pre-commit").read_bytes()
    assert data.startswith(b"#!/bin/sh\n") and b"\r" not in data


# ---- command line ----------------------------------------------------------------------

def test_main_exit_codes_and_output(tmp_path, capsys):
    clean = tmp_path / "clean.py"
    clean.write_text("x = 1\n")
    dirty = tmp_path / "dirty.py"
    dirty.write_text(cat("value = '", fake_jwt(), "'\n"))
    assert main([str(clean)]) == 0
    assert main([str(dirty)]) == 1
    out = capsys.readouterr().out
    assert "[jwt]" in out and RULES["jwt"] in out and fake_jwt() not in out
    assert main(["--no-such-option"]) == 2
    assert main([str(tmp_path / "missing.py")]) == 2
    assert main(["--staged", "--repo", str(tmp_path)]) == 2  # not a git repository
    assert main(["--deny", str(tmp_path / "missing.txt"), str(clean)]) == 2
    assert main(["--list-rules"]) == 0


def test_wrapper_script_runs_standalone(tmp_path):
    clean = tmp_path / "clean.py"
    clean.write_text("x = 1\n")
    dirty = tmp_path / "dirty.py"
    dirty.write_text(cat("value = '", fake_jwt(), "'\n"))
    script = ROOT / "tools" / "check_confidential.py"

    def run(*args):
        return subprocess.run([sys.executable, str(script), *args], cwd=str(tmp_path),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    assert run(str(clean)).returncode == 0
    result = run(str(dirty))
    assert result.returncode == 1 and b"[jwt]" in result.stdout
    assert run("--no-such-option").returncode == 2


# ---- git modes ---------------------------------------------------------------------------

def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=str(repo), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    return result.stdout.decode("utf-8", "replace")


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A fresh repository with its own git configuration (none of the user's)."""
    if not HAS_GIT:
        pytest.skip("git is not installed")
    config = tmp_path / "gitconfig"
    config.write_text("")
    for key, value in {
        "GIT_CONFIG_GLOBAL": str(config), "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "Unit Test", "GIT_AUTHOR_EMAIL": "unit@example.org",
        "GIT_COMMITTER_NAME": "Unit Test", "GIT_COMMITTER_EMAIL": "unit@example.org",
    }.items():
        monkeypatch.setenv(key, value)
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q")
    return path


def test_staged_mode_scans_the_index(repo):
    name = cat("ACCESS_TO", "KEN")
    settings = repo / "settings.py"
    settings.write_text(cat(name, " = '", fake_jwt(), "'\n"))
    (repo / "clean.py").write_text("x = 1\n")
    (repo / "results.csv").write_text("a,b\n")
    git(repo, "add", ".")
    settings.write_text("x = 2\n")  # the staged version still holds the value
    found = scan_staged(repo, deny_terms=())
    assert sorted((f.path, f.line, f.rule) for f in found) == [
        ("results.csv", 0, "forbidden-file"),
        ("settings.py", 1, "credential-assignment"),
        ("settings.py", 1, "jwt"),
    ]
    assert all(fake_jwt() not in f.excerpt for f in found)
    assert main(["--staged", "--repo", str(repo)]) == 1
    git(repo, "rm", "-q", "-f", "--cached", "settings.py", "results.csv")  # unstage, keep the files
    assert scan_staged(repo, deny_terms=()) == []


def test_default_deny_list_lives_in_the_git_dir(repo, tmp_path, monkeypatch):
    monkeypatch.delenv("OEGEM_DENY_FILE")
    info = repo / ".git" / "info"
    info.mkdir(exist_ok=True)
    (info / "oegem-deny.txt").write_text("# never committed\nAcme Widgets\n")
    (repo / "notes.md").write_text("Prepared for the acme widgets team.\n")
    (repo / "acme_widgets_run.py").write_text("x = 1\n")
    git(repo, "add", ".")
    found = scan_staged(repo)
    assert sorted((f.path, f.line, f.rule) for f in found) == [
        ("acme_widgets_run.py", 0, "deny-term"),
        ("notes.md", 1, "deny-term"),
    ]
    other = tmp_path / "other-deny.txt"
    other.write_text("prepared\n")
    monkeypatch.setenv("OEGEM_DENY_FILE", str(other))  # the variable wins over .git/info
    assert [(f.path, f.rule) for f in scan_staged(repo)] == [("notes.md", "deny-term")]
    empty = tmp_path / "empty-deny.txt"
    assert main(["--staged", "--repo", str(repo), "--deny", str(empty)]) == 0  # --deny wins
    assert main(["--staged", "--repo", str(repo)]) == 1


def test_history_mode_finds_a_removed_value(repo):
    name = cat("API_", "KEY")
    config = repo / "config.py"
    config.write_text(cat(name, " = '", FAKE_KEY, "'\n"))
    git(repo, "add", "config.py")
    git(repo, "commit", "-q", "-m", "add config")
    first = git(repo, "rev-parse", "HEAD").strip()
    config.write_text(cat(name, " = os.environ['OE_", name, "']\n"))
    git(repo, "add", "config.py")
    git(repo, "commit", "-q", "-m", "read the key from the environment")
    assert scan_tracked(repo, deny_terms=()) == []
    found = scan_history(repo, deny_terms=())
    assert [(f.path, f.line, f.rule) for f in found] == [("config.py", 1, "credential-assignment")]
    assert len(found[0].commits) == 1 and first.startswith(found[0].commits[0])
    assert FAKE_KEY not in found[0].excerpt
    assert main(["--history", "--repo", str(repo)]) == 1
    assert main(["--tracked", "--repo", str(repo)]) == 0


def test_pre_commit_hook_blocks_a_staged_token(repo, monkeypatch):
    # The hook runs the checker of the repository it guards, so copy it in.
    for rel in ("tools/check_confidential.py", "tools/hooks/pre-commit", "oegem/leakcheck.py"):
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(ROOT / rel), str(target))
    (repo / "tools" / "hooks" / "pre-commit").chmod(0o755)
    monkeypatch.setenv("OEGEM_PYTHON", Path(sys.executable).as_posix())
    git(repo, "config", "core.hooksPath", "tools/hooks")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "add the checker")  # clean, so the hook lets it through
    (repo / "settings.py").write_text(cat("value = '", fake_jwt(), "'\n"))
    git(repo, "add", "settings.py")
    result = subprocess.run(["git", "commit", "-q", "-m", "add settings"], cwd=str(repo),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output = (result.stdout + result.stderr).decode("utf-8", "replace")
    assert result.returncode != 0, output
    assert "[jwt]" in output and "Commit blocked" in output and fake_jwt() not in output
