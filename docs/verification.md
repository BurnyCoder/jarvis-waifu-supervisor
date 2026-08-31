# Verification guide

Use the smallest verification path that can observe the changed behavior, then
run the complete automated suite. Hardware-free tests are not an end-to-end
claim, `--smoke` is not a dashboard or enforcement test, and `--dry-hosts` is
not a harmless simulation after a session starts.

## Verification levels

| Command | What it exercises | What it does not prove |
|---|---|---|
| `uv run python main.py --help` | CLI parsing/import boundary | Configuration, UAC, app wiring, hardware, API, server, or enforcement |
| `uv run pytest` | Fake/injected state, policy, storage, scheduler, Flask, startup, and adapter contracts using temporary paths | Real Windows hosts permissions, Defender, physical capture devices, network/model behavior, browser integration, or audible playback |
| `uv run python main.py --smoke` | One real screen/webcam composite, persistence, one first-capture productivity request, accepted verdict path, and queued speech | Flask, readiness/browser opening, scheduler-loop cadence, real hosts writes, app killing, agent watching, or rolling comparison from capture two |
| `uv run python main.py --dry-hosts` | Full dashboard and scheduler with hosts apply/clear replaced by logging | Real hosts-file writes, DNS cache behavior, UAC, or website blocking |
| `uv run python main.py` | Full local runtime, including UAC, hosts enforcement, app killing, capture/API/TTS, and UI | Behavior on every Windows/device/network/model combination; inspect evidence rather than calling one run flawless |
| `Start Deep Work.bat` | Launcher elevation and readiness-gated browser flow | Any behavior not reached after the dashboard loads |

After Start, `--dry-hosts` still kills configured apps, captures and uploads
monitor/webcam images, makes API calls, writes artifacts, and plays speech.
`--smoke` also uploads a real capture and can call text generation and OpenAI
speech depending on the verdict and `TTS_ENGINE`.

## Reproducible automated baseline

From a fresh clone on Windows:

~~~powershell
uv sync --locked
uv lock --check
uv run pytest
uv run python main.py --help
~~~

`uv sync --locked` creates the repository-local `.venv` from `uv.lock` and
refuses to update an inconsistent lock. `uv lock --check` checks that project
metadata and the lock agree without modifying either; see uv's
[locking and syncing documentation](https://docs.astral.sh/uv/concepts/projects/sync/).

The full pytest suite should make no administrator, OpenAI, hardware, browser,
or audio request. It injects collaborators or uses temporary files around
those boundaries. A failure must be investigated rather than papered over by
running only a narrower selection.

## Documentation-only reconciliation

Documentation changes still need the reproducible baseline above because
imports, lock metadata, command names, and test counts are documentation
claims. When source comments in state or logging are also touched, run the
focused checks before the full suite:

```powershell
uv run pytest tests/test_state.py tests/test_logging_setup.py
uv run pytest
git diff --check
git check-ignore -v .env logs/ results/
```

Review the rendered README on GitHub, including its Mermaid graph, tables,
admonition, and attachment images. Follow every changed relative link and
heading anchor. Compare each setup/default/runtime statement with executable
code, focused tests, `.env.example`, `pyproject.toml`, and `uv.lock`; compare
external service or library claims with current primary documentation.

## Focused automated matrix

Run a focused test first while developing, then run `uv run pytest` before
handoff.

| Area | Focused command |
|---|---|
| Configuration, catalog, and presets | `uv run pytest tests/test_config.py tests/test_access_policy.py` |
| Hosts and exact-name process adapters | `uv run pytest tests/test_hosts_blocker.py tests/test_app_killer.py` |
| Capture conversion, stitching, and analyzer requests | `uv run pytest tests/test_capture_stitch.py tests/test_analyzer.py` |
| Message generation and speech queue | `uv run pytest tests/test_feedback.py` |
| State, accounting, and concurrency | `uv run pytest tests/test_state.py` |
| Scheduler loops, context changes, expiry, and retry | `uv run pytest tests/test_scheduler.py tests/test_runtime_status.py` |
| Flask routes and status contract | `uv run pytest tests/test_webui.py` |
| Shared picker and safe rendering | `uv run pytest tests/test_unified_picker_ui.py` |
| Startup, CLI, launcher, and browser readiness | `uv run pytest tests/test_main.py tests/test_launcher.py tests/test_webui_server.py` |
| Logging and artifacts | `uv run pytest tests/test_logging_setup.py tests/test_storage.py` |

The fake-blocker tests—not a manual UI run—cover a failed hosts reconciliation,
HTTP 503 on affected mutating routes, `reconciliation_pending`, and the
enforcer applying only the newest policy on retry. Storage/scheduler/web tests
similarly cover ordered JSONL retry and feedback gating without inducing a real
disk failure.

For a behavior change, preserve the repository's TDD order:

1. Add or adjust the focused test and observe the intended failure.
2. Implement the smallest behavior change.
3. Rerun the focused test.
4. Run the complete suite.
5. Exercise the affected real path below when it crosses an OS, hardware,
   browser, network, model, or speech boundary.

## Prepare a manual run

Manual checks can expose sensitive data and abruptly terminate applications.

1. Use a non-sensitive desktop and API project. Close secrets and private
   content on every monitor and decide whether camera index `0` may be captured.
2. Save work and close Discord, Telegram, and Steam unless the test explicitly
   needs one. The app killer uses abrupt termination.
3. Stop every other Deep Work instance. Hosts and state files have no
   cross-process lock.
4. Back up the Windows hosts file before a real enforcement check and inspect
   any existing Deep Work markers. Follow
   [stale-fence recovery](troubleshooting.md#a-stale-hosts-block-remains-after-exit)
   before real mode if the markers are unpaired.
5. Record temporary `.env` values. Use positive intervals; nonpositive values
   are not safely range-validated.
6. Know where evidence will appear:
   `logs/`, `results/captures/`, `results/llm/`,
   `results/sessions/`, `results/state.json`, and `/status`.
7. Read [Privacy, data, and cost](privacy-and-data.md). Neither
   `--dry-hosts` nor `--smoke` is a privacy-safe mode.

## Dashboard readiness

Choose an unused, non-default `UI_PORT` and run without starting a session:

~~~powershell
uv run python main.py --dry-hosts --open-browser
~~~

Confirm:

1. Exactly one tab opens at the configured loopback port without a manual
   refresh or a connection-refused page.
2. The terminal and newest log show this order:

   ~~~text
   control panel listening: http://127.0.0.1:<UI_PORT>
   waiting for dashboard readiness: http://127.0.0.1:<UI_PORT>/status
   dashboard ready: ... returned HTTP 200
   opened control panel in the default browser: ...
   ~~~

3. A direct terminal run without `--open-browser` opens no tab and the logged
   URL works manually.
4. Ctrl+C stops the server. A readiness or browser-launch failure should log
   the manual URL without stopping a successfully bound server.

The focused automated server tests cover bind failure, retry, timeout,
cancellation, false/raising browser integration, and final socket closure.
The detailed sequence lives in [Dashboard startup](startup.md).

## Real one-capture pipeline

`--smoke` is the shortest real capture/API check:

~~~powershell
uv run python main.py --smoke
~~~

Before running it, make every monitor and the camera safe to upload. Then
confirm:

1. The terminal and newest log show monitor count, camera success or a
   non-fatal failed-read warning, capture persistence, progress-window
   `(1/N)`, the complete prompt, structured output, and one speech queue entry.
2. The newest `results/captures/*.jpg` is a 960-pixel-wide labeled composite
   containing every expected panel and no unexpected sensitive content.
3. The newest `results/llm/*_vision.json` contains the complete first-capture
   prompt, a capture-file reference rather than base64, `detail="original"`,
   and the full successful response.
4. The prompt uses topic `smoke test`, no task or goal groups, and the
   single-capture rule. Its reason may affirm current engagement but must not
   invent chronological progress.
5. The run starts no listening server, scheduler-loop threads, real hosts
   writes, app kill sweep, agent-watch tick, `session_start` event, or
   good-luck message.
6. Registered shutdown still performs a dry reconciliation and persists
   `smoke test` in previous-topic state.

If the verdict calls for a nudge or 30-minute praise, a text-message exchange
can also appear. With `TTS_ENGINE=openai`, an utterance becomes a Speech API
call; with pyttsx3 only synthesis/playback is local.

## Rolling productivity comparison

Smoke cannot test this branch. Use a normal dashboard session with a positive
short test interval, for example:

~~~dotenv
CAPTURE_INTERVAL_S=60
PROGRESS_WINDOW_CAPTURES=5
~~~

Run `uv run python main.py --dry-hosts`, start one session, and keep its topic,
task groups, goal access, mode, and agent state unchanged through two
successful monitor ticks. Close configured distraction apps first because the
real app killer remains active.

Inspect the second successful `*_vision.json` and confirm:

- the header says `COMPARISON (2/5)`;
- two capture references appear oldest first;
- each image uses `detail="original"`;
- corresponding monitor/webcam panels are compared using evidence relevant to
  the stated task;
- playback bars, clocks, cursors, webcam lighting, and unrelated animation are
  not treated as work progress;
- the second accepted verdict credits
  `max(1, CAPTURE_INTERVAL_S // 60)` minutes, not the whole rolling window.

A context change during capture should avoid persistence/model work for that
capture. A context change during save or inference can leave local/OpenAI
artifacts but must return `context_changed` without accepting a verdict,
event, or speech. A failed analysis may remain in the analyzer window; for a
deterministic two-capture inspection, ensure both requests succeeded.

Restore normal `.env` values after the check.

## Session, access, break, and status flow

Use `--dry-hosts` for state/UI behavior, while remembering that app enforcement
and capture/API/TTS remain real after Start.

1. Confirm Start, temporary goal access, and Break render the same 14 ordered
   group choices: one Discord **Web + App** choice, Telegram and Steam **App**,
   and 11 **Web** choices.
2. Start a session with one-off `discord` and `telegram` access. If a
   `projects.json` preset is being tested, choose it too.
3. Inspect `/status`. `work_access.selected_groups` should show the one-off
   choices; `allowed_groups` should show the preset union;
   `allowed_sites` should include Discord but not Telegram; `allowed_apps`
   should include both.
4. Start a timed goal grant for one web and one app group. Confirm mode stays
   ON, monitoring continues, social allowance is unchanged, countdown fields
   are present, and start/end events retain the complete goal and canonical
   plus derived access arrays.
5. Start a BREAK with a different group. Confirm permanent task groups remain
   allowed, the whole goal grant reports `suspended: true`, goal-only app
   permission disappears, break-only permission appears, monitoring pauses,
   and the goal's wall-clock timer continues.
6. End the break before the goal expires. Confirm only break permission is
   removed and the unexpired goal resumes. Let a separate grant expire and
   confirm the first later enforcer tick closes it.
7. For a positive `social_media` break, confirm the full requested duration is
   reserved at start. Manual stop charges each started minute and refunds the
   rest; natural expiry keeps the full reservation. Use valid dashboard values:
   purpose, 1–240 minutes, and exact `away` or `social_media`.
8. Submit the wrong Disable phrase and confirm HTTP 403/state remains active.
   Submit the exact displayed phrase and confirm state becomes OFF.

The automated route suite, rather than forged manual input, is the canonical
check for strict `allowed_groups` rejection, legacy-field rejection,
idempotency, malformed goal forms, and concurrency. The current incomplete
server validation for break duration/kind/purpose is a documented limitation,
not an acceptance target.

At each step check that `/status` is JSON-safe, additive, and served with
`Cache-Control: no-store`. LLM text must remain escaped/text-rendered.

## Real Windows enforcement

This phase requires UAC and can disrupt browsing and applications:

~~~powershell
uv run python main.py --open-browser
~~~

After Start:

1. Inspect `C:\Windows\System32\drivers\etc\hosts`. It should contain one paired
   Deep Work fence. Unpermitted configured domains should have both
   `127.0.0.1` and `::1` lines; a permitted website group should be omitted.
2. Run `ipconfig /flushdns`, then use
   `[System.Net.Dns]::GetHostAddresses("reddit.com")` (substituting the
   unpermitted configured hostname under test) and the actual browser.
   Browser-specific secure DNS and caches can bypass the Windows resolver, so
   record both results.
3. With saved work and disposable app state, confirm an unpermitted configured
   process is terminated on an enforcer tick and a task-permitted process is
   spared. Exact-name matching does not cover renamed or protected processes.
4. Exercise an overlapping task/goal/break group and confirm ending one scope
   removes only that scope's permission.
5. Watch `enforcement.reconciliation_pending`. Treat a true value as desired
   state awaiting a successful hosts write, not confirmation of enforcement.
6. Disable from an active state and confirm the paired fence is removed.
7. Use Ctrl+C, wait for exit, inspect the hosts file again, and run
   `ipconfig /flushdns` if recovery is needed.

Do not create a real hosts failure merely to test retry semantics; injected
automated tests cover that path safely. If Defender reports a modification,
follow [Troubleshooting](troubleshooting.md#microsoft-defender-reports-a-hosts-file-change)
instead of adding a broad exclusion.

## Agentic watcher

In an ON session, enable agentic mode while a visibly active AI coding agent is
working, then allow the watcher to observe both working and idle states.

Confirm:

- busy opens the website blocklist and pauses productivity monitoring;
- busy does not grant app permission, so unpermitted configured apps remain
  kill targets;
- the transition event and acknowledgement use the watcher's concrete reason;
- idle restores the latest task/goal website policy;
- unchanged watcher verdicts do not append duplicate transition events.

The watcher checks eligibility before capture but has no post-inference
revision check. A simultaneous session, mode, or agentic transition can publish
a stale watcher result. Avoid concurrent clicks during the manual observation;
the limitation remains covered in documentation rather than hidden by a
best-case run.

## Verdict corrections

Exercise reverse, restore, duplicate, stale identity/revision, correction
during BREAK, correction after break completion, JSONL durability gating,
neutral acknowledgement, and suppression of in-flight original speech.

The complete HTTP, audit, accounting, privacy, and manual procedure is in
[Latest productivity-verdict corrections](verdict-corrections.md). A correction
changes effective history/accounting only; it is not analyzer retraining and
must not create a new vision request.

## Evidence review and acceptance

For any affected real path, inspect:

- the newest terminal and timestamped file log for complete prompts, semantic
  outputs, ordering, and exceptions;
- each relevant stitched capture for expected panels and privacy;
- successful `results/llm` request/response objects for model, reasoning,
  prompt, image detail/reference order, and full response;
- session JSONL for canonical event order and complete payloads;
- `results/state.json` only for allowance/topic persistence;
- `/status` for loop phase/result/error, countdowns, effective policy, and
  current verdict identity.

Acceptance requires observed output to agree with the prompt and documented
flow. Model judgments remain probabilistic and should not be described as
ground truth. Record the OS version, device availability, model overrides,
temporary intervals, and any untested boundary when reporting results.

Finish with one bounded review covering correctness, security, privacy,
maintainability, tests, reliability, architecture, and unsupported
documentation claims. Do not repeat review loops unless a serious issue is
found.
