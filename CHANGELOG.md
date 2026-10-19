# Changelog

## 0.2.0 (2026-10-19)

First release of the general toolkit: the Python package `oegem`, the `oegem` command
line, a MATLAB mirror and the documentation set.

- **Releases**: list the release tree and pick a release by `latest`, `latest:5yr`,
  `latest:25yr`, name, path or forecast id (`oegem releases`, `releases resolve`).
- **Data**: fetch values of any release or solved forecast into one table layout, the
  long frame, with an automatic annual fallback for annual-only economies and
  whole-catalog fetches (`oegem data`); save and load CSV, Excel and parquet files.
- **Metadata**: units, scaling, history end, annualization method and base years per
  series (`oegem meta`, `oegem.metadata`); vendor contact fields and internal ids are left
  out by default.
- **Scenarios**: the `.3fs` command language, YAML scenario files with shock types,
  profiles, `FIX` windows and `include:` (also across files loaded in order), a Python
  builder, validation, and `oegem scenario validate`, `build`, `show` and `diff`.
- **Batch runs**: `oegem run` solves any number of scenarios from a run config, up to
  four at a time without threads, resumes after an interruption, retries taken output
  paths, can rewrite shocks as levels (`resolve: levels`), and writes a run folder with
  results, `manifest.json`, `metadata.csv` and the command files; `load_run` reads it
  back.
- **Reports**: measure chains (growth rates, annual averages, sums and end-of-year
  values, annualization by each series' own method, deviations), weighted aggregates, and
  report configs that write Excel, CSV, Markdown, HTML and a PDF chart book
  (`oegem report`), with forecast columns marked after the history end.
- **Charts**: paths, deviations, small multiples and chart books in a color-vision-safe
  palette, with the history end drawn and the forecast period shaded (`oegem plot`).
- **Model introspection**: catalog search and shock-variable lists; equation exports to
  Markdown, LaTeX, Excel and JSON; parameters by a documented heuristic; dependencies,
  reverse dependencies and Graphviz graphs; economy profiles with a heuristic class that
  points to likely satellite and annual-only economies (`oegem catalogue`, `equations`,
  `params`, `deps`, `profile`).
- **Release comparison**: two releases side by side with revision rows and notes on
  base-year changes (`oegem compare-releases`).
- **Workspace**: list, create, move, archive and delete folders and forecasts
  (`oegem workspace`).
- **Access**: token checks (`oegem auth status`), password login through your account's
  settings (`oegem auth token`), TLS through the operating system's certificate store
  behind proxies, and retries for dropped connections.
- **Demo mode**: a synthetic offline backend for every command and function (`--demo`,
  `OEGEM_DEMO=1`); its numbers are not model output.
- **Projects**: `oegem init` writes a starter run config, scenarios, report config,
  groupings and `.gitignore`.
- **Confidentiality**: a leak checker for credentials and model content
  (`oegem check-leaks`, `tools/check_confidential.py`) with a pre-commit hook and a local
  deny list.
- **Error messages**: one error line and a hint per failure, including hints for files
  open in Excel and Windows paths over 260 characters.
- **MATLAB**: functions for releases, catalog, data, solves, batch runs, transforms,
  tables and equations that read and write the same files as the Python package.
