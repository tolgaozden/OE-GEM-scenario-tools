# Confidentiality

The Global Economic Model is a licensed, confidential model. This repository holds code
and documentation only. Everything the model produces stays on your machine or in your
API workspace, and credentials stay in environment variables. This page lists what must
never be committed and the checks that help you keep to that.

## What never goes into the repository

| Never commit | Keep it here instead |
|---|---|
| credentials: tokens, passwords, API keys, the `OE_AUTH_*` values | environment variables (`OE_TOKEN`, `OE_AUTH_DOMAIN`, ...) |
| model output: fetched values, `results.csv`/`.xlsx`/`.parquet`, reports, charts, run manifests | `outputs/`, which git ignores |
| equations, coefficients, parameter tables, residual values | `outputs/equations/` (the default for `oegem equations`) |
| catalog dumps (indicator and group lists) | files under `outputs/` |
| release ids and forecast ids (UUIDs) | refer to releases by `latest:5yr` or a release name in configs |
| scenario files with levels derived from the baseline (`resolve: levels`, or `SET` commands with real levels) | the run folder, `outputs/<run_name>/scenarios/` |
| contact details of vendor staff (metadata tables, equation exports and run folders leave them out unless you pass `--keep-contacts` or `keep_contacts=True`) | your own address book |
| material specific to your institution: its name, internal project names, shared-folder paths, workbook names | your own notes, outside the repository |

What may be committed: code, documentation, configs with example mnemonics and round
shock sizes, and tests that build synthetic data in code.

## How the repository helps

1. `.gitignore` ignores `outputs/`, `.oegem_cache/`, the data and document formats (csv,
   xlsx, parquet, json, tex, html, pdf, png, svg and others), `*.3fs` files outside
   `examples/`, and credential files such as `.env` and `*.token`. Runs, reports and
   equation exports write under `outputs/` by default; keep it that way. `oegem init`
   puts a similar `.gitignore` into new projects. Because `*.json` is ignored, write your
   configs in YAML.
2. The leak checker scans text for credentials and for things that look like model
   content.
3. A pre-commit hook runs the leak checker on every commit.

## The leak checker

```bash
oegem check-leaks                    # tracked files inside a git repository, else the current folder
oegem check-leaks docs CONTRIBUTING.md   # these folders and files
oegem check-leaks --staged           # what the next commit would add (the hook runs this)
oegem check-leaks --tracked          # every tracked file
oegem check-leaks --history          # every version of every file in the git history
oegem check-leaks --list-rules       # the rules with one line each
```

`python tools/check_confidential.py` takes the same arguments. It loads the checker from
`oegem/leakcheck.py` with the standard library only, so it works before `pip install` and
inside the git hook. The exit status is 0 when nothing is flagged, 1 when something is,
and 2 for a usage error.

| Rule | Flags |
|---|---|
| `jwt` | JWT-like tokens (`eyJ...`) |
| `bearer` | `Bearer` followed by a token value |
| `credential-assignment` | a name such as password, secret, token, client_id or api_key set to a quoted literal; placeholders such as `<token>` and environment lookups pass |
| `auth-domain` | host names of identity-provider tenants |
| `email` | email addresses, except example.org/.com/.net and reserved test domains |
| `uuid` | UUIDs such as release or forecast ids; all-zero test values pass |
| `equation-like` | two or more `MNEM:GROUP` references and a number with 3 or more decimals on one line |
| `numeric-series` | six or more numbers with 3 or more decimals on one line |
| `forbidden-file` | files in output formats (csv, xlsx, json, pdf, png and others; `.3fs` outside `examples/`) |
| `large-file` | files over 500 KiB |
| `deny-term` | terms from your local deny list |

References to the fictional test codes (groups ALPHA and BETA, mnemonics such as AAA) do
not count toward `equation-like`. Folder scans skip `outputs/`, `.oegem_cache/`, `.git`
and virtual environments, and `forbidden-file` applies in the git modes and to files you
name. A file with a credential line and a deny-listed project name gives:

```text
leakcheck: 2 finding(s) in 1 of 1 file(s) (paths; deny list: 1 term(s))

  notes.md:2: [deny-term] project folder: Acme Widgets scenarios
  notes.md:3: [credential-assignment] OE_TOKEN = '***'
```

followed by one line per rule explaining what it means and how to fix the file. The
checker replaces flagged credential values with `***` in its own output.

## Install the hook

From the repository root, once per clone:

```bash
git config core.hooksPath tools/hooks
```

Before each commit the hook runs `python tools/check_confidential.py --staged` and blocks
the commit if anything is flagged. It looks for Python 3.9 or newer as `python3`, `python`
or `py`; set `OEGEM_PYTHON` to choose another interpreter. When it blocks a commit it
prints how to unstage a file, how to mark a false positive, and how to skip the check for
one commit (`git commit --no-verify`, for when you are sure).

## The local deny list

Some words are sensitive because of who you are: your organization's name, internal
project names, the names of shared folders. Listing them in the repository would publish
them, so the checker reads them from a file outside the tracked tree. It looks in this
order:

| Order | Location |
|---|---|
| 1 | the file given with `--deny FILE` |
| 2 | the file named in the `OEGEM_DENY_FILE` environment variable |
| 3 | `.git/info/oegem-deny.txt` in the repository (git never commits files under `.git`) |

One term per line; lines starting with `#` are comments. Matching ignores case and treats
spaces, hyphens and underscores alike, so `Acme Widgets` also finds `acme-widgets` and
`ACME_WIDGETS`. A line `re:<pattern>` is a regular expression. Terms are matched in file
contents and in file paths.

```text
# .git/info/oegem-deny.txt (example terms)
Acme Widgets
re:project[-_ ]?falcon
```

Create the file with any text editor. The summary line of each check shows how many terms
were loaded (`deny list: 2 term(s)`), or `deny list: none` when there is no list, in which
case the rule is skipped.

## False positives

Add the comment `leakcheck: allow` to the line. It silences every rule on that line, so
use it rarely and only where a reviewer can see why. In Markdown, an HTML comment at the
end of the line works: `<!-- leakcheck: allow -->`.

## If something leaked

1. If the commit has not left your machine, amend or reset it before you push.
2. If it reached a shared remote, rewrite the history to remove the content (for example
   with `git filter-repo`), force-push, and ask everyone with a clone to clone again.
   Hosting services can keep cached copies of old commits; ask the host to purge them.
3. Rotate exposed credentials: change a leaked password, and ask your account
   administrator to reissue leaked account settings. Tokens expire within about 24 hours;
   treat an exposed token as compromised until then.
4. If model content (equations, data, results) left your organization, tell your Oxford
   Economics account contact.
5. Scan the rest of the history: `oegem check-leaks --history`.
