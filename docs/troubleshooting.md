# Troubleshooting and recovery

Start from the repository root and keep only one instance running. Most useful
evidence is in the terminal, the newest `logs/deepwork_*.log`, and the JSON
returned by `http://127.0.0.1:<UI_PORT>/status`.

## Installation and configuration

### `uv` is not recognized

Install uv using its current
[Windows instructions](https://docs.astral.sh/uv/getting-started/installation/),
open a new PowerShell window, and confirm:

~~~powershell
uv --version
uv sync --locked
~~~

The checked-in `.python-version` selects Python 3.13 and `pyproject.toml`
requires Python 3.13 or newer. uv normally creates and manages the repository
local `.venv`. Do not substitute an unrelated activated environment for the
project commands; use `uv run ...`.

### The lockfile or environment is out of sync

~~~powershell
uv lock --check
uv sync --locked
~~~

`uv lock --check` verifies that `uv.lock` agrees with project metadata without
updating it. `uv sync --locked` creates or synchronizes `.venv` from the
checked-in lock and fails instead of silently changing an outdated lock. This
matches uv's [locking and syncing contract](https://docs.astral.sh/uv/concepts/projects/sync/).

If a local `.venv` is damaged, stop the app, rename that directory for
recovery, and run `uv sync --locked` again. Do not remove `uv.lock` to solve an
environment problem.

### `OPENAI_API_KEY missing`

Copy `.env.example` to `.env` and replace its placeholder. The code loads
`.env` without overriding an already defined process environment value, so an
old `OPENAI_API_KEY` in the launching environment wins over the file.

An API key and API billing are separate from a ChatGPT subscription. Never put
the key in `projects.json`, a command argument, a bug report, or a committed
file. `.env` is gitignored.

### Configuration fails before the dashboard starts

- Numeric values are parsed with `int()`. A non-integer value can fail before
  timestamped logging is configured.
- `PROGRESS_WINDOW_CAPTURES` must be at least `2`.
- Use a positive `CAPTURE_INTERVAL_S`, `KILL_INTERVAL_S`, and
  `AGENT_CHECK_INTERVAL_S`. Most interval ranges are not validated; zero or
  negative delays can create tight loops and repeated API/CPU work.
- Use an available TCP port from `1` through `65535` for `UI_PORT`.
- A present `projects.json` must be valid JSON mapping project names to lists
  of canonical access-group keys. Invalid JSON, shapes, or keys fail startup
  instead of silently weakening policy.
- Only exact `TTS_ENGINE=openai` selects OpenAI speech. Every other value
  currently falls back to pyttsx3.

Compare local values with `.env.example` and run:

~~~powershell
uv run python main.py --help
~~~

That command validates the CLI surface without loading configuration, asking
for UAC, starting hardware, or calling OpenAI.

## Startup, UAC, and dashboard

### No UAC prompt or dashboard appears

Real mode checks elevation before configuring the run log. If it is not
elevated, it asks Windows to relaunch the same Python command with the `runas`
verb and exits the original process. A rejected or blocked UAC launch may
therefore leave no new `deepwork_*.log`.

Run from PowerShell so errors remain visible:

~~~powershell
uv run python main.py --open-browser
~~~

Use `--dry-hosts` only to isolate UAC/hosts permission trouble. It suppresses
hosts writes, but after Start it still terminates configured apps, captures and
uploads images, calls APIs, stores artifacts, and speaks.

### The server runs but no browser opens

Direct terminal runs open no tab unless `--open-browser` is present. Search the
newest log for:

~~~text
control panel listening: http://127.0.0.1:<UI_PORT>
~~~

Open that exact URL manually. Browser readiness and OS browser-launch failure
are best-effort errors and do not stop an already bound server. The
[startup guide](startup.md) documents the expected listening → readiness →
open order.

### The port is already in use

Server construction binds `127.0.0.1:<UI_PORT>` before a browser worker starts,
so a bind failure opens no tab. Stop the process using that port or select an
unused `UI_PORT` in `.env`, then restart. Do not bind this unauthenticated,
CSRF-unprotected Werkzeug development server to a network interface.

### The dashboard is stale or reports an error

Open `/status` directly and inspect `runtime.loops` and
`enforcement.reconciliation_pending`. The frontend uses non-overlapping
polling, but a browser/network error can leave its last rendered values on
screen. Reload once after confirming the server still answers.

LLM text is rendered as text rather than trusted HTML. Saved captures and raw
exchange files are not available from dashboard routes.

## Website enforcement

### A selected blocked site still opens

Check in this order:

1. Confirm the app is ON, the site group is not permitted by the task, preset,
   goal, break, or agent-busy policy, and
   `enforcement.reconciliation_pending` is `false`.
2. Inspect the hosts file as Administrator. A real active policy should contain
   the paired `# >>> deepwork block start` and
   `# <<< deepwork block end` markers plus IPv4 and IPv6 entries for configured
   hostnames.
3. Run `ipconfig /displaydns` and `ipconfig /flushdns`, then retry. Microsoft
   documents that the Windows DNS client checks its cache, then the hosts file,
   then a DNS server, and that
   [`/flushdns` resets the resolver cache](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/ipconfig).
4. Test the exact configured hostname. The policy is an explicit list, not a
   wildcard: alternate domains, direct IP access, unlisted subdomains such as
   Substack author domains, proxies, and VPNs can bypass it.
5. Check the browser or application's secure-DNS/DoH and cache behavior.
   Software with its own resolver can bypass the Windows resolver path even
   though Microsoft's
   [DNS troubleshooting guide](https://learn.microsoft.com/en-us/troubleshoot/windows-client/networking/troubleshoot-dns-client-resolution-issues#scenario-2-theres-an-entry-for-the-domain-name-in-the-hosts-file)
   shows Windows itself honoring hosts entries.

A cleared pending flag means the hosts write path returned successfully. The
blocker ignores the exit status from its best-effort DNS flush, so the flag
does not prove that DNS cache flushing succeeded.

### `reconciliation_pending` stays true

The desired state has changed but the hosts backend raised. The fixed-delay
enforcer retries the newest desired policy. Inspect the log for
`enforcement reconciliation failed`, confirm the process is elevated, check
file permissions and Defender, and keep the session state visible until a later
tick clears the flag.

Do not infer the Windows hosts contents from the desired dashboard state while
this flag is true. A superseded transition is intentionally not announced as
success.

### Microsoft Defender reports a hosts-file change

This project intentionally edits the Windows hosts file. Microsoft documents
that its
[HostsFileHijack detection](https://www.microsoft.com/en-us/wdsi/threats/malware-encyclopedia-description?Name=SettingsModifier%3AWin32%2FHostsFileHijack)
flags suspicious hosts modifications and may reset entries. Verify the
detection path and this application's fenced entries before considering any
exclusion. Do not broadly disable Defender.

### A stale hosts block remains after exit

Python's
[`atexit` handlers are not guaranteed after hard termination](https://docs.python.org/3.13/library/atexit.html),
and startup, Disable-while-already-OFF, or shutdown without ever leaving OFF
does not proactively remove a prior fence. Recover deliberately:

1. Stop every Deep Work instance. There is no cross-process lock.
2. Open `C:\Windows\System32\drivers\etc\hosts` as Administrator and make a
   backup that preserves all unrelated lines.
3. If both Deep Work markers are present in the correct order, remove exactly
   the inclusive fenced section and nothing else.
4. If a start marker has no matching end marker, do **not** start a real
   enforcement session first. The current strip logic assumes a paired fence
   and can discard everything after an unmatched start marker during its next
   rewrite. Reconstruct the file from the backup while preserving intentional
   non-Deep-Work entries.
5. Save the file and run `ipconfig /flushdns` from an elevated terminal.
6. Reopen the file and verify that neither Deep Work marker remains.

The blocker rewrites the complete hosts file directly and has no atomic
replacement, automatic backup, or cross-process lock. A manual backup is the
recovery boundary.

## Application enforcement

### An app is killed during `--dry-hosts`

That is expected. `--dry-hosts` swaps only the hosts backend; the enforcer
still calls the real exact-name process killer while mode is ON or BREAK.
Disable the session before reopening an app that is not allowed by an active
scope.

### A configured app is killed unexpectedly

Discord, Telegram, and Steam permissions are group-based and scope-aware:

- task/preset groups remain active during ON and BREAK;
- a goal group's app permission is suspended during BREAK;
- a break group applies only during that break;
- Discord is one Web + App choice;
- agent-busy mode opens websites but adds no app permission.

The process killer terminates exact executable names abruptly without asking
them to save. Check `/status` access scopes before reproducing with important
work open.

### A configured app is not killed

The current exact-name policy covers `discord.exe`, `telegram.exe`,
`steam.exe`, and `steamwebhelper.exe`. Renamed binaries, web versions, helper
processes outside that list, inaccessible/protected processes, and process
races are not covered. Process-access failures are intentionally skipped so
the periodic enforcer survives.

## Capture, API, and speech

### Capture fails or the webcam tile is absent

Look for `capture failed`, `webcam capture failed`, and the loop's
`capture_failed` result in `/status`.

- An unsuccessful camera-index-0 read is non-fatal and omits the webcam tile.
- An exception from monitor or webcam capture fails that entire tick.
- Productivity and agent-watch capture calls share one lock; waiting for the
  other capture is normal.
- `context_changed` is not an API failure. It means a session/access/mode
  transition made the capture or completed analysis stale, so no verdict was
  accepted.

Close other camera consumers, verify Windows camera permissions, and inspect
the newest saved composite before retrying.

### OpenAI authentication, model, rate, or network errors

Inspect the complete exception in the terminal and newest log, then compare it
with OpenAI's current
[API error guidance](https://developers.openai.com/api/docs/guides/error-codes).
Verify the API key's project, billing/limits, model access, and network.

`VISION_MODEL` must support image input with `detail="original"`. A failed API
call is logged but not saved as a successful `results/llm/*.json` exchange.
Depending on where failure occurred, its capture can remain on disk and in the
rolling in-memory window for a later request.

### There is no sound

- Search for `speaking:` followed by `TTS failed`.
- With exact `TTS_ENGINE=openai`, verify network, speech-model/voice access,
  Windows WAV playback, and the OS temporary directory. A failed path can leave
  a temporary WAV.
- Any other engine value selects pyttsx3. Verify a Windows SAPI voice is
  installed and available to that user.
- Speech is FIFO and asynchronous. Normal shutdown waits only a bounded time
  for transition generation and does not guarantee that all queued audio
  finishes.

The dashboard's AI-voice disclosure applies to AI-generated wording even when
pyttsx3 performs local synthesis.

## Local data and shutdown

### `results/state.json` is corrupt

Stop the app, back up the malformed file, and rename it out of
`results/` before restarting. The app will treat the missing path as first run.
This resets only persisted daily social usage and previous-topic history; it
does not recover or delete sessions, captures, exchanges, or JSONL events.

Do not hand-edit the file while the app is running. State writes are direct and
non-atomic, so also check disk health, free space, and directory permissions.

### Artifact writes fail

Run from the repository root so `logs/`, `results/`, and `projects.json` resolve
to the expected location. Check free space and permissions.

Session JSONL appends retain complete failed lines in memory and retry in order.
Capture, exchange, and state writes do not use that queue. Hard termination can
lose pending in-memory events and feedback.

### Clean shutdown does not finish all work

Use Ctrl+C and wait for the process to exit. Normal cleanup stops scheduler
producers, publishes terminal OFF state, attempts ordered grant-end
persistence, reconciles hosts cleanup, and saves allowance/topic state.

Cleanup remains best effort: scheduler joins and transition generation have
bounded waits, the speech worker is not fully drained, persistent I/O or hosts
errors can survive, and hard termination can skip cleanup altogether. Inspect
the hosts markers and newest log after any abnormal exit.

For a controlled diagnostic sequence, use [Verification](verification.md).
For the full data inventory, see [Privacy, data, and cost](privacy-and-data.md).
