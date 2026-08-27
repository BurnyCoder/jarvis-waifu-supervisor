# OpenAI vision productivity analyzer (requirement 3). Global context: every
# active monitor tick appends one stitched capture to a bounded rolling window,
# then one vision call compares all currently available captures.
# OpenAI supports multiple images in one Responses content array:
# https://developers.openai.com/api/docs/guides/images-vision#giving-a-model-images-as-input
# Structured outputs via responses.parse:
# https://developers.openai.com/api/docs/guides/structured-outputs
# Vision input format: https://developers.openai.com/api/docs/guides/images-vision

import base64
import logging
from collections import deque
from pathlib import Path

# pydantic BaseModel doubles as the JSON schema the API is forced to follow:
# https://docs.pydantic.dev/latest/concepts/models/
from pydantic import BaseModel

from deepwork.access_policy import access_labels
from deepwork.storage import ResultsStore

log = logging.getLogger(__name__)

# Dense stitched desktop captures need their original pixels so small code,
# document, and UI changes remain visible to the productivity model. The fast
# one-image agent watcher keeps low detail because it only needs coarse status:
# https://developers.openai.com/api/docs/guides/images-vision#choose-an-image-detail-level
PRODUCTIVITY_IMAGE_DETAIL = "original"
AGENT_IMAGE_DETAIL = "low"

# System prompt: sets the judging persona; ordinary productive reasons are
# spoken without another text-model pass, so their acknowledgment belongs here.
# The tablet-math exception treats visible exercise text as corroborating
# context when webcam evidence supports external work despite camera framing.
# The music-video exception keeps secondary background media neutral while the
# independent work evidence remains responsible for every productive verdict.
# Concrete writing choices are more reliable than broad tone labels:
# https://developers.openai.com/api/docs/guides/latest-model#prompting-best-practices
SYSTEM_PROMPT = (
    "You are a gentle, encouraging productivity coach. You receive a series of "
    "labeled captures from successive monitoring intervals during a deep-work "
    "session, ordered oldest to newest. Each chronological capture is one "
    "stitched image containing panels labeled Monitor 1, Monitor 2, and, when "
    "available, Webcam; those panels are not separate chronological captures. "
    "Use the explicit chronological capture labels as the only timeline. For "
    "two or more captures, compare corresponding monitor and webcam panels from "
    "oldest to newest. Judge both whether the work matches the stated topic and "
    "whether meaningful task-relevant progress or engagement is visible. Tasks "
    "that normally create visible artifacts or interactions—coding, writing, "
    "editing, note-taking, debugging, and active research—should show relevant "
    "changes. Active research here means visible source navigation, annotation, "
    "synthesis, or note-taking; task-directed reading follows the static-work "
    "rule. If those screens are meaningfully unchanged across two or more "
    "captures and no other task-aligned engagement is visible, set productive "
    "false and explain the stall gently. Work that can legitimately keep a "
    "screen static—reading, thinking, calls, physical work, or waiting on "
    "visibly running builds, tests, or training—may remain productive only when "
    "the stated topic and concrete screen or webcam evidence support genuine "
    "engagement. Mathematics worked out on a tablet is one such physical task. "
    "When the stated topic is concretely mathematics-related, visible unsolved "
    "exercise text, equations, or a problem statement on a monitor is "
    "corroborating task-alignment evidence: it need not be fully legible, but "
    "must be visibly recognizable as relevant mathematical work, and it need not "
    "change onscreen while the user solves it on the tablet. Combine that screen "
    "hint with concrete webcam evidence such as visible stylus use, handwriting, "
    "or a task-directed calculation posture. The tablet itself may be below or "
    "outside the webcam frame; do not require the tablet surface or new handwriting "
    "to be visible in every snapshot. A stylus used or held ready while attention "
    "is directed toward the likely work surface may corroborate the exercise, and "
    "brief calculation or thinking pauses do not break engagement when surrounding "
    "captures support the combined task context. When this combined evidence "
    "continues across multiple captures, treat it as sustained task-aligned "
    "engagement and do not infer a stall solely from the unchanged exercise or "
    "desktop, even over a long interval. This supports praise for focus, not a "
    "claim that the solution progressed unless chronological evidence shows "
    "advancement. An exercise displayed by itself, mere tablet presence, generic "
    "looking down, minor posture changes, or holding a stylus without task-directed "
    "engagement do not prove productivity. Clear unrelated browsing, media, chat, "
    "or gaming remains unproductive. If the task "
    "is vague or ambiguous, do not invent an exception: "
    "meaningfully unchanged captures without concrete task-aligned evidence are "
    "unproductive. An unrelated visible change is not progress. Timestamps, "
    "clocks, cursor movement, animations, webcam lighting, or minor posture "
    "changes alone are incidental and do not establish progress. With only one "
    "capture, judge current task alignment and explicitly avoid claiming a "
    "trend that cannot yet be seen. If that single capture shows genuine "
    "task-aligned engagement, you must set productive true; missing comparison "
    "history alone must never make the verdict false. For exactly one capture, "
    "the observed field must describe only the current scene and end with "
    "'No chronological comparison is available yet'; never call it progress, "
    "no progress, advanced, or stalled. Obey the evaluation rule in the user "
    "message. Social media, video, chat, and games are unproductive "
    "unless the user message explicitly lists that website/app access group either as "
    "permanently required for the task, with visible activity that serves the "
    "stated overall topic, or as temporary goal access, with visible activity "
    "that serves both the overall topic and the explicit temporary goal. "
    "Merely seeing any allowed website or app never proves productivity; unrelated "
    "feeds, chats, videos, and games remain unproductive. A music video occupying "
    "only a secondary part of a monitor may be neutral work-supporting background "
    "media: do not mark it off-track when the remaining work area shows genuine "
    "task-aligned engagement and, with two or more captures, meaningful "
    "task-relevant progress. Never count changing video frames, animation, "
    "playback bars, timestamps, titles, or other playback changes as progress. "
    "On one capture, treat the music video as neutral and apply the current-"
    "engagement rule without claiming progress. If the work area is stalled or "
    "lacks task-aligned evidence, or the video is the primary activity, this "
    "exception does not apply; use the ordinary video and access rules. When "
    "productive is true, "
    "integrate a brief, natural affirmation tied to the observed work into the "
    "reason, in the spirit of 'Good job' (for example, 'Nice work' or 'Great "
    "focus'); vary the wording rather than using a fixed catchphrase. For "
    "exactly one capture, affirm only current task-aligned engagement and do "
    "not claim progress, improvement, advancement, or any change over time. "
    "For two or more captures, praise progress only when visible changes or "
    "other capture evidence across the series support it; if productive "
    "engagement is supported but progress is not, praise the engagement or "
    "focus instead. When productive is false, state the problem gently and "
    "include no praise or congratulations. Reply with: productive true/false; "
    "reason - one short, kind, speech-ready sentence naming the concrete "
    "evidence for the verdict; and observed - for two or more captures, a "
    "concrete oldest-to-newest account of what materially changed or stayed "
    "static in the corresponding panels and why that evidence is or is not "
    "adequate for the stated task. Name visible apps, sites, window titles, "
    "content, monitors, and webcam presence so a coach can quote it back."
)


class ProductivityVerdict(BaseModel):
    # The exact JSON contract from the spec: productive yes/no + reason —
    # plus `observed`, the concrete what-I-saw description the TTS messages
    # quote back to the user ("you had Twitter open on monitor 2...").
    productive: bool
    reason: str
    observed: str


# Agentic mode: is the user's AI coding agent still working? Judged from ONE
# capture per poll (fast cadence beats batched depth for this question).
AGENT_WATCH_PROMPT = (
    "You are watching a developer's screens for agentic engineering. Decide "
    "whether an AI coding agent (e.g. Claude Code, Cursor, Copilot, a "
    "terminal/IDE agent) is ACTIVELY WORKING on any monitor right now: look "
    "for streaming/generating output, running tools or commands, progress "
    "spinners, or 'esc to interrupt'-style status lines. It is NOT working "
    "if it shows a finished response waiting for user input, a permission "
    "prompt awaiting approval, or no agent is visible at all. Reply with "
    "agent_working true/false and one short sentence of evidence."
)


class AgentActivityVerdict(BaseModel):
    # Structured contract for the agent-watch poll.
    agent_working: bool
    reason: str


class AgentActivityChecker:
    """One-capture vision check: is the AI agent on screen still busy?"""

    def __init__(
        self,
        client,
        model: str,
        store: ResultsStore,
        reasoning_effort: str = "medium",
    ):
        self.client = client                      # openai.OpenAI or test fake
        self.model = model
        self.store = store
        self.reasoning_effort = reasoning_effort

    def check(self, path: Path) -> AgentActivityVerdict:
        # Same responses.parse structured-output call as the productivity
        # analyzer, but a single low-detail image per poll. Responses nests
        # the explicitly selected reasoning effort under `reasoning`:
        # https://developers.openai.com/api/docs/guides/structured-outputs
        # https://developers.openai.com/api/docs/guides/reasoning#get-started-with-reasoning
        user_content = [
            {"type": "input_text", "text": "Current capture of all monitors follows."},
            {"type": "input_image", "image_url": _image_to_data_url(path),
             "detail": AGENT_IMAGE_DETAIL},
        ]
        request = {"model": self.model,
                   "reasoning": {"effort": self.reasoning_effort},
                   "input": [{"role": "system", "content": AGENT_WATCH_PROMPT},
                             {"role": "user", "content": user_content}],
                   "text_format": AgentActivityVerdict}
        log.info(
            "agent-watch request: model=%s reasoning=%s capture=%s system=%r user=%r",
            self.model,
            self.reasoning_effort,
            path.name,
            AGENT_WATCH_PROMPT,
            user_content[0]["text"],
        )
        response = self.client.responses.parse(**request)
        verdict: AgentActivityVerdict = response.output_parsed
        log.info("agent-watch verdict: working=%s reason=%s",
                 verdict.agent_working, verdict.reason)
        stored_request = {**request,
                          "text_format": AgentActivityVerdict.__name__,
                          "input": [request["input"][0],
                                    {"role": "user",
                                     "content": [user_content[0],
                                                 {"type": "input_image",
                                                  "file": str(path),
                                                  "detail": AGENT_IMAGE_DETAIL}]}]}
        self.store.save_llm_exchange("agent_watch", stored_request,
                                     response.model_dump(mode="json", warnings=False))
        return verdict


def _image_to_data_url(path: Path) -> str:
    # Vision API accepts base64 data URLs for local files:
    # https://developers.openai.com/api/docs/guides/images-vision#giving-a-model-images-as-input
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


def _evaluation_rule(capture_count: int, window_size: int) -> str:
    """Describe whether the current request can support a progress comparison."""

    if capture_count == 1:
        # A first image can prove present distraction or engagement, but it has
        # no earlier state from which to infer progress or a stall.
        return (
            f"SINGLE CAPTURE ({capture_count}/{window_size}): this capture "
            "cannot establish a stall. No chronological comparison is available; "
            "judge only current task alignment and visible engagement."
        )
    # From capture two onward, every available oldest-to-newest image is valid
    # evidence; filling the maximum deque is not a prerequisite for a verdict.
    return (
        f"COMPARISON ({capture_count}/{window_size}): compare the whole available "
        "window. A meaningfully unchanged scene may establish a task-dependent "
        "stall under the task and evidence rules in the system prompt."
    )


class ProductivityAnalyzer:
    def __init__(self, client, model: str, store: ResultsStore,
                 window_size: int = 5, reasoning_effort: str = "medium"):
        # client injected (real openai.OpenAI in prod, fake in tests).
        if window_size < 2:
            # A one-slot deque could evaluate alignment but could never reach
            # the capture-two comparison promised by this analyzer.
            raise ValueError("window_size must be at least 2")
        self.client = client
        self.model = model
        self.store = store
        self.window_size = window_size
        self.reasoning_effort = reasoning_effort
        # A bounded deque automatically evicts the oldest item on append:
        # https://docs.python.org/3/library/collections.html#collections.deque
        self._window: deque[Path] = deque(maxlen=window_size)

    def reset(self) -> None:
        """Start a fresh progress window for a newly started work session."""
        self._window.clear()
        log.info("progress window reset")

    def add_capture(
        self,
        path: Path,
        topic: str,
        allowed_groups: tuple[str, ...] = (),
        goal_access_goal: str | None = None,
        goal_access_groups: tuple[str, ...] = (),
    ) -> ProductivityVerdict:
        """Append one capture and evaluate every available recent capture."""
        self._window.append(path)
        window = list(self._window)                # stable oldest→newest snapshot
        log.info("progress window updated (%d/%d): %s",
                 len(window), self.window_size,
                 ", ".join(capture.name for capture in window))
        return self._analyze(
            window,
            topic,
            allowed_groups,
            goal_access_goal,
            goal_access_groups,
        )

    def _analyze(
        self,
        window: list[Path],
        topic: str,
        allowed_groups: tuple[str, ...] = (),
        goal_access_goal: str | None = None,
        goal_access_groups: tuple[str, ...] = (),
    ) -> ProductivityVerdict:
        # User content: one text part naming the topic + one input_image per
        # capture. Multiple images in one content array are documented at:
        # https://developers.openai.com/api/docs/guides/images-vision#giving-a-model-images-as-input
        # Original detail preserves dense desktop pixels for task-progress
        # comparison; each image still counts toward request tokens:
        # https://developers.openai.com/api/docs/guides/images-vision#choose-an-image-detail-level
        # Put the chronology rule beside the current count so one image cannot
        # be mistaken for a comparison and capture two can establish a stall.
        phase_rule = _evaluation_rule(len(window), self.window_size)
        capture_summary = (
            "1 chronological capture follows"
            if len(window) == 1
            else f"{len(window)} chronological captures follow"
        )
        # Keep permanent task requirements separate from a temporary grant so
        # the model does not mistake website/app access for evidence of progress.
        # OpenAI recommends prompts state the goal, context, constraints, and
        # required evidence explicitly:
        # https://developers.openai.com/api/docs/guides/latest-model#prompting-best-practices
        permanent_labels = (
            ", ".join(access_labels(allowed_groups)) if allowed_groups else "none"
        )
        permanent_access_rule = (
            "Permanent task-required website/app access groups: "
            f"{permanent_labels}. Seeing a permanently allowed website or app "
            "does not automatically make "
            "the activity productive; it must show activity that visibly "
            "serves the stated topic."
        )
        if goal_access_goal is not None:
            temporary_labels = (
                ", ".join(access_labels(goal_access_groups))
                if goal_access_groups
                else "none"
            )
            temporary_access_rule = (
                "Temporary goal-access website/app access groups: "
                f"{temporary_labels}. Explicit temporary goal: "
                f"{goal_access_goal!r}. While this grant is active, a "
                "productive verdict requires visible activity to serve both "
                "the overall deep-work topic and the explicit temporary goal. "
                "A temporarily allowed website or app is never automatically "
                "productive; unrelated browsing, chat, video, or gaming remains "
                "unproductive."
            )
        else:
            temporary_access_rule = (
                "No temporary goal-access grant is active."
            )
        header = {"type": "input_text",
                  "text": f"My deep-work topic: {topic}. "
                          f"{permanent_access_rule} "
                          f"{temporary_access_rule} "
                          f"{capture_summary}, oldest first. "
                          f"{phase_rule}"}
        user_content = [header]
        stored_content = [header]
        for index, path in enumerate(window, start=1):
            # Interleaved labels make the temporal boundary explicit: each
            # following image contains the panels from one monitoring tick.
            label = {
                "type": "input_text",
                "text": f"Chronological capture {index} of {len(window)}: "
                        "one stitched image with monitor/webcam panels from one "
                        "monitoring tick.",
            }
            user_content.extend([
                label,
                {"type": "input_image",
                 "image_url": _image_to_data_url(path),
                 "detail": PRODUCTIVITY_IMAGE_DETAIL},
            ])
            # Persist the same uncut text prompt while referring to the already
            # stored JPEG instead of duplicating its large base64 payload.
            stored_content.extend([
                label,
                {"type": "input_image", "file": str(path),
                 "detail": PRODUCTIVITY_IMAGE_DETAIL},
            ])
        request = {"model": self.model,
                   # Responses nests effort under `reasoning`; GPT-5.6 supports
                   # medium as its balanced starting point:
                   # https://developers.openai.com/api/docs/guides/latest-model#update-api-and-model-parameters
                   "reasoning": {"effort": self.reasoning_effort},
                   "input": [{"role": "system", "content": SYSTEM_PROMPT},
                             {"role": "user", "content": user_content}],
                   "text_format": ProductivityVerdict}
        # Log every textual prompt part uncut; name image files instead of
        # dumping base64 bytes because the exact JPEGs are already persisted.
        prompt_text = [
            SYSTEM_PROMPT,
            *(part["text"] for part in user_content
              if part["type"] == "input_text"),
        ]
        log.info(
            "vision request: model=%s reasoning=%s image_detail=%s prompt=%r "
            "capture_files=%s",
            self.model,
            self.reasoning_effort,
            PRODUCTIVITY_IMAGE_DETAIL,
            prompt_text,
            ", ".join(path.name for path in window),
        )
        # responses.parse validates the reply against ProductivityVerdict and
        # retries malformed JSON at the API layer:
        # https://github.com/openai/openai-python#structured-outputs
        response = self.client.responses.parse(**request)
        verdict: ProductivityVerdict = response.output_parsed
        log.info(
            "vision output: productive=%s reason=%s observed=%s",
            verdict.productive,
            verdict.reason,
            verdict.observed,
        )
        # Persist the whole exchange; data URLs are elided from the stored
        # request (the JPEGs already live in results/captures/).
        stored_request = {**request,
                          "text_format": ProductivityVerdict.__name__,
                          "input": [request["input"][0],
                                    {"role": "user",
                                     "content": stored_content}]}
        # mode="json" + warnings=False silences pydantic's union-serializer
        # noise when dumping the SDK's ParsedResponse (harmless but loud):
        # https://docs.pydantic.dev/latest/concepts/serialization/#serialization-warnings
        self.store.save_llm_exchange("vision", stored_request,
                                     response.model_dump(mode="json", warnings=False))
        return verdict
