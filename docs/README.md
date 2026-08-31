# Documentation

Start with the repository [README](../README.md). It explains the methodology,
runtime data flow, prerequisites, installation, configuration, first run, and
the warnings that matter before enabling enforcement.

Use the guides below when you need more detail. Each page has one primary
responsibility so the same contract does not need to be maintained in several
places.

| Guide | What it owns |
|---|---|
| [User guide](user-guide.md) | Day-to-day session controls, modes, access groups and presets, temporary goal access, breaks, agentic mode, the dashboard, and `/status` |
| [Architecture](architecture.md) | Components, runtime data flow, scheduler loops, locking, policy reconciliation, monitoring contexts, feedback queues, and persistence boundaries |
| [Privacy and data](privacy-and-data.md) | What is captured or uploaded, OpenAI requests and retention considerations, local artifacts, speech backends, cleanup, and cost drivers |
| [Troubleshooting](troubleshooting.md) | UAC, hosts cleanup, DNS and browser behavior, port conflicts, startup failures, state recovery, and known operational limitations |
| [Verification](verification.md) | Automated checks and the full manual verification matrix |
| [Dashboard startup](startup.md) | The narrow server-bind, readiness-probe, and optional browser-opening contract |
| [Verdict corrections](verdict-corrections.md) | Latest-verdict correction UI, HTTP fields, accounting, event ordering, feedback, and focused checks |
| [Repository operating guide](../AGENTS.md) | Code-sensitive invariants, implementation constraints, verification expectations, and the GitHub workflow for maintainers and coding agents |

## Documentation ownership

Keep clone-to-first-session instructions and the short architecture graph in
the top-level README. Put operational instructions in the user guide, internal
design and module ownership in the architecture guide, data-handling claims in
the privacy guide, test procedures in the verification guide, and contributor
rules in `AGENTS.md`. Link to the canonical section instead of copying it.

When behavior changes, check executable code and focused tests first, then
`.env.example`, `pyproject.toml`, and `uv.lock`, before updating the owning
guide. External platform claims should be checked against current primary
documentation.
