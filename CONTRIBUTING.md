# Contributing

This repository holds code and documentation for a licensed, confidential model. Read
[docs/confidentiality.md](docs/confidentiality.md) before your first commit; the rules
below apply to every change.

## Development setup

```bash
# setup steps: they install packages and change git settings
git clone <repository-url> oegem
cd oegem
python -m venv .venv
.venv\Scripts\Activate.ps1          # PowerShell; Git Bash: source .venv/Scripts/activate; macOS/Linux: source .venv/bin/activate
pip install -e ".[dev,tls]"
git config core.hooksPath tools/hooks
```

`pip install -e` installs the package in editable mode, so code changes take effect
without a reinstall. The last line switches on the pre-commit hook that runs the leak
checker ([below](#confidentiality-rules)).

## Tests

```bash
python -m pytest -q                       # the whole suite, under a minute
python -m pytest -q tests/test_scenario.py
python -m pytest -q -k annual
```

The tests are offline. `tests/conftest.py` gives every test a `client` fixture
(`OEClient.demo()`, the synthetic backend) and a `release` fixture (the newest demo 5yr
release). No test may call the real API. The demo backend can inject failures and take
extra endpoints (`FakeSession.fail_next`, `FakeSession.add_route`):

```python
def test_server_error_is_retried(client):
    client.session.fail_next(503)               # the next request answers HTTP 503
    assert client.whoami()["Path"] == "/me"     # the client retries and succeeds
```

The MATLAB tests are offline too; a fake transport stands in for the network:

```matlab
cd matlab/tests
run_tests
```

## Confidentiality rules

- Test data is synthetic and generated in code. Do not copy files, numbers or catalog
  extracts from real runs into tests or fixtures.
- Tests use fictional codes: indicators such as AAA, BBB and CCC, groups ALPHA and BETA.
  The example mnemonics (GDP, CPI, RFED and the rest) belong in examples and docs only,
  always with the note to check them in your own catalog.
- Toy equations are written by hand, with numbers of at most 2 decimals, for example
  `0.5 * AAA:ALPHA[-1] + 0.25 * BBB:ALPHA + &AAA:ALPHA`. Never paste a real equation,
  not even a shortened one.
- Build sensitive-looking test strings at runtime, so that the source file passes the
  leak checker:

```python
import uuid

from oegem.demo import make_demo_token

token = make_demo_token()                   # JWT-shaped, unsigned, not a credential
forecast_id = str(uuid.uuid4())
address = "analyst" + "@" + "corp" + ".com"
```

- No credentials, release ids, workspace paths, organization or project names, or
  personal names anywhere: code, tests, docs, commit messages.
- Never commit outputs. Generated files go under `outputs/`, which git ignores.

The hook runs `python tools/check_confidential.py --staged` before each commit and blocks
the commit if anything is flagged. Run the same check by hand with
`oegem check-leaks --staged`. Put organization and project names in your local deny list,
`.git/info/oegem-deny.txt`, which is never committed
([format](docs/confidentiality.md#the-local-deny-list)). If the checker flags a test
string you built on purpose, add the comment `leakcheck: allow` to that line, and keep
such lines rare.

## Code style

| Topic | Rule |
|---|---|
| Python version | 3.9 syntax: `from __future__ import annotations` at the top of each module, no `match` statements |
| dependencies | runtime: requests, numpy, pandas, matplotlib, openpyxl, pyyaml; optional: truststore; dev: pytest. Discuss any new dependency first |
| docstrings | on every public function: one line on what it does, then the arguments and return value in short prose |
| comments | explain why, not what |
| output | library code logs through `logging.getLogger("oegem")`; only the CLI and examples print |
| errors | `OEError` (from `oegem.client`) for API failures; `ValueError` for bad input, with a message that says how to fix it |
| API functions | take the client as the first argument, as in `fetch(client, forecast_id, ...)` |
| data | pass data around as the long frame: columns forecast, indicator, group, period, freq, value, measure, in that order, sorted by forecast, indicator, group and period |
| periods | strings: `2026Q3`, `2026`; ranges `"2026Q3:2031Q4"` |

Union types written with `|` (PEP 604) are fine in annotations, which the `__future__`
import keeps as text, but not in code that runs, such as `isinstance` checks or type
aliases; use `Optional` and `Union` there.

## Adding a CLI command

The command line lives in `oegem/cli.py`.

1. Write a handler. It receives a `_Context` with the parsed arguments in `ctx.args`, the
   API client from `ctx.client()` (the demo client under `--demo`, created only when
   called) and the chosen release from `ctx.release()`. Return 0 on success and 1 when
   the command ran but found problems. Raise `ValueError` with a how-to message for bad
   input; `main()` turns any exception into one error line, a hint and exit status 2.

```python
def cmd_hello(ctx: _Context) -> int:
    """hello: print the release the other commands would use."""
    rel = ctx.release()
    _print(f"release: {rel.get('Name')}")
    return 0
```

2. Register it in `build_parser()` with the local `add()` helper. Shared parent parsers
   add common flags: `release` gives `--release` and `--root`, `out` gives `--out`.

```python
p = add(sub, "hello", cmd_hello, "print the release in use", parents=[release])
```

   For a command with actions, such as `scenario validate`, copy the pattern of the
   `scenario` or `workspace` blocks: `add_subparsers(dest=..., required=True)` plus a
   small dispatcher.

3. Use the helpers: `_emit(df, ctx.args.out)` prints a table or writes it in the format
   that the file extension names; `_note()` sends status lines to stderr; `_check_ext()`
   rejects an unsupported `--out` type before any API call.
4. Add the command to the list in the module docstring.
5. Add a smoke test to `tests/test_cli.py` that runs offline:

```python
from oegem.cli import main


def test_hello_runs_in_demo_mode():
    assert main(["--demo", "hello"]) == 0
```

6. Document the command in [docs/cli.md](docs/cli.md) and on the guide page it belongs
   to, and note it in [CHANGELOG.md](CHANGELOG.md). Update `README_PIPELINE.md` when a
   change adds or renames a pipeline step or an output.

## Before you push

- `python -m pytest -q` passes, and so does `run_tests` in MATLAB if you changed
  `matlab/`.
- `oegem check-leaks --staged` reports nothing.
- The docs describe any change a user can see.
