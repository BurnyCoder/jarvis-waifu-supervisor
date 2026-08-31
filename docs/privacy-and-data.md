# Privacy, data, and cost

Read this before the first real or `--smoke` run. Deep Work is a local
Windows application, but it is not an offline application: its monitoring and
message-generation paths send sensitive content to OpenAI. Local artifacts are
also retained without encryption or automatic deletion.

## What each runtime path handles

“Written locally” describes completed writes, not guaranteed transition-time
durability. Direct capture/exchange writes can fail, and a failed session-event
append can remain only in the process's ordered retry queue until a later retry
succeeds.

| Path | Sent to OpenAI | Written locally |
|---|---|---|
| Productivity monitor | One through `PROGRESS_WINDOW_CAPTURES` chronological stitched JPEGs; the topic; permanent task/preset access groups; any active temporary goal and its groups; the complete analyzer prompt | The newest stitched JPEG, each successfully written request/response exchange, complete prompt/output logging, and the accepted verdict event after its JSONL append succeeds |
| Agent watcher | One current stitched JPEG and the agent-activity prompt | The JPEG and each successfully written request/response exchange; only an actual busy/idle transition attempts an event, which appears in JSONL after its append succeeds |
| Text feedback | A message-specific prompt plus a bounded current-session summary: topic, elapsed time, streak, allowance, relevant access state, break/agent state, and at most five recent observations | Each successfully written request/response exchange and the complete prompt/output log |
| Verdict correction | No new image. A changed correction queues a text prompt containing the old/new labels and the same bounded current-session summary | The append-only correction event after its JSONL append succeeds, then any successfully written acknowledgement exchange; the original vision exchange is unchanged |
| OpenAI speech | Only the utterance text selected for speech | A streamed WAV in the OS temporary directory until successful playback deletes it; speech responses and audio are not copied into `results/llm/` |
| pyttsx3 speech | Nothing for synthesis or playback | Audio is synthesized and played locally; the monitoring and text-generation paths above still use OpenAI |

The default capture combines one screenshot from every physical monitor with
one frame from camera index `0` when that read succeeds. Each tile is resized
to 960 pixels wide, labeled, stacked vertically, and the composite is saved as
a quality-80 JPEG. Productivity vision uses `detail="original"`; agent-watch
vision uses `detail="low"`. “Original” refers to the supplied composite, not
native monitor or camera resolution. See OpenAI's current
[image-input guide](https://developers.openai.com/api/docs/guides/images-vision#choose-an-image-detail-level)
for model-specific sizing and token behavior.

BREAK pauses productivity monitoring. Break-only groups remain in local
events, but are not attached to a productivity capture. An active goal grant
is suspended during BREAK. Agent-busy mode also pauses the productivity
monitor, although agent-watch captures continue while its watcher is eligible.

There is no supported “screen only” or “no webcam” setting. If camera index
`0` is unavailable and its read simply fails, the capture omits that tile and
logs a warning. Verify a saved test capture rather than assuming a privacy
shutter, driver setting, or device choice behaved as intended.

## Local artifact inventory

All paths are relative to the repository root, which is why commands should be
run from that directory.

| Path | Contents and lifetime |
|---|---|
| `logs/deepwork_YYYYMMDD_HHMMSS.log` | A whole-second-named UTF-8 log selected at setup. Textual LLM prompts and semantic outputs are logged completely to this file and the terminal; image base64 is represented by capture filenames. File logging uses append mode, so independent processes started in the same second can share one path. |
| `results/captures/*.jpg` | Sensitive stitched monitor/webcam composites from successful capture persistence. |
| `results/llm/*.json` | Complete successful text, productivity-vision, and agent-watch Responses API objects. Vision requests contain the saved JPEG paths instead of duplicate base64 bytes. Failed API calls and streamed speech are not stored here. |
| `results/sessions/YYYYMMDD.jsonl` | Timestamped session, break, access, agent, verdict, and correction audit events, one JSON object per line. |
| `results/state.json` | Only daily social-allowance usage and previous-topic history. Live sessions, grants, breaks, and verdict history are not restored after restart. |
| OS temporary directory | An OpenAI speech WAV may remain if the API, header repair, playback, or deletion path raises after the temporary file is created. |
| `projects.json`, if created | Local project names and access presets. This file is loaded at startup and is not gitignored. |

These files are ordinary, unencrypted filesystem data. There is no retention
limit, pruning job, or secure-erasure mechanism. Capture, exchange, and state
writes are direct and non-atomic. Session JSONL is the only artifact type with
an ordered in-memory retry path; a hard termination can still lose retained
lines before they reach disk.

The dashboard exposes current in-memory status on loopback but has no
authentication or CSRF defense. It does not serve the saved JPEGs or exchange
JSON directly. Keep the Werkzeug server on `127.0.0.1` and do not expose it as
a network service.

## OpenAI retention and training controls

The application does not pass `store=False` to its Responses API calls.
OpenAI's current
[data-controls documentation](https://developers.openai.com/api/docs/guides/your-data#storage-requirements-and-retention-controls-per-endpoint)
says:

- API data for `/v1/responses` and `/v1/audio/speech` is not used to train
  OpenAI models by default.
- Both endpoints are eligible for abuse-monitoring retention of up to 30 days
  by default.
- Except for documented cases, Responses API application state is retained for
  at least 30 days by default, or when `store=true`.
- Organization-level Zero Data Retention, Modified Abuse Monitoring, regional
  controls, and endpoint/model exceptions can change the applicable behavior.

Treat the linked OpenAI page and the controls on the API organization as the
source of truth at run time; service policy can change independently of this
repository. A ChatGPT subscription does not configure this application's API
organization or billing.

Verdict corrections are not training examples for this app. They do not enter
future analyzer prompts, update a model, or alter the rolling capture window.
Their acknowledgement is still a separate text request to OpenAI.

## Cost shape

The application does not calculate or cap API spend.

- The first successful productivity request in a monitoring context normally
  sends one image. From capture two onward it resends the retained
  oldest-to-newest window, up to `PROGRESS_WINDOW_CAPTURES`.
- A failed analysis can leave its JPEG in that window, so a later successful
  request may include multiple captures even if no earlier verdict was
  accepted.
- Agentic polling adds one low-detail vision request per eligible watcher tick.
- Off-track nudges, 30-minute praise, session/break/access/agent transitions,
  and changed verdict corrections can add text-generation requests.
- Every utterance that reaches the OpenAI speaker adds a Speech API call when
  `TTS_ENGINE=openai`. pyttsx3 removes that speech charge, not the vision or
  text-generation charges.

Image tokenization depends on the selected model, dimensions, and detail.
Use OpenAI's current [pricing](https://developers.openai.com/api/docs/pricing)
and [image-input documentation](https://developers.openai.com/api/docs/guides/images-vision)
rather than a fixed per-session estimate.

## Practical data-minimization checklist

Before a capture-capable run:

1. Close or move password managers, private messages, secrets, customer data,
   health/financial records, and unrelated windows off every captured monitor.
2. Decide whether camera index `0` may be included. If not, make the device
   unavailable and inspect the first saved composite before continuing.
3. Use a narrowly scoped API project/key and review its current data controls
   and spend limits.
4. Prefer `TTS_ENGINE=pyttsx3` when only speech needs to stay local.
5. Remember that `--dry-hosts` is not a privacy or safety mode: after Start it
   can kill configured apps, capture and upload images, call APIs, store
   artifacts, and speak.
6. Remember that `--smoke` performs a real capture and productivity vision
   request. It may also generate text feedback and OpenAI speech depending on
   the verdict and configuration.

After a run:

1. Stop the process before moving or deleting artifacts.
2. Review the newest log, capture, exchange JSON, session JSONL, and any
   leftover temporary WAV before sharing diagnostics.
3. Retain only what is needed. Removing `results/state.json` also resets the
   persisted allowance usage and previous-topic list on the next start; it
   does not remove other audit artifacts.
4. Never commit or force-add `.env`, `logs/`, or `results/`. Review
   `projects.json` before committing because it may contain sensitive names.

See [Troubleshooting](troubleshooting.md) for recovery procedures and
[Verification](verification.md) for a controlled first-run checklist.
