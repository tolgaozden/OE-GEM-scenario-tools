# API notes

The toolkit talks to the GEM web API at `https://model.oxfordeconomics.com/api` (the
`OE_BASE_URL` variable changes the address). The API has no public documentation. These
notes record the requests the toolkit sends and the replies it expects, as learned from
working code, so that they can be checked with the vendor or adapted if the API changes.
The [demo backend](demo-mode.md) answers with the same shapes.

## Every request

- Headers `Authorization: Bearer <token>`, with the token from `OE_TOKEN`, and
  `Accept: application/json`. Logs and error messages never contain the token: the
  toolkit replaces it, and anything that looks like a token, with `***`.
- Replies may start with a UTF-8 byte-order mark (BOM). The toolkit decodes the raw bytes
  and strips the mark before parsing JSON; `response.json()` in requests would fail on it.
- Resource paths are percent-encoded one segment at a time, keeping the slashes:
  `Global Economic Model` becomes `Global%20Economic%20Model` and `$Archive` becomes
  `%24Archive`.
- Dropped connections, timeouts and HTTP 429, 502, 503 and 504 are retried with
  exponential backoff (5 retries by default). Any other status outside 200-299 raises
  `OEError` with the status, the URL and the first 800 characters of the reply.

## Endpoints

| Request | Body | Reply | Used for |
|---|---|---|---|
| `GET /v1/resources/<path>` | | resource dict, with `Children` for folders | release tree, workspace listing |
| `GET /v1/resources/me` | | your workspace root | `oegem auth status` |
| `GET /v1/forecast-contents/<forecastId>` | | forecast summary (`Id`, `Name`, `Path`) | looking up a forecast id |
| `GET /v1/forecast-contents/<forecastId>/indicators` | | list of `{Code, Name, ...}` | catalog |
| `GET /v1/forecast-contents/<forecastId>/groups` | | list of `{Code, Name, Type, ...}` | catalog |
| `POST /v1/forecast-contents/<forecastId>/variables?onlyProps=Values` | list of selections | values per selection | data, runs, reports |
| `POST /v1/forecast-contents/<forecastId>/model-variables?onlyProps=Equations,Residuals,Metadata` | list of selections | equations, residuals and metadata per selection | equations, parameters, dependencies |
| `POST /v1/operations/solve` | solve request | operation `{Id, Status, ...}` | solves |
| `GET /v1/operations/<Id>/await` | | operation, after a long poll | waiting for a solve |
| `GET /v1/operations/<Id>` | | operation | waiting for a solve, when `/await` fails |
| `PUT /v1/resources/<new path>` | folder definition | the new folder (status 200 or 201) | `oegem workspace mkdir` |
| `PATCH /v1/resources/<path>` | `{"Directory": "<new parent path>"}` | the moved item | `mv`, `archive` |
| `DELETE /v1/resources/<path>` | | empty | `rm` |

## Resources

`GET /v1/resources/<path>` returns a dict with `Id`, `Name`, `Path`, a type in `Type` or
`ResourceType` (`Directory` for folders) and, for folders, a `Children` list of dicts with
the same keys. The toolkit also accepts children listed under `Items` or `Resources`.
`me` (or `/me`) is your workspace root.

The release tree starts at `oxford-economics/releases/Global Economic Model`. Current
releases sit in `Extension/<name>`, with names of the form `MonYY_n <horizon>` (month,
two-digit year, release number within the month, forecast length such as `5yr`). Older releases
sit under `Extension/Previous releases/<YYYY-MM_n>/<name>`. Other models may sit elsewhere
under `oxford-economics/releases/`. The toolkit walks the tree, 4 levels deep by default,
instead of assuming a fixed layout.

## Catalog

`.../indicators` returns a list of `{Code, Name, ...}` and `.../groups` a list of
`{Code, Name, Type, ...}`. Other scalar fields become extra columns. In the groups list
`Type` is "Normal" for every entry, so it does not tell annual-only or satellite
economies apart.

## Values

Body: a list of selections, at most 400 per request. The toolkit splits larger requests
into batches of 400.

```json
[
  {"IndicatorCode": "GDP", "GroupCode": "US"},
  {"IndicatorCode": "GDP", "GroupCode": "BETA", "Frequency": "Annual"}
]
```

Reply (numbers illustrative):

```json
[
  {"IndicatorCode": "GDP", "GroupCode": "US",
   "Values": [{"Period": "2026Q1", "Value": 100.0}, {"Period": "2026Q2", "Value": 101.0}]}
]
```

Values are levels. Quarterly periods look like `2026Q1`. Annual period labels contain a
four-digit year, but the format varies (the demo uses `2026-01-01T00:00:00`); the toolkit
keeps the first four-digit year of any label without a `Q`.

Annual fallback: an annual-only economy returns no values at the default frequency. The
toolkit requests every pair that came back empty a second time, with
`"Frequency": "Annual"`, and logs how many series fell back (visible with `-v`).
`annual_fallback=False` in Python, or `--no-annual-fallback` on the command line, turns
this off.

## Equations, residuals and metadata

The model-variables request takes the same body as the values request. Each reply item
has `IndicatorCode`, `GroupCode`, `Equations`, `ResidualType` (`Additive`,
`Multiplicative`, or empty for a variable without an equation), `Residuals` (a list of
`{Period, Value}`) and `Metadata` (a dict).

`Equations` comes in several shapes: a string, a list of strings, a dict, or a list of
dicts. The toolkit takes the text from the first of the keys `Equation`, `Definition`,
`Expression`, `Formula` and `Text` that it finds, and otherwise keeps the JSON text.

Equation syntax, shown with a toy equation and fictional codes:

```text
0.5 * AAA:ALPHA[-1] + 0.25 * BBB:ALPHA - 0.1 * CCC:ALPHA[+1] + 2 + &AAA:ALPHA
```

| Element | Meaning |
|---|---|
| `AAA:ALPHA` | variable AAA of group ALPHA |
| `[-1]`, `[+1]` | lag and lead, in periods |
| `&AAA:ALPHA` | the residual of AAA's equation |
| `LN`, `LOG`, `EXP`, `DLOG`, `DIFF`, `D`, `S(x, n)` | functions; others occur |
| `+ - * / ^` and parentheses | operators |

There is no parameters endpoint: coefficients are the numbers written in the equation
text. `oegem params` extracts them with a heuristic parser
([model-introspection.md](model-introspection.md)).

Field names seen in `Metadata`:

| Kind | Fields |
|---|---|
| description and source | `Description`, `GroupName`, `Source`, `OriginalSourceProvider` |
| units and scale | `Unit`, `Units`, `Scaling`, `ScaleFactor`, `BaseYearIndex`, `BaseYearPrice` |
| history | `HistoryEnd`, `DerivedHistoryEnd` |
| properties | `AnnualizationType`, `IsSeasonallyAdjusted`, `IndicatorProperties` |

The replies also carry contact fields and internal id fields. The toolkit drops them from
its tables and exports unless asked to keep them (`oegem meta --keep-contacts`, or
`keep_contacts=True` in `oegem.metadata.metadata` and `oegem.equations.equations`).

## Solves

Request (`InputForecast` is the `Path` of the release or forecast, as the resources
endpoint returns it):

```json
{
  "InputForecast": "<Path of the release or forecast>",
  "SolutionRange": {"From": "2026Q3", "To": "2031Q4"},
  "Commands": "MULTIPLY WPO_EQN:WORLD 2027Q1 1.2, 1.2, 1.2, 1.2\nFIX WPO_EQN:WORLD 2027Q1:2027Q4",
  "OutputForecast": "/me/oegem-runs/starter/oil_up_20-20261019-160608"
}
```

The reply is an operation `{Id, Status, ...}`, normally with `Status` `Queued`.

1. Poll `GET /v1/operations/<Id>/await` (a long poll) while `Status` is `Queued` or
   `InProgress`. If `/await` fails, the toolkit switches to `GET /v1/operations/<Id>`
   every 10 seconds.
2. The final `Status` is `Succeeded`, or anything else with the reason in
   `FailureReason` (or `Error`, `Message`).
3. On success, `GET /v1/resources/<OutputForecast>` returns the new forecast and its `Id`.

Solves take a minute or two. The output path must be new: the API does not write over an
existing forecast, and the toolkit treats HTTP 409 as that case. The solve request is
sent once and never retried, because a repeated request could start a second solve.

## Folders

| Action | Request | Body |
|---|---|---|
| create | `PUT /v1/resources/<full new path>` | `{"Name": "<last segment>", "ResourceType": "Directory", "Type": "Directory"}` |
| move | `PATCH /v1/resources/<path>` | `{"Directory": "<new parent path>"}` |
| delete | `DELETE /v1/resources/<path>` | none |

Deleting works in your own area. On shared resources the API refuses it unless the item
sits in an archive or temporary folder; archiving is a move into `<shared root>/$Archive`
([workspace.md](workspace.md)).

## Open points to confirm with Oxford Economics

| Topic | Question | What the toolkit does now |
|---|---|---|
| stacked commands | how two value commands on the same variable and period combine: applied in order, or only the last one | sends them as written; `validate()` warns; the demo applies them in order |
| `INCREASE` on variables | whether `INCREASE VAR` (without `&`) adds to the input-forecast values in every case | assumes it does; `resolve: levels` sends `SET` levels instead |
| `MULTIPLY` on residuals | whether `MULTIPLY &VAR` scales a multiplicative residual as intended | sends it as written |
| annual period labels | the exact format, and whether it is stable | keeps the first four-digit year |
| `Equations` payload | which shapes occur and which key holds the text | tries the known keys, else keeps the JSON text |
| release tree depth | whether the layout under the release root is fixed, and whether other model families follow it | walks the tree, 4 levels by default |
| output paths | the status for an existing output path, and whether two solves submitted at the same moment can claim the same path | adds a timestamp; tries `-2` and `-3` after HTTP 409 |
| annual-only and satellite economies | there is no documented flag; the groups list has `Type` "Normal" for every entry | detects annual-only economies by the empty quarterly reply |
| changing parameters | whether coefficients can be changed through the API | no support |
| parameters endpoint | there is no structured endpoint for coefficients | reads the numbers from the equation text |
