# Troubleshooting

Find the message you see in the first column. Add `-v` to any command for more detail,
or `-vv` for a full traceback. Exit status 0 means success, 1 that the command ran but
found problems (a failed solve, a file that does not parse, an expired token), and 2 a
usage, input or API error.

## Access and connection

| Symptom | Cause | Fix |
|---|---|---|
| `No Oxford Economics API token found in the OE_TOKEN environment variable.` | `OE_TOKEN` is not set in this terminal; each terminal has its own environment | set it ([getting-started.md](getting-started.md#set-your-api-token)), or try the command with `--demo` |
| `TLS certificate verification failed (... CERTIFICATE_VERIFY_FAILED ...)` | a corporate proxy re-signs encrypted traffic with a certificate Python does not trust, or the strict checks of Python 3.13 and newer reject the proxy's certificate | `pip install truststore` (or the `tls` extra) and leave `OE_TLS` unset; if that fails, set `OE_TLS=relaxed`. Certificates are checked in every mode ([TLS](getting-started.md#tls-behind-a-corporate-proxy)) |
| `OE_TLS=truststore needs the truststore package` | `OE_TLS=truststore` without the package | `pip install truststore`, or unset `OE_TLS` |
| `Unknown TLS mode '...'` | a typo in `OE_TLS` | use `auto`, `truststore`, `relaxed` or `default` |
| `HTTP 401 ... (token missing, invalid or expired ...)` | the token expired (tokens last about 24 hours) or was pasted incompletely | set a fresh `OE_TOKEN`; `oegem auth status` shows the expiry |
| `HTTP 403 ... (your account is not allowed to do this on this resource)` | no rights on that folder or release, a write into the release tree, or a delete in a shared folder | check the path with `oegem workspace ls`; write to `/me`; archive shared items instead of deleting them ([workspace.md](workspace.md)) |
| `HTTP 404 ... (not found: check the path, id or mnemonic)` | a wrong path, release name or forecast id; a parent folder that does not exist; `/me` rewritten by Git Bash | check with `oegem releases` and `oegem workspace ls`; create parents with `oegem workspace mkdir -p`; see the Git Bash row below |
| `WARNING: ...: ConnectionError ...; retrying in 2.0 s (attempt 2 of 6)` | a dropped connection or a timeout, often at a proxy, or a busy server (HTTP 429, 502, 503, 504) | nothing to do: the client retries up to 5 times, waiting 2, 4, 8, 16 and 32 seconds, and follows the server's `Retry-After` |
| `... failed after 6 attempt(s): ...` | the problem lasted through all retries | try again later. In Python, `OEClient(retries=..., backoff=..., timeout=...)` sets the number of retries, the first wait and the per-request timeout (180 s by default) |
| `Password login needs OE_AUTH_DOMAIN and OE_AUTH_CLIENT_ID` | `oegem auth token` without the identity-provider settings | set them from your account setup ([getting-started.md](getting-started.md#optional-log-in-with-a-password)) |

## Solves

| Symptom | Cause | Fix |
|---|---|---|
| `HTTP 409` when a solve is submitted | the output path exists already; the API does not write over a forecast | let the toolkit choose the path (it adds a timestamp). `oegem run` retries with `-2` and `-3` by itself; with `solve(..., output_path=...)`, pick a new path |
| the run table shows `Failed` and a failure text; exit status 1 | the model could not apply or solve the commands; the text is the operation's `FailureReason` (or `Error`, `Message`) | read the failure text, which is also in `manifest.json`; run `oegem scenario validate FILE --catalogue`; check that the shocked periods fall inside the solve range and that annual-only economies get years. Fix the scenario and run again: scenarios that already succeeded are not solved twice |
| `Still InProgress after ... s; check operation ... later` | the solve did not finish within `timeout_seconds` (3600 by default) | look for the output forecast later with `oegem workspace ls`; raise `solve.timeout_seconds` in the run config |
| `Lost contact with solve '...' (operation ..., output ...); it may still be running, so check it before resubmitting` | the connection broke while the toolkit waited for a submitted solve | look for the output path with `oegem workspace ls`; if the forecast is there, the solve ran. Solve requests are never retried automatically, so one request never starts two solves |

## Data

| Symptom | Cause | Fix |
|---|---|---|
| `no values returned: check the codes ... and the period range.` | the mnemonic or group is not in this release, or the period range lies outside the data | `oegem catalogue search <text>`; widen `--from` and `--to` |
| an economy's series have annual periods only, or are missing | the economy is annual-only, and it returns nothing at the default frequency | keep the annual fallback on (the default); `--no-annual-fallback` or `annual_fallback: false` switches it off. Use years in that economy's scenario commands |
| `Parquet files need a parquet engine ...` | no parquet library is installed | `pip install pyarrow`, or write `.csv` or `.xlsx` |

## Files and shells

| Symptom | Cause | Fix |
|---|---|---|
| `error: cannot write or read ...xlsx: permission denied`, with the hint to close the file | the workbook is open in Excel, which locks it on Windows | close it and run the command again. `oegem run` records each finished solve in `manifest.json` as it goes, so the second run fetches the results without solving again |
| `HTTP 404: Resource /C:/Program Files/Git/me not found` | Git Bash turned `/me` into a Windows path | write `me/...` without the slash, or put `MSYS_NO_PATHCONV=1` before the command ([workspace.md](workspace.md#git-bash-rewrites-me)) |
| `could not parse YAML: ...` | wrong indentation, a tab character, or an unquoted special value | check the indentation and quote period ranges, for example `"2026:2030"` |
| `file not found: ...` | a relative path that starts from another folder | paths typed on the command line start from the current folder; paths inside a config file start from that file's folder |
| `file not found: ...` on Windows, for a file the toolkit writes itself (for example `...\scenarios\oil_up_20.3fs`), with the hint `the full path is over Windows' 260-character limit` | the full path is 260 characters or more, the Windows default limit; deeply nested synced or network folders reach it | move the project to a shorter folder, such as `C:\work\my_project`, or turn on long path support in Windows. Run and report configs already fold `..` segments in their relative paths, which keeps paths shorter |

Still stuck? Run the same command with `--demo`. If it works there, the problem is in
access, rights or the real data; if it fails there too, the problem is in your files or
command line.
