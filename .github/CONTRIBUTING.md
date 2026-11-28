# Contributing

## Writing documentation

Each part of Jaadah has one document in `docs/`, listed in [`docs/README.md`](../docs/README.md).

- **Shape:** a title in sentence case, then a paragraph on what the part does and why. Then, where they apply: *How to run it*, *How it works*, *Files*, *Limitations and open points*. At most three heading levels.
- **Section numbers** only in long reference documents that others cite by number, such as `kpi_engine.md` and `data_models.md`. Keep existing numbers, because other files cite them, for example `kpi_engine.md` section 17.11.
- **Spelling:** American English: color, modeled, labeled, signalized, meters.
- **Names:** the *RCRC traffic feed*, though describing it as replaying the RCRC report is fine. The *SUMO simulation*, never "model", which is kept for the AI parts. The pages as the navigation bar names them: Network Traffic Overview, Current Traffic, Traffic Forecast, Traffic Patterns & Trends, Alerts.
- **Commands:** run from the repository root with `python -m …`, in PowerShell blocks. Add the macOS line only where it differs.
- **Time:** name the release, as in "in Release 1" or "planned for Release 2", instead of "currently" or "not yet", which go out of date.
- **No parentheses in prose:** work the aside into the sentence instead.
- **Links:** relative, to files and headings that exist. CI checks every link in the README and in `docs/`.
- **New documents** get a row in the table in `docs/README.md`.
