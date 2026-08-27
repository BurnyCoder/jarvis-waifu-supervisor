# AGENTS.md — repository operating guide

## Product and source of truth

This Windows 11 productivity-enforcement app combines explicit hosts entries,
exact-name process killing, rolling OpenAI screen/webcam evaluation, spoken
feedback, session modes/exceptions, a loopback dashboard, and local storage.

When documentation and implementation disagree, verify behavior in this order:

1. Executable code and focused tests.
2. `.env.example`, `pyproject.toml`, and `uv.lock`.
3. `README.md`, this file, and other prose.
4. Current authoritative upstream documentation for external behavior.

Do not preserve a claim merely because an older README or comment says it.

## Working commands

Run from the repository root with the uv-managed local `.venv`:

```powershell
uv sync --locked                   # reproduce the checked-in lockfile
uv sync                            # update after an intentional dependency edit
uv lock --check                    # verify lockfile/project metadata consistency
uv run pytest                      # complete fake-backed unit suite
uv run python main.py --help       # CLI surface
uv run python main.py --dry-hosts  # UI + scheduler; no UAC/hosts writes
uv run python main.py --dry-hosts --open-browser  # readiness-gated browser; dry hosts
uv run python main.py --smoke      # one direct capture/analyze/speak attempt
uv run python main.py              # UAC + real hosts enforcement + UI
```

Unit tests need no admin, API, capture, or audio; `--smoke` uses the last three.
After Start, `--dry-hosts` still kills apps, captures, calls APIs, stores, and speaks.
`--smoke` directly attempts one productivity monitor tick with topic
`smoke test`: it starts no Flask or scheduler-loop threads, runs no
enforcer/app-killer/agent-watch tick, and emits no `session_start`/good-luck
feedback, although registered shutdown reconciles OFF through the dry-run
blocker and persists the topic history.

`Start Deep Work.bat` passes `--open-browser`; direct terminal runs open no
browser unless that flag is supplied. Python's UAC relaunch preserves the
argument, and `--smoke` ignores it because smoke starts no server.

## Wrapper and module ownership

`main.py` must remain the readable wrapper:

```text
arguments → elevation → config/logging → blocker selection
          → collaborator wiring → cleanup registration → smoke or server run
```

Implementation details live under `deepwork/`:

| Module | Current responsibility |
|---|---|
| `config.py` | Frozen `.env`-derived `Config`; hardcoded site/app policy tables and hostname expansion; sparse numeric validation |
| `access_policy.py` | Immutable 14-option website/app catalog; labels/capabilities; strict normalization; site/app projection; `projects.json` loading and task/preset union |
| `logging_setup.py` | Timestamped UTF-8 file and terminal root logging |
| `state.py` | Locked modes, terminal shutdown, grant lifecycle/feedback coordination, versioned monitoring context, retryable policy reconciliation, breaks, allowance, verdicts, and status |
| `storage.py` | Quality-80 capture JPEGs, text/vision exchange JSON, retryable ordered session JSONL, and persisted allowance/topic state |
| `runtime_status.py` | Locked JSON-safe fixed-delay loop cadence, phase, result, countdown, and error state |
| `scheduler.py` | Enforcer (including access expiry and dirty-policy retry), context-safe productivity monitor, and agent-watch loops |
| `blocking/admin.py` | Windows admin test and `runas` self-relaunch |
| `blocking/hosts_blocker.py` | Direct marker-fenced hosts replacement/removal and best-effort DNS-cache flush; dry-run adapter |
| `blocking/app_killer.py` | Abrupt case-insensitive exact process-name termination with psutil |
| `monitoring/screen_capture.py` | One Pillow image per physical monitor via mss |
| `monitoring/webcam_capture.py` | DirectShow camera-index-0 frame; an unsuccessful read returns `None`, while exceptions fail that capture tick |
| `monitoring/stitcher.py` | Labeled vertical composite after resizing each monitor/webcam tile to 960 pixels wide |
| `monitoring/analyzer.py` | Original-detail productivity verdict: current alignment on capture 1 and task-aware rolling comparison from capture 2; low-detail single-capture agent-activity verdict |
| `feedback/goal_access.py` | Policy-revision-gated transition acknowledgments and independent FIFO message-generation worker |
| `feedback/messages.py` | Context-grounded good-luck, nudge, milestone-praise, break, goal-access, and agent-transition text |
| `feedback/tts.py` | OpenAI temporary WAV or per-utterance pyttsx3 speaker behind one FIFO daemon worker |
| `webui/app.py` | Flask factory and state-changing session, access, break, agent, and disable routes |
| `webui/status.py` | Composition of state and scheduler snapshots |
| `webui/server.py` | Loopback threaded Werkzeug serving, optional `/status` readiness polling, and one-time default-browser launch |
| `webui/templates/`, `static/` | Actions-first dashboard and safe non-overlapping polling |

## Behavioral invariants

- A new session replaces one-off task access groups, ends any temporary goal-access
  grant, and resets the latest verdict, timeline, break, streak, and agent
  state. Its next monitor tick resets the analyzer window.
- Registered normal shutdown attempts to end and persist an active grant before
  serialized hosts cleanup. A retained transient JSONL failure may become
  durable during cleanup; persistent I/O failure or hard termination can lose
  the end event.
- OFF and BREAK preserve the in-memory timeline; restart does not. Only
  allowance usage and topic history are reloaded into live state. Captures,
  exchanges, JSONL events, and logs remain on disk; live sessions/grants never
  reload.
- A successful productivity capture is evaluated immediately against the
  available rolling window only if its versioned monitoring context still
  matches. Capture one judges only current task alignment and cannot establish
  progress or a stall. From capture two, compare corresponding monitor/webcam
  panels across the whole available oldest-to-newest window.
- `PROGRESS_WINDOW_CAPTURES` is a maximum retained history with a minimum value
  of two, not a comparison threshold. With five captures and the default
  five-minute fixed delay, the maximum window begins on the fifth uninterrupted
  same-context tick and spans at least about 20 minutes; capture and model
  latency extend that timing.
- Add each saved capture to the rolling deque before the model/exchange write
  completes. A failed analysis remains in the window, so a later successful
  request may compare multiple captures even if no earlier verdict was recorded.
- Task-aware comparison expects meaningful relevant changes from
  artifact-producing coding, writing, editing, note-taking, debugging, and
  active research. Meaningfully unchanged captures with no other task-aligned
  evidence may be stalled from capture two. Plausibly static reading, thinking,
  calls, physical work, and visibly running builds, tests, or training remain
  productive only with concrete topic-aligned engagement evidence. Unrelated
  changes, timestamps, clocks, cursors, animations, webcam lighting, and minor
  posture changes do not establish progress. Do not invent a static-work
  exception for a vague task.
- Mathematics worked out on a tablet is a supported static-work case when the
  stated topic is concretely math-related. A visibly recognizable unsolved
  exercise, equation, or problem statement may stay unchanged onscreen while
  corroborating webcam evidence shows stylus use, handwriting, or a task-directed
  calculation posture. The tablet surface and fresh handwriting need not appear
  in every snapshot, and brief thinking pauses may occur while the combined
  evidence remains coherent. Sustained combined evidence can establish focus
  across a long interval, not solution progress unless chronology shows
  advancement. The exercise, device or stylus presence, looking down, or posture
  changes without task-directed engagement are insufficient; clear unrelated
  browsing, media, chat, or gaming remains unproductive.
- A music video occupying only a secondary part of a monitor is neutral
  work-supporting background media, not evidence of productivity. Capture one
  still uses the current-engagement rule; from capture two onward, the remaining
  work area must show meaningful task-relevant progress for this exception to
  apply. Video frames, animation, playback bars, timestamps, titles, and other
  playback changes never count as progress. If work stalls or the video becomes
  the primary activity, use the ordinary video and access rules. This prompt
  exception grants no website or app access.
- The analyzer prompt requires every productive reason to integrate a brief
  affirmation tied to concrete task-aligned evidence and asks the model to vary
  the wording naturally. A single capture may praise current engagement but
  must not claim change over time. From capture two, progress praise requires
  supporting task-relevant chronological evidence; otherwise praise only the
  engagement or focus. The canonical reason is stored, displayed, and spoken
  unchanged on ordinary productive ticks. Off-track and 30-minute
  streak-milestone ticks instead generate a nudge or richer praise. A
  context-accepted verdict is recorded before JSONL append and optional message
  generation; if either fails, the tick may publish an in-memory verdict
  without queuing its otherwise single utterance.
- Scheduler intervals are fixed delays after a tick finishes, not wall-clock
  schedules. Starting a session does not reset their countdowns.
- Productivity and agent-watch ticks share one capture lock. Hold it only
  around the injected capture callable; persistence, model calls, state
  mutation, and speech must remain outside it.
- The productivity analyzer gets an immutable, revisioned context snapshot.
  Every grant start/end changes that identity and resets the rolling window
  before the next capture. Recheck after capture and atomically compare again
  when recording: a transition during capture must avoid persistence/model
  work; a transition during save/model work can leave a capture/exchange locally
  and at OpenAI but must produce `context_changed` with no verdict state, event,
  or speech.
- The canonical access catalog has 14 ordered groups: `reddit`, `youtube`,
  `twitter`, `discord`, `hackernews`, `linkedin`, `bluesky`, `substack`,
  `facebook`, `lesswrong`, `eaforum`, `4chan`, `telegram`, and `steam`.
  Discord grants both its configured websites and desktop app from one choice;
  Telegram and Steam are app-only; every other group is website-only.
- Start, goal-access, and break forms share one repeated `allowed_groups`
  checkbox contract. Strictly normalize and allowlist all values before state,
  events, prompts, speech, hosts, or process mutation. Reject unknown keys and
  either legacy `allowed_sites`/`allowed_apps` field with HTTP 400. This strict
  group validation does not extend to all route fields: Start accepts a forged
  empty topic; Break trusts HTML for purpose, duration, and kind, calls `int()`
  outside its error handler, does not reject zero/negative/above-240 minutes or
  arbitrary kinds, and can corrupt accounting with negative `social_media`
  minutes.
- Task and preset groups remain active during ON and BREAK, are part of the
  analyzer's permanent task context while monitoring is active, spend no social
  allowance, and spare any selected app-capable processes.
- One temporary goal-access grant may be active at a time, but a session may
  contain unlimited sequential grants. Each requires a non-empty goal, at
  least one strictly validated access group, and either 1..240 wall-clock
  minutes or session-end duration. It stays in ON mode, spends no social
  allowance, does not itself pause monitoring, and can spare selected apps.
- BREAK preserves but suspends the entire goal grant: grant-only websites
  re-block and grant-only apps become kill targets while its timer keeps
  running. It resumes only if still active when BREAK ends. Task groups remain
  active and break groups apply only during that BREAK; overlapping scopes are
  additive. Agentic policy can independently permit an overlapping website.
  Timed grant and break expiry are detected by the first later fixed-delay
  enforcer tick rather than at the exact displayed wall-clock end.
- Serialize every desired hosts policy through the state-owned reconciliation
  lock. A backend exception leaves the policy dirty, exposes
  `/status.enforcement.reconciliation_pending`, and is retried by the enforcer;
  never let an older writer overwrite a newer transition. App-only scope
  changes advance monitoring identity and process policy without dirtying or
  rewriting an identical hosts policy.
- `HostsBlocker` rewrites the complete hosts file directly; it has no atomic
  replace, backup, or cross-process lock, and ignores DNS-flush exit status.
  Startup begins OFF/clean and does not proactively clear a fenced section left
  by a hard-killed prior process. Run one instance only and preserve the manual
  cleanup warning.
- Complete goal-access events and successful enforcement precede optional
  transition message/TTS work. Start, manual stop, and expiry each enqueue one
  immutable acknowledgment context. Successful serialized reconciliation moves
  only requests supported by that exact policy revision toward the ready FIFO;
  a superseded failed permission transition is dropped rather than announced.
  A separate daemon worker delivers approved requests without holding the
  lifecycle lock. Cancel an unapplied start if its
  grant ends, expires, is replaced, is disabled, or shuts down before opening
  reconciliation succeeds. Model/speech failure never rolls state back or
  retries a claimed request. Canonical lifecycle events are attempted and
  retained before reconciliation, but persistent storage failure can still
  prevent durability.
- Session-event appends are serialized. A transient JSONL failure retains the
  complete timestamped line for enforcer retry, never prevents immediate hosts
  reconciliation, and rolls partial/close-time writes back to the previous line
  boundary before retry. Matching transition speech waits until earlier events
  are durable. All ready session, break, agent, and goal transition work shares
  one FIFO worker. A goal request still gated on failed enforcement/event
  durability is not ready and may be overtaken by an independent later
  acknowledgment; preserve that behavior and never announce unapplied access.
- Positive social-break minutes are reserved in full when the break starts.
  Manual stop charges each started minute and refunds the unelapsed reservation
  to the break's starting local date; natural expiry consumes the full amount.
  Only manual stop refunds: replacement session start, Disable, and shutdown
  clear the break without a refund. Accounting depends solely on exact kind
  `social_media`, not selected groups; any other/forged kind is uncharged.
- Agent-busy mode empties only the website blocklist; it adds no app
  permissions. App killing continues for processes not spared by an active
  task/goal group, and the productivity monitor pauses until a later watcher
  verdict marks the agent idle.
- Unlike productivity monitoring, agent-watch checks eligibility only before
  capture/model work and has no post-inference context recheck. A concurrent
  mode/session/agentic transition can therefore publish a stale watcher event
  and message.
- Each enforcer tick holds the goal-access lifecycle lock while expiring scopes,
  taking the effective process-target snapshot, and running the kill sweep.
  Expired apps become targets on that tick, and a concurrent route cannot grant
  an app between target selection and termination.
- Shared scheduler/Flask state must stay behind the existing locks.
- `/status` must remain JSON-safe, additive, and `Cache-Control: no-store`.
  Canonical group keys/labels coexist with derived site/app arrays in
  `work_access`, `goal_access`, and `break`; equivalent event payloads retain
  derived arrays for diagnostics and older-log readability. Render model text
  as text, never trusted HTML.
- The Werkzeug development server hosting Flask stays on `127.0.0.1`. Server
  construction binds `UI_PORT` before any browser worker starts. With
  `--open-browser`, a 30-second monotonic deadline retries `/status`, treats any
  completed HTTP response as reachable, and attempts at most one default-browser
  tab. Bind failure prevents launch; readiness/browser failure is logged without
  stopping a bound server; server exit cancels pending opening; smoke bypasses
  all server/browser work. The server has no authentication or CSRF defense and
  must not be exposed as a production network service.

## LLM, logging, storage, and privacy invariants

- Log every complete textual prompt and semantic model output to both terminal
  and the timestamped run log; never slice or abbreviate them.
- Permanent task groups and active goal-access goals/groups are complete
  productivity-prompt/event data; log and persist them without truncation and
  document that productivity evaluation uploads them with capture context.
  BREAK pauses monitoring: break-only groups remain in local events but are not
  sent with a productivity capture. Allowed Discord, Telegram, or other group
  activity remains conditionally productive only when concrete visible
  evidence serves the topic and, for a goal grant, its explicit goal.
- Persist each successful text/productivity-vision/agent-watch Responses API
  object under `results/llm/`. For vision requests, persist full text plus
  capture-file references instead of duplicating base64 image bytes. Failed
  calls and streamed TTS responses/audio are not stored there.
- Keep capture, exchange, session, and state artifacts under `results/`.
- Screen images and a camera-index-0 frame when its read succeeds are sensitive
  and are uploaded to OpenAI for vision requests. The code does not set
  `store=False`; keep README's
  current OpenAI Responses-retention warning synchronized with official data
  controls. OpenAI TTS uploads utterance text, streams an OS-temp WAV, and
  deletes it only after successful playback; an exception may leave that file.
  `pyttsx3` makes synthesis/playback only offline.
- Local artifacts are unencrypted and have no automatic pruning. Session JSONL
  alone has the ordered in-memory retry path; capture, exchange, and
  `state.json` writes are direct/non-atomic, and corrupt `state.json` can abort
  startup.
- `.env`, `logs/`, and `results/` remain gitignored. Never stage credentials or
  runtime captures, even with a force-add.
- `projects.json` is loaded only at startup and is not gitignored; avoid
  committing sensitive project names.
- Preserve the dashboard's AI-voice disclosure.

## Implementation rules

Before adding anything, ask:

- Does it need to exist?
- Does the standard library or an established dependency already do it?
- Can the design or line be simpler?
- Can one readable reusable function replace duplication?

Then follow these rules:

- Build the simplest practical, functioning implementation, not a throwaway
  demo.
- Keep the wrapper phase-oriented and hide details in clearly named modules.
  Split files/directories only as complexity actually grows.
- Reuse functions and policy tables; do not duplicate parsing, validation,
  prompt, status, or persistence logic.
- Keep access-group order, labels, capability projection, strict normalization,
  and project-preset union centralized in `access_policy.py`. All three forms
  must continue to render the shared picker and submit repeated
  `allowed_groups` values.
- Use `.env` for runtime tunables, uv for dependency management and commands,
  and the repository-local `.venv`. Run from the repository root because
  `projects.json`, `logs/`, and `results/` are cwd-relative. python-dotenv
  searches upward from the calling source file for `.env`; existing process
  environment values win because loading is non-overriding.
- Validate new configuration at its boundary. Current numeric parsing is raw
  `int()` and only the progress-window minimum is checked later; nonpositive
  scheduler delays can create tight loops and excessive API/CPU work. Exact
  `TTS_ENGINE=openai` is the only value that selects OpenAI; every other value
  currently falls back to pyttsx3.
- Use TDD for behavior changes. Add the failing test first, implement the
  smallest fix, then run the full suite.
- Prefer dependency injection for clients, paths, clocks, and hardware/network
  callables. Tests may monkeypatch narrow OS/library boundaries such as psutil
  iteration or DNS flushing; do not claim that globals are never patched.
- Add global-context and local-behavior comments to files, functions, and code
  lines as requested by the project owner. Ground non-obvious external API and
  platform behavior in current primary documentation links. Write comments
  deliberately with the code; do not mass-generate them.
- Search current library, language, platform, and upstream repository docs
  before implementing unfamiliar behavior. Prefer official/primary sources and
  verify copied API shapes against the installed versions.
- Keep `README.md`, `AGENTS.md`, `.env.example`, architecture diagrams, setup,
  usage, privacy notes, and caveats synchronized with behavior.

## Verification and review

For every change:

1. Run focused tests during TDD.
2. Run `uv run pytest`.
3. Exercise the affected path as a user would. For capture/LLM/TTS changes,
   run `uv run python main.py --smoke`; it covers only the single-capture
   productivity branch. For rolling-comparison changes, also exercise at least
   two same-context captures and inspect the second request. For UI/state
   changes, also exercise the relevant Flask flow or full local app.
   For server/launcher changes, run
   `uv run python main.py --dry-hosts --open-browser` with an available
   nondefault `UI_PORT`; verify one first-load tab without refresh and inspect
   listening/readiness/open log ordering. `--smoke` does not cover this path.
4. Inspect the newest terminal/file logs and relevant `results/` artifacts.
   Confirm prompts, outputs, stored records, and spoken behavior agree.
5. Fix observed issues, rerun the affected path, and push the corrected
   functional commit.
6. Perform one bounded review pass covering correctness, security, privacy,
   maintainability, tests, reliability, design, architecture, and unsupported
   claims.

Do not call a hardware-free unit run an end-to-end smoke test. Do not claim
"flawless" behavior from tests that cannot observe Windows, devices, the
network, or model nondeterminism.

## GitHub workflow

- The canonical repository is
  `BurnyCoder/deep-work-jarvis-waifu-supervisor`. A local `origin` may still use
  the legacy `BurnyCoder/jarvis-waifu-supervisor` URL, which GitHub redirects;
  do not create a duplicate or change visibility without explicit
  authorization.
- Start changes from `master` on `feat/<name>`.
- Preserve unrelated user work. Stage only intended files.
- Split genuinely independent functional units into meaningful commits; do not
  manufacture commit splits for one inseparable documentation correction.
- Push the feature branch, open a pull request, review it, and merge it to
  `master` with a merge commit (`--no-ff`) once checks pass. Complete those
  steps without delegating routine repository operations back to the user.
- No `.github/workflows` are tracked currently, so repository-local verification
  is the only checked-in CI-equivalent unless GitHub branch settings add
  external checks.
- Never commit secrets. Confirm important source, tests, configuration
  examples, and docs are tracked before merging.

## Current gotchas

- Browser opening is best-effort. Readiness timeout, a false `webbrowser`
  result, or an exception leaves the server running and the logged loopback URL
  is the fallback.
- `.python-version` selects Python 3.13. Do not invent a Python 3.14 wheel
  limitation without checking current package indexes.
- The pyttsx3 adapter constructs an engine per utterance to avoid the linked
  upstream reuse issue in `feedback/tts.py`.
- Access is intentionally group-based rather than split by backend. An existing
  `projects.json` preset containing `discord` now opens Discord websites and
  spares `discord.exe`; Telegram and Steam are valid app-only preset keys. Do
  not reintroduce separate site/app controls or silently reinterpret that key.
- `/break` strictly validates `allowed_groups` and rejects legacy split access
  fields, but purpose, duration, and kind still rely on the dashboard's HTML
  constraints. Nonnumeric minutes can return 500; zero, negative, and
  above-240 values are not rejected by validation, while extreme values can
  still fail date arithmetic. Arbitrary kinds are accepted. Negative social
  duration corrupts accounting, and an `away`/unknown kind can grant any
  selected group without spending allowance. Only `/break/stop` refunds unused
  social minutes.
- Browser-level DoH behavior is not uniform. Windows honors its hosts file in
  the system resolver, while software with its own resolver can bypass that
  path; keep README wording conditional.
- Hard termination can skip `atexit`; manual fenced-section cleanup remains
  necessary. Startup/Disable-while-OFF do not proactively remove a stale fence,
  and even normal shutdown can abandon transition/speech work after its bounded
  wait.
- Hosts policy is explicit, not wildcard-based. Substack author subdomains and
  other unlisted alternate domains are not covered.
- Productivity vision uses original detail, which preserves supplied image
  dimensions with the default GPT-5.6 Luna model but can increase input tokens
  and latency. Every raw monitor/webcam tile is first resized to 960 pixels wide
  and the composite is JPEG-compressed, so “original” does not mean native
  monitor resolution. `VISION_MODEL` overrides must support original detail.
  Tall composites, occlusion, ambiguity, and visually static work can still
  mislead it.
  Agent-watch vision remains low-detail and can miss small screen text. Never
  present either model verdict as ground truth.
- The watcher lacks productivity's post-inference revision check; concurrent
  session/mode/agentic changes can let a stale busy/idle result publish.
- Hosts and local state files have no cross-process lock. Do not run concurrent
  instances.
