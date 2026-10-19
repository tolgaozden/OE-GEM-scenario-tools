# Workspace

Solved scenarios are stored on the API side, in a folder tree called the workspace. The
`oegem workspace` commands and the functions in `oegem.resources` list, create, move,
archive and delete items there. Local files (results, reports) are covered in
[running-scenarios.md](running-scenarios.md) and [reporting.md](reporting.md).

## Paths

| Path | What it is |
|---|---|
| `/me` (also `me`) | your own area: you can create, move and delete items here |
| `/me/oegem-runs` | the default folder for solves started by `oegem run` |
| `<shared root>/...` | folders shared with colleagues; which ones you see depends on your account |
| `<shared root>/$Archive` | the archive folder of a shared area |
| `oxford-economics/releases/...` | the model releases; read-only |

Write paths with `/`. Spaces are fine (`.../Global Economic Model/...`): the toolkit
encodes each part of the path. A leading `/` is optional.

## Where runs put solved forecasts

`oegem run` saves each solved scenario as a new forecast at

```text
<output_folder>/<run_name>/<scenario>-<YYYYmmdd-HHMMSS>
```

With the starter config (`run_name: starter`, `output_folder: /me/oegem-runs`) the oil
scenario lands at `/me/oegem-runs/starter/oil_up_20-20261019-160608`. The runner creates
`<output_folder>/<run_name>` if it is missing. The timestamp (local time) keeps every
output path new, because the API does not write over an existing forecast; if a path is
taken anyway, the runner tries `<path>-2` and then `<path>-3`. The `manifest.json` file in
the local run folder records each scenario's workspace path and forecast id.

A single solve from Python (`oegem.solve.solve`) without `output_path` saves to
`<output_folder>/<name>-<timestamp>`, with `output_folder="/me"` unless you pass another.

## Commands

| Command | What it does |
|---|---|
| `oegem workspace ls [PATH] [--depth N] [--out FILE]` | lists a folder (default `/me`, one level deep) |
| `oegem workspace mkdir PATH [-p]` | creates a folder; `-p` also creates missing parent folders |
| `oegem workspace mv PATH NEW_PARENT` | moves a folder or forecast into another folder |
| `oegem workspace archive PATH ARCHIVE_FOLDER` | moves an item into an archive folder |
| `oegem workspace rm PATH --yes` | deletes a folder or forecast; this cannot be undone |

The examples below run against the demo workspace ([demo-mode.md](demo-mode.md)). Each
demo command starts from a fresh demo workspace, so a folder made by one command is gone
in the next.

```bash
oegem --demo workspace ls me --depth 2
oegem --demo workspace mkdir -p me/oegem-runs/tests/oil
oegem --demo workspace mv me/examples/demo-copy me
oegem --demo workspace archive demo-shared/team-scenarios/old-scenario 'demo-shared/team-scenarios/$Archive'
oegem --demo workspace rm me/examples/demo-copy --yes
```

Output of the first command:

```text
 depth      type      name                   path
     1 Directory  examples           /me/examples
     2  Forecast demo-copy /me/examples/demo-copy
```

Put paths that contain `$` in single quotes, in bash and PowerShell alike: inside double
quotes both shells read `$Archive` as a variable.

## Deleting and archiving

| Where the item is | Delete | Instead |
|---|---|---|
| `/me` | allowed; `oegem workspace rm` asks for `--yes` | |
| a shared folder | refused by the API | archive it |
| an archive or temporary folder of a shared area | allowed | |
| the release tree | refused | |

Deleting a shared item fails with HTTP 403, and the toolkit adds what to do (demo output,
shortened):

```text
error: DELETE https://oegem-demo.invalid/api/v1/resources/demo-shared/team-scenarios/old-scenario -> HTTP 403: ...
The API refuses to delete shared resources unless they sit in an archive or temporary folder. Move the item with archive(client, path, '<shared root>/$Archive') (CLI: oegem workspace archive) instead.
```

Because you cannot delete a shared forecast yourself, a test solve written to a shared
folder by mistake stays there until someone archives it. Solve new scenarios into `/me`
first. Point `output_folder` at a shared folder only for runs you mean to share, or move
finished forecasts there with `oegem workspace mv` if your account may write to that
folder.

`archive` first checks that the archive folder exists. Shared areas usually have one at
`<shared root>/$Archive`; if yours does not, someone with the rights has to create it
(`oegem workspace mkdir`).

## Python

```python
from oegem import OEClient
from oegem.resources import archive, delete, ensure_folder_tree, list_forecasts, make_folder, move, walk

client = OEClient.demo()        # OEClient() for live use
ensure_folder_tree(client, "/me/oegem-runs/tests")
make_folder(client, "/me/oegem-runs/tests/oil")
move(client, "/me/examples/demo-copy", "/me/oegem-runs/tests")
print(walk(client, "/me", max_depth=3)[["depth", "type", "path"]])
archive(client, "demo-shared/team-scenarios/old-scenario", "demo-shared/team-scenarios/$Archive")
delete(client, "demo-shared/team-scenarios/$Archive/old-scenario", confirm=True)
print(list_forecasts(client, "/me")[["name", "path"]])
```

Within one Python session the demo workspace keeps its changes.

| Function | What it does |
|---|---|
| `walk(client, path, max_depth=4)` | DataFrame of everything below `path`: name, path, type, id, depth, parent |
| `list_forecasts(client, path="/me", max_depth=3)` | the forecasts (not folders) below `path` |
| `exists(client, path)` | True or False |
| `make_folder(client, path, exist_ok=True)` | creates one folder; its parent must exist |
| `ensure_folder_tree(client, path)` | creates the folder and any missing parents |
| `move(client, path, new_parent)` | moves an item |
| `archive(client, path, archive_folder)` | moves an item into an archive folder |
| `delete(client, path, confirm=False)` | deletes an item; needs `confirm=True` and refuses the root `/me` |

## Git Bash rewrites /me

Git Bash on Windows turns command-line arguments that start with `/` into Windows paths.
`/me` then reaches the toolkit as `C:/Program Files/Git/me`, and the API answers 404:

```text
error: GET https://oegem-demo.invalid/api/v1/resources/C%3A/Program%20Files/Git/me -> HTTP 404: Resource /C:/Program Files/Git/me not found (not found: check the path, id or mnemonic)
```

Leave out the leading slash, or switch the rewriting off for the command:

```bash
oegem --demo workspace ls me
MSYS_NO_PATHCONV=1 oegem --demo workspace ls /me
```

PowerShell and cmd do not rewrite arguments, and paths inside YAML files are never
affected.
