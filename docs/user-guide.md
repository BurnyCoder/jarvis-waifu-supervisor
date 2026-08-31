# User guide

This guide covers normal use after the application is installed and running.
For a reproducible installation, `.env` setup, launch commands, methodology,
and the runtime overview, begin with the repository [README](../README.md).
For startup and browser-opening behavior specifically, see
[Dashboard startup](startup.md).

## Operating model

The application starts in OFF mode. Starting a focused session moves it to ON;
a timed break temporarily moves it to BREAK; Disable returns it to OFF.

| Mode | Website policy | Distraction-app policy | Productivity monitoring |
|---|---|---|---|
| OFF | A transition from an active mode requests removal of the managed hosts section; startup, Disable while already OFF, and shutdown without leaving OFF do not scrub a stale section | Kill sweeps do no work | Paused |
| ON | Configured domains are blocked except those allowed by active scopes | Configured exact-name processes are killed except those allowed by active scopes | Active, unless agentic mode has classified the agent as working |
| BREAK | Blocking remains active with task/preset and break access; goal-only access is suspended | Killing remains active with the same scope rules | Paused |

The dashboard reports desired policy. If
`enforcement.reconciliation_pending` is true, the latest hosts-file change has
not succeeded yet and the enforcer will retry it. A state-changing request can
therefore return HTTP 503 after session state has changed. Check the dashboard
or `/status`, then use the [troubleshooting guide](troubleshooting.md) if the
pending state does not clear.

## Productivity evaluation rules

The productivity monitor evaluates visible evidence against the exact session
topic, permanent task/preset groups, and any active temporary goal. Access is
only permission: activity on an allowed website or app is not productive unless
the capture gives concrete evidence that it serves the topic and, during a goal
grant, the stated goal as well.

The first capture in a monitoring context judges only current alignment and
engagement. It cannot establish progress or a stall. From capture two onward,
the model receives the available corresponding panels oldest first and may make
chronological claims only when task-relevant evidence changed. The configured
`PROGRESS_WINDOW_CAPTURES` is a maximum retained history, not a threshold that
must fill before comparison begins.

Apply these evidence rules:

- Artifact-producing coding, writing, editing, note-taking, debugging, and
  active research ordinarily need meaningful relevant change from capture two
  onward. An unchanged scene without other aligned evidence may be a stall.
- Reading, thinking, calls, physical work, and visibly running builds, tests, or
  training can remain productive when concrete topic-aligned evidence supports
  genuine engagement. A vague task does not create a blanket static-work
  exception.
- Timestamps, clocks, cursors, animations, webcam lighting, minor posture
  changes, and unrelated screen changes do not establish work progress.
- Learning, research, and problem-solving may switch to a clearly
  topic-relevant clarification resource such as documentation, an article,
  lecture, explanatory video, worked example, reference, or forum explanation.
  It may become the primary visible activity when its content clearly connects
  to the topic and the combined evidence supports task-directed engagement.
  Playback, scrolling, navigation, or source switching alone does not prove
  conceptual progress; synthesis, notes, application, or another chronological
  advance is needed for a progress claim.
- For a concretely math-related topic, an unchanged recognizable exercise or
  equation can combine with webcam evidence of stylus use, handwriting, or a
  task-directed calculation posture to support sustained focus. The exercise,
  device, looking down, or posture alone is insufficient, and solution progress
  still requires chronological advancement.
- A music video confined to a secondary part of a monitor can be neutral
  background media. It is never productivity evidence: capture one still needs
  task-aligned engagement, and later captures need meaningful progress in the
  work area. Video frames, playback controls, and titles do not count as
  progress, and this evaluator rule grants no website/app access.

A productive reason is prompted to include a brief affirmation grounded in the
observed task evidence. On capture one it may praise current engagement but must
not invent change over time; later progress praise requires chronological
support. These are prompt rules, not guarantees. Screen compression, occlusion,
ambiguous or invisible work, camera framing, and model nondeterminism can still
produce a wrong verdict. Use the latest-verdict correction instead of treating
the model label as ground truth.

## Start a focused session

In **Start a focused session**:

1. Enter a concrete topic describing the work you intend to do.
2. Optionally select a saved project preset.
3. Check any website or app groups genuinely required for this task.
4. Optionally enable **Agentic engineering** if an AI coding agent will work
   while you wait.
5. Select **Start session**.

The one-off selections and the selected preset are combined. The resulting
task access stays active in ON and BREAK, does not spend social-break minutes,
and is included in the productivity context while monitoring is active. Access
is permission, not evidence of productivity: visible activity still has to
serve the session topic.

Starting a session also queues a good-luck message and applies the new website
policy. The periodic scheduler keeps its existing countdown, so Start does not
force an immediate productivity capture; the dashboard shows when the monitor
is next due.

Starting another session replaces the current one. It clears the current
evaluation timeline, latest verdict, productive streak, break, active
goal-access grant, and agent-busy state. Replacing an active social break does
not refund its unused reservation. Topic history is saved for the Start-form
suggestions, but live sessions and access scopes are not restored after a
process restart.

## Access groups

Start, temporary goal access, and breaks use the same ordered catalog. A Web
group omits its configured hostnames from the managed hosts blocklist. An App
group spares its configured exact process names from the kill sweep. Discord is
the only group that does both.

For each configured apex hostname, the policy also generates a `www.` variant.
There is no wildcard matching, so an unlisted alternate hostname is outside the
policy. In particular, the Substack group does not cover arbitrary author
subdomains.

| Key | Dashboard label | Capability | Configured targets |
|---|---|---|---|
| `reddit` | Reddit | Web | `reddit.com`, `old.reddit.com`, `np.reddit.com`, `i.redd.it`, `v.redd.it` |
| `youtube` | YouTube | Web | `youtube.com`, `m.youtube.com`, `music.youtube.com`, `youtu.be` |
| `twitter` | X / Twitter | Web | `twitter.com`, `mobile.twitter.com`, `x.com`, `t.co` |
| `discord` | Discord | Web + App | `discord.com`, `discord.gg`, `discordapp.com`; `discord.exe` |
| `hackernews` | Hacker News | Web | `news.ycombinator.com` |
| `linkedin` | LinkedIn | Web | `linkedin.com` |
| `bluesky` | Bluesky | Web | `bsky.app` |
| `substack` | Substack | Web | `substack.com` only, plus its generated `www.` variant |
| `facebook` | Facebook | Web | `facebook.com`, `m.facebook.com`, `fb.com` |
| `lesswrong` | LessWrong | Web | `lesswrong.com`, `greaterwrong.com` |
| `eaforum` | EA Forum | Web | `forum.effectivealtruism.org` |
| `4chan` | 4chan | Web | `4chan.org`, `boards.4chan.org`, `4channel.org`, `boards.4channel.org` |
| `telegram` | Telegram | App | `telegram.exe` |
| `steam` | Steam | App | `steam.exe`, `steamwebhelper.exe` |

Checked values are normalized, deduplicated, validated against this catalog,
and restored to catalog order before they can affect state or enforcement.
Start and Break may use no groups; temporary goal access requires at least one.
The old split fields `allowed_sites` and `allowed_apps` are rejected.

Access scopes are additive:

- Task choices and the selected preset apply throughout ON and BREAK.
- Goal-access groups apply only in ON and are suspended during BREAK.
- Break groups apply only for that break.
- Ending one scope does not remove a permission still supplied by another.

Hosts-file blocking is an explicit Windows resolver policy, not a guarantee
that every browser or application will honor it. See
[Troubleshooting](troubleshooting.md) for DNS, browser, and manual-cleanup
caveats.

## Saved project presets

Create an optional `projects.json` in the repository root, beside `main.py`.
It must be a JSON object whose nonempty names map to arrays of access-group
keys:

```json
{
  "ml-research": ["twitter", "linkedin", "telegram"],
  "community": ["discord", "bluesky", "steam"]
}
```

The selected preset is unioned with the one-off task choices. Presets use the
same catalog, so `telegram` and `steam` are valid app-only entries and
`discord` grants both its web and app capability. Invalid JSON, the wrong
shape, an empty preset name, a duplicate name after trimming, or an unknown
group fails during loading; an unknown submitted preset is rejected before a
session changes policy.

Presets are loaded once at process startup. Restart after editing the file.
`projects.json` is not gitignored, so do not commit confidential project names.

## Temporary goal-based access

Use **Temporary goal-based access** during an ON session when the current task
needs a limited exception. Unlike the Start and Break routes described under
[direct-request limitations](#direct-request-input-limitations), this route
validates its goal, duration mode, timed range, and group requirement on the
server:

1. State the concrete result you need to achieve.
2. Choose either a timed duration or **Until this focused session ends**.
3. For a timed grant, enter a whole number from 1 through 240 minutes.
4. Select at least one access group and start the grant.

Only one grant can be active at a time, but you can complete or expire one and
then start another; there is no per-session count or cumulative-minute cap.
The session remains ON, productivity monitoring continues, app-capable groups
can spare their processes, and the grant spends no social allowance. For the
monitor to count the activity as productive, visible evidence must serve both
the main session topic and the stated temporary goal.

Select **Goal complete — stop access** to end the current grant. A timed grant
expires on the first later enforcer tick, rather than at an exact timer
interrupt. Starting a replacement session, successfully disabling, or normal
registered shutdown also ends an active grant.

BREAK preserves the grant record and its wall-clock timer but suspends every
grant-only website and app permission. When the break ends, a grant still
recorded as active becomes eligible again; the enforcer removes a timed grant
on its first tick at or after expiry. An overlapping task or break scope can
independently keep the same group available.

The goal-access badge distinguishes Ready, Active, Suspended for break, and
Policy update pending. A transition acknowledgment can wait for the related
event and policy update; dashboard state may change before speech is delivered.

## Breaks and social allowance

Breaks can start only from ON. In **Take a timed break**, use a nonempty
purpose, a duration from 1 through 240 minutes, one of the two displayed break
types, and any groups needed only for the break.

- **Away from computer** pauses productivity monitoring without charging the
  social allowance.
- **Social media allowance** reserves the full requested duration immediately
  against the current local date's allowance. The default cap is 120 minutes
  per day and can be changed with `DAILY_SOCIAL_CAP_MIN`.

A social break beyond the remaining allowance is refused. Natural expiry keeps
the full reservation. If you select **Stop break and resume work**, every
started minute is charged and the unelapsed reservation is refunded to the
break's starting date. Manual stop is the only refund path: starting a new
session, Disable, or process shutdown clears a break without refunding unused
minutes.

The break ends automatically on the first enforcer tick after its displayed end
time, or immediately through the Stop button. Completion returns to ON, removes
break-only access, makes any still-active goal grant eligible again, resets the
productive streak, and resumes productivity monitoring.

## Agentic engineering mode

Enable agentic mode on the Start form or change it from the **Agentic mode**
card. It is meaningful during an ON session. Start applies its checkbox value
anew, and watcher ticks remain inactive outside ON.

While ON and enabled, the agent watcher periodically captures the stitched
monitor/webcam view and asks whether the coding agent is still working. The
effects follow the latest watcher transition:

- **Initial or repeated idle verdict:** normal website restrictions and
  productivity monitoring stay active. The watcher still reconciles policy, but
  it does not queue an agent-finished message without a preceding busy state.
- **Agent working:** the complete website blocklist opens and productivity
  monitoring pauses.
- **Busy-to-idle transition:** normal website restrictions return, active
  task/goal website permissions remain open, productivity monitoring resumes,
  and one transition message is queued.

Agentic mode never grants app permission. The app killer continues to target
configured processes unless an active task or goal scope spares them. Detection
happens on the configured polling cadence, not instantly, and the vision
classification can be wrong. Turning agentic mode off resets the busy flag and
requests normal website policy immediately.

## Direct-request input limitations

The dashboard's HTML supplies normal constraints, but the current Flask routes
do not enforce every one of them. Treat these as implementation limitations,
not supported ways to obtain access:

- `POST /start` validates access groups and the selected preset, but a
  hand-crafted request can submit an empty, whitespace-trimmed topic and start
  an ON session with that empty topic.
- `POST /break` strictly validates access groups and rejects the legacy
  `allowed_sites` and `allowed_apps` fields. It converts `minutes` with `int()`
  outside its route error handler, so a nonnumeric value can return HTTP 500.
  It does not reject an empty purpose, zero/negative/above-240 minutes, or an
  arbitrary `kind`; extreme values can also fail date arithmetic.
- Break allowance accounting is keyed only by the exact `social_media` kind,
  not by selected groups. A negative social-media duration can reduce recorded
  usage, while `away` or an unknown kind can carry selected groups without
  spending allowance. Only `/break/stop` refunds unused positive social-media
  minutes.
- `POST /agentic` accepts a hand-crafted toggle outside ON. That does not start
  a session, and watcher ticks stay inactive outside ON; the next Start request
  replaces the value with its own checkbox setting.

The loopback dashboard has no authentication or CSRF protection, so browser
controls are neither a server-side validation boundary nor a security boundary.
Keep it on `127.0.0.1`; see [Privacy and data](privacy-and-data.md).

## Dashboard and `/status`

The dashboard is served only on `127.0.0.1` at the configured `UI_PORT`. Unless
you launch with `--open-browser`, open the loopback URL printed in the terminal.
The browser fetches the no-cache `/status` payload every three seconds, avoids
overlapping requests, pauses network polling in a hidden tab, and retains the
last successful view during a temporary connection failure.

The page shows:

- current mode, topic, elapsed session time, monitoring state, and next
  evaluation;
- productive streak, remaining daily social allowance, accepted
  current-session evaluation totals, and last synchronization time;
- newest-first accepted verdict history, with the model reason and expandable
  visual observation;
- current break, agent state, and task/preset access;
- desired blocked-domain and process-target counts;
- goal-access state and countdown; and
- the phase, cadence, last result, and latest error for the monitor, enforcer,
  and agent-watch loops.

BREAK and OFF retain the current in-memory verdict timeline for review. A new
session or process restart clears it. The history has no within-session cap, so
long sessions produce a larger `/status` response and browser timeline.

Only the newest verdict can be changed between Productive and Off track. A
manual correction changes the effective dashboard/accounting label while
retaining the model label and evidence; it does not retrain or rerun the
analyzer. See [Latest productivity-verdict corrections](verdict-corrections.md)
for the complete UI, accounting, HTTP, event, and feedback contract.

Inspect the JSON directly from PowerShell, replacing the port if needed:

```powershell
Invoke-RestMethod "http://127.0.0.1:5000/status"
```

Important top-level sections include `work_access`, `goal_access`, `break`,
`enforcement`, and `runtime`. Access objects publish canonical group keys and
labels plus derived site/app arrays. `work_access.selected_groups` contains only
the one-off Start choices, while `work_access.allowed_groups` includes the
selected preset. `goal_access.suspended` identifies BREAK suspension, and
`enforcement.reconciliation_pending` identifies an unapplied hosts update.

The dashboard does not serve saved captures or prompt/exchange files. It is a
loopback development server without authentication or CSRF protection, so do
not expose it to a network. Review [Privacy and data](privacy-and-data.md)
before a real session.

## Disable and exit

To leave enforcement OFF from the dashboard, type this exact case-sensitive
confirmation phrase:

```text
I will not stop cool deepwork session
```

Disable from an active mode ends the session and any goal grant, clears an
active break without a social-minute refund, and requests removal of the
managed hosts section. It
does not erase the in-memory verdict timeline. Use Ctrl+C in the terminal to
stop the application; after an active run, registered shutdown also attempts
serialized policy cleanup.

Hard termination can bypass cleanup, and startup does not proactively remove a
managed section left by a previously killed process. Do not run concurrent
instances. Follow the fenced-section recovery procedure in
[Troubleshooting](troubleshooting.md) if sites remain blocked after exit.
