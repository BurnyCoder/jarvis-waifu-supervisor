# Latest productivity-verdict corrections

The dashboard lets the user correct the newest productivity evaluation when
the vision model got its productive/off-track classification wrong. A
correction is reversible, changes the effective session accounting, and keeps
the model's original judgment and evidence available for audit. It does not
rerun or retrain the analyzer, modify the rolling capture window, grant access,
change hosts or app enforcement, alter a break timer, or spend social allowance.

No extra dependency or configuration is required. Start the app normally, wait
for a productivity evaluation, and use the action on the newest history card.

## Dashboard behavior

Only the newest history card can be corrected. Older cards remain visible but
have no correction control. The latest card uses a native HTML form and shows:

- **Actually productive** when the model marked the evaluation off track.
- **Actually off track** when the model marked it productive.
- **Restore model verdict** while a manual override is active.

The effective badge, timeline dot, productive count, rate, latest verdict, and
matching monitor-runtime summary use the user-selected `productive` value. An
active override also shows **Corrected by you**, the original model label, and
**Original model explanation** above the unchanged reason. Restoring the model
verdict removes the active marker and returns the reason label to **Model
explanation**; the append-only correction records remain on disk.

The action remains available while the session is ON, during BREAK, and after
Disable leaves the session OFF, because those modes preserve the current
in-memory history. A new session or process restart clears that history and
therefore removes the control for the old verdict.

## Effective accounting

Each model evaluation records its configured interval as `credited_minutes`
and the productive streak that existed before that interval. When the latest
verdict still belongs to the current streak segment, a correction folds that
same interval again using the new effective label:

- Productive adds `credited_minutes` to the pre-verdict streak. Reaching or
  crossing 30 minutes resets the displayed streak to zero, matching an ordinary
  monitor verdict.
- Off track resets the streak to zero.
- Restoring the model verdict repeats the same calculation with the immutable
  `model_productive` label.

A correction never retroactively emits the original nudge or 30-minute praise;
its only new feedback is the neutral correction acknowledgement described
below. During an active BREAK, the pre-break streak is still preserved, so a
correction can adjust it. Manual or natural break completion resets the streak
and closes that streak segment. A later correction still changes history,
latest-verdict data, and productive-rate totals, but reports
`streak_adjusted: false` and cannot resurrect the ended pre-break streak. OFF
preserves the latest history and can still accept its correction.

## HTTP and `/status` contract

The browser submits a native `POST /verdict/correct` form using the same
form-processing pattern as the other dashboard actions. Flask documents POST
routes and `request.form` in its
[quickstart](https://flask.palletsprojects.com/en/stable/quickstart/), and MDN
documents native [form submission](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/form).

The three required fields are:

| Field | Value |
|---|---|
| `verdict_id` | Server-issued UUID of the displayed latest verdict |
| `expected_revision` | Non-negative integer from its current `correction_revision` |
| `productive` | Explicit desired effective label: lowercase `true` or `false` |

Success follows the dashboard's existing POST/redirect flow and returns HTTP
302. Retrying the immediately preceding successful command is idempotent, as is
a current-revision no-op: either redirects without changing the revision,
appending another event, or generating another acknowledgement. Missing or
malformed fields return HTTP 400. A missing current verdict, an ID that is no
longer latest, or any older revision beyond that immediate retry returns HTTP
409—even if an ABA correction cycle has returned to the requested label. The
UUID and monotonically increasing correction revision prevent an old tab from
overwriting a newer evaluation or replaying an obsolete command after a
correct/restore cycle.

Each `last_verdict` and `evaluation_history` entry in `/status` has these fields:

| Field | Meaning |
|---|---|
| `verdict_id` | Stable UUID for this model evaluation |
| `ts` | ISO timestamp when the model verdict was accepted |
| `model_productive` | Immutable model classification |
| `productive` | Effective classification used by the dashboard and accounting |
| `credited_minutes` | Configured interval credited by this evaluation |
| `correction_revision` | Starts at zero and increments for each accepted change |
| `corrected_at` | ISO time of the active override, or `null` when effective equals model |
| `reason` | Unchanged model-written explanation |
| `observed` | Unchanged model-written visual observation |

The matching result under `runtime.loops.monitor.last_result` retains the raw
scheduler `status`, `model_status`, and `verdict_id`. The dashboard matches that
ID to the latest verdict and renders the effective label, including “corrected
from …” copy when needed. Correcting history does not create a new monitor run.

## Append-only events and failure handling

The original `verdict` JSONL event now includes `verdict_id`, `evaluated_at`,
`model_productive`, effective `productive`, `credited_minutes`,
`correction_revision: 0`, `reason`, and `observed`. The monitor holds the shared
lifecycle coordinator through that append, so a correction cannot overtake its
source event.

Every accepted change appends `verdict_corrected` with:

- `verdict_id`, `evaluated_at`, and immutable `model_productive`;
- `from_productive`, `to_productive`, and `credited_minutes`;
- `correction_revision` and `changed_at`;
- `restored_model_verdict`;
- `streak_adjusted` and the resulting `productive_streak_min`.

Neither event rewrites the original vision exchange. Restoring the model label
appends another correction event rather than deleting history. A transient
JSONL failure leaves the effective in-memory correction applied and retains the
complete event for the existing ordered retry path. Its acknowledgement waits
until that event is durable. A hard termination or persistent I/O failure can
still lose an event that exists only in the retry queue; live verdict history
is not reloaded after restart.

## Spoken acknowledgement and privacy

Each non-idempotent correction queues one AI-written, neutral confirmation. The
text prompt states the correction action and old/new labels, includes the full
session context, and explicitly tells the model not to praise, nudge, challenge
the user, or reinterpret the visual evidence. It needs no hosts-policy approval,
but it cannot become delivery-ready before the correction event is durable.
Model or speech failure does not roll back the correction and the claimed
acknowledgement is not retried.

If the original verdict's feedback is still being generated when a correction
lands, its now-stale utterance is suppressed before speech. Work already sent
to a model can still finish and be logged or stored. The correction does not
cancel or erase the original vision request, response, reason, observation, or
earlier audio that already played.

The correction acknowledgement is a separate Responses API text request. Its
complete prompt and response are logged and stored under `results/llm/`, so the
task, labels, and session-context text may be sent to OpenAI even though no new
image is uploaded. With `TTS_ENGINE=openai`, the resulting utterance text is
also sent to the Speech API; `TTS_ENGINE=pyttsx3` keeps only synthesis and
playback local. See the README's [data, privacy, and cost](../README.md#data-privacy-and-cost)
section for retention and local-storage caveats.

Corrections are not training signals. They are not added to future analyzer
prompts, do not alter the model configuration, and do not teach subsequent
vision calls how to classify similar captures.

## Local security boundary

The dashboard is bound to `127.0.0.1`, but it has no authentication or CSRF
defense. A browser can send a simple cross-origin form POST without allowing the
attacking page to read the response, so an untrusted webpage or local process
could attempt the correction route. UUID/revision validation limits stale
writes but is not authorization. Keep the server loopback-only and do not treat
the correction endpoint—or any other dashboard action—as safe for network
exposure.

## Verification

Run the automated suite from the repository root:

```powershell
uv lock --check
uv run pytest
```

For a manual check:

1. Run `uv run python main.py --dry-hosts --open-browser`, start a session, and
   wait for one productivity evaluation.
2. Use **Actually productive** or **Actually off track**. Confirm the effective
   badge, totals, streak, live announcement, and matching runtime summary change
   while the original model label, explanation, and observation remain visible.
3. Use **Restore model verdict**. Confirm the active correction marker clears,
   totals and eligible streak accounting return to the model label, and the
   control again offers the opposite classification.
4. Inspect `/status` for the fields above and
   `results/sessions/*.jsonl` for one source `verdict` followed by each
   `verdict_corrected` event. Inspect the newest log and `results/llm/` exchange
   for the neutral acknowledgement.
5. Repeat a submitted desired state and confirm it adds no event or speech.
   To reproduce a stale-tab conflict, capture an older form payload (or freeze
   that tab's `/status` polling), apply a correction/restore cycle elsewhere,
   and submit the captured payload. Confirm it receives HTTP 409 instead of
   changing the latest entry. A normally visible tab refreshes every three
   seconds and may replace its stale form before it can be clicked.
6. Correct during BREAK, then finish the break and correct again. Confirm the
   first change can adjust the preserved streak, while the later historical
   change updates the rate without restoring the ended streak or changing break
   allowance, timing, hosts policy, or process targets.
