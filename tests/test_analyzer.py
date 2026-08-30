# Tests for deepwork/monitoring/analyzer.py with a FAKE OpenAI client — no
# network, no key. The fake mirrors the two SDK members the analyzer touches:
# client.responses.parse(...) and the returned .output_parsed, per
# https://developers.openai.com/api/docs/guides/structured-outputs

import json
import logging
import pytest
from PIL import Image

from deepwork.monitoring.analyzer import (
    SYSTEM_PROMPT,
    AgentActivityChecker,
    AgentActivityVerdict,
    ProductivityAnalyzer,
    ProductivityVerdict,
)
from deepwork.storage import ResultsStore


class FakeResponses:
    def __init__(self, verdict):
        self.verdict = verdict
        self.last_kwargs = None
        self.calls = []

    def parse(self, **kwargs):
        self.last_kwargs = kwargs                  # captured for assertions
        self.calls.append(kwargs)                  # every rolling evaluation
        verdict = self.verdict                     # close over, not R's self
        # Minimal stand-in for openai.types.responses.ParsedResponse
        class R:
            output_parsed = verdict
            def model_dump(self, **kwargs):        # analyzer persists this
                return {"output_parsed": verdict.model_dump()}
        return R()


class FakeClient:
    def __init__(self, verdict):
        self.responses = FakeResponses(verdict)


def test_verdict_requires_observed_description():
    # The nudge/praise TTS quotes what was seen, so `observed` is a REQUIRED
    # part of the vision contract, and the system prompt must ask for it.
    v = ProductivityVerdict(productive=False, reason="off-topic",
                            observed="Twitter feed open on monitor 2")
    assert "Twitter" in v.observed
    assert "observed" in SYSTEM_PROMPT           # prompt requests the field
    assert "concrete" in SYSTEM_PROMPT.lower()   # ...and concrete specifics
    assert "progress" in SYSTEM_PROMPT.lower()   # compare oldest → newest
    assert "reading" in SYSTEM_PROMPT.lower()    # static-but-valid work caveat
    assert "must set productive true" in SYSTEM_PROMPT.lower()
    assert "panels are not separate chronological captures" in SYSTEM_PROMPT.lower()
    assert "no chronological comparison is available yet" in SYSTEM_PROMPT.lower()
    assert "successive monitoring intervals" in SYSTEM_PROMPT.lower()
    assert "taken 5 minutes apart" not in SYSTEM_PROMPT.lower()


def test_prompt_requires_task_aware_meaningful_snapshot_comparison():
    """Static pixels become a task-aware verdict only when chronology exists."""

    prompt = SYSTEM_PROMPT.lower()
    # Corresponding panels, rather than panels inside one stitched moment, form
    # the chronology that the model must compare from oldest to newest.
    assert "corresponding monitor and webcam panels" in prompt
    assert "for two or more captures" in prompt
    # Artifact-producing tasks normally need visible task-relevant state change,
    # while genuinely static work needs concrete topic-aligned evidence.
    assert "coding, writing, editing, note-taking, debugging, and active research" in prompt
    assert "active research here means visible source navigation" in prompt
    assert "task-directed reading follows the static-work rule" in prompt
    assert "reading, thinking, calls, physical work" in prompt
    assert "visibly running builds, tests, or training" in prompt
    assert "meaningfully unchanged across two or more captures" in prompt
    assert "set productive false" in prompt
    assert "do not invent an exception" in prompt
    # Pixel noise and off-topic movement must never masquerade as progress.
    assert "timestamps, clocks, cursor movement, animations, webcam lighting" in prompt
    assert "minor posture changes" in prompt
    assert "changes alone are incidental and do not establish progress" in prompt
    assert "unrelated visible change" in prompt
    # The unchanged verdict schema stays auditable through its existing text.
    assert "why that evidence is or is not adequate for the stated task" in prompt


def test_prompt_allows_topic_aligned_clarification_resources():
    """A relevant clarification resource may replace the original source onscreen."""

    prompt = SYSTEM_PROMPT.lower()
    # The rule is general across learning formats instead of encoding one subject
    # or one website as a special case.
    assert "learning, research, or problem-solving" in prompt
    assert (
        "explanatory video, lecture, article, documentation page, reference, "
        "worked example, forum explanation"
    ) in prompt
    # A learner may focus on the clarification resource itself without keeping
    # the original book, problem, or artifact visible beside it.
    assert "may be the primary visible activity" in prompt
    assert "need not remain onscreen" in prompt
    assert "without visible artifact creation" in prompt
    # Relevant consumption can establish engagement, but passive UI changes do
    # not justify a false claim that the learner understood or advanced.
    assert "may support current or sustained task-aligned engagement" in prompt
    assert "playback, scrolling, navigation, or source switching" in prompt
    assert "do not by themselves prove conceptual progress" in prompt
    assert "synthesis, notes, application, or other advancement" in prompt
    # Concrete relevance and the existing access contract prevent this rule from
    # turning vaguely adjacent media or an ungranted website into productive work.
    required_evidence = (
        "productive only when concrete visible content connects it to the stated "
        "topic"
    )
    assert required_evidence in prompt
    assert "capture evidence coherently supports task-directed engagement" in prompt
    assert "any governed website/app group must still be explicitly listed" in prompt
    assert (
        "temporary-goal activity must serve both the stated topic and the "
        "explicit temporary goal"
    ) in prompt
    assert (
        "recommendation-feed drift, entertainment, unrelated or merely adjacent "
        "content"
    ) in prompt
    assert "merely topic-sounding title without supporting content" in prompt


def test_prompt_recognizes_tablet_math_as_evidence_backed_static_work():
    """An unchanged exercise can corroborate, but never prove, tablet work."""

    prompt = SYSTEM_PROMPT.lower()
    # A math-specific topic and recognizable exercise establish why an unchanged
    # desktop may be expected while the actual calculation happens elsewhere.
    assert "mathematics worked out on a tablet" in prompt
    assert "unsolved exercise text, equations, or a problem statement" in prompt
    assert "corroborating task-alignment evidence" in prompt
    assert "need not be fully legible" in prompt
    assert "change onscreen while the user solves it on the tablet" in prompt
    # The exception still needs independent webcam evidence of real external work,
    # but ordinary camera framing need not expose the tablet surface itself.
    assert "combine that screen hint with concrete webcam evidence" in prompt
    assert (
        "visible stylus use, handwriting, or a task-directed calculation posture"
        in prompt
    )
    assert "tablet itself may be below or outside the webcam frame" in prompt
    assert "do not require the tablet surface or new handwriting" in prompt
    assert "to be visible in every snapshot" in prompt
    assert "brief calculation or thinking pauses do not break engagement" in prompt
    assert (
        "do not infer a stall solely from the unchanged exercise or desktop"
        in prompt
    )
    assert "even over a long interval" in prompt
    # Sustained engagement is not automatically evidence that the solution advanced.
    assert (
        "supports praise for focus, not a claim that the solution progressed"
        in prompt
    )
    assert "unless chronological evidence shows advancement" in prompt
    # Neither props nor generic body position may turn the exception into a loophole.
    assert "exercise displayed by itself" in prompt
    assert (
        "generic looking down, minor posture changes, or holding a stylus"
        in prompt
    )
    assert "without task-directed engagement do not prove productivity" in prompt
    assert (
        "clear unrelated browsing, media, chat, or gaming remains unproductive"
        in prompt
    )


def test_prompt_treats_partial_music_video_as_neutral_only_beside_real_work():
    """A background music video cannot excuse missing or stalled task progress."""

    prompt = SYSTEM_PROMPT.lower()
    # A secondary music video is tolerated only beside evidence that independently
    # satisfies the existing single-capture engagement or rolling-progress rules.
    assert "music video occupying only a secondary part of a monitor" in prompt
    assert (
        "remaining work area shows genuine task-aligned engagement"
    ) in prompt
    assert (
        "with two or more captures, meaningful task-relevant progress"
    ) in prompt
    # Playback changes are animation, not evidence that the user's work advanced.
    assert (
        "never count changing video frames, animation, playback bars, timestamps, "
        "titles"
    ) in prompt
    # Capture one must keep the established engagement-only behavior because it
    # has no earlier image from which progress could be inferred.
    assert "on one capture, treat the music video as neutral" in prompt
    assert "without claiming progress" in prompt
    # The narrow exception ends when background media replaces or outlasts work.
    assert "work area is stalled or lacks task-aligned evidence" in prompt
    assert "video is the primary activity" in prompt
    assert "ordinary video and access rules" in prompt


def test_productive_reason_prompt_requests_creative_grounded_encouragement():
    # Positive speech should celebrate the specific visible work without
    # turning "Good job" into one repetitive canned prefix on every check.
    prompt = SYSTEM_PROMPT.lower()
    assert "when productive is true" in prompt
    assert "in the spirit of 'good job'" in prompt
    assert "affirmation tied to the observed work" in prompt
    assert "vary the wording rather than using a fixed catchphrase" in prompt
    # A first capture can support praise for present engagement, not a claim
    # about progress across time that the model has not observed yet.
    assert (
        "for exactly one capture, affirm only current task-aligned engagement"
    ) in prompt
    assert (
        "do not claim progress, improvement, advancement, or any change over time"
    ) in prompt
    # Later praise must remain evidence-grounded, and negative verdicts must
    # never congratulate the user for work the monitor judged off-track.
    assert "for two or more captures" in prompt
    assert "praise progress only when visible changes or other capture evidence" in prompt
    assert "praise the engagement or focus instead" in prompt
    assert "when productive is false" in prompt
    assert "include no praise or congratulations" in prompt
    assert "naming the concrete evidence for the verdict" in prompt


def make_analyzer(tmp_path, verdict=None, window_size=5):
    verdict = verdict or ProductivityVerdict(productive=True, reason="deep in code",
                                             observed="IDE with tests running")
    client = FakeClient(verdict)
    store = ResultsStore(tmp_path)
    analyzer = ProductivityAnalyzer(client=client, model="test-model",
                                    store=store, window_size=window_size)
    return analyzer, client, store


def save_capture(store):
    return store.save_capture(Image.new("RGB", (8, 8), "blue"))


def save_named_capture(store, name, color):
    # Distinct filenames and pixels make rolling-window order observable even
    # when several test images are created inside the same clock second.
    path = store.root / "captures" / name
    Image.new("RGB", (8, 8), color).save(path, "JPEG")
    return path


def image_urls(call):
    # Extract only the image parts from one captured Responses API request.
    return [part["image_url"] for part in call["input"][-1]["content"]
            if part["type"] == "input_image"]


def test_every_capture_evaluates_available_rolling_window(tmp_path):
    analyzer, client, store = make_analyzer(tmp_path, window_size=3)
    paths = [
        save_named_capture(store, "01.jpg", "red"),
        save_named_capture(store, "02.jpg", "green"),
        save_named_capture(store, "03.jpg", "blue"),
        save_named_capture(store, "04.jpg", "yellow"),
    ]

    # Warm-up evaluates 1, then 2, then 3 captures; the fourth call remains
    # bounded at 3 and discards only the oldest capture.
    assert all(analyzer.add_capture(path, topic="thesis").productive
               for path in paths)
    assert [len(image_urls(call)) for call in client.responses.calls] == [1, 2, 3, 3]
    third_window = image_urls(client.responses.calls[2])
    fourth_window = image_urls(client.responses.calls[3])
    assert fourth_window[:2] == third_window[1:]  # oldest was evicted
    assert fourth_window[-1] not in third_window  # newest was appended


def test_request_shape_matches_responses_api(tmp_path):
    analyzer, client, store = make_analyzer(tmp_path, window_size=2)
    analyzer.add_capture(save_named_capture(store, "01.jpg", "red"), topic="thesis")
    analyzer.add_capture(save_named_capture(store, "02.jpg", "blue"), topic="thesis")
    kwargs = client.responses.last_kwargs
    assert kwargs["model"] == "test-model"
    assert kwargs["reasoning"] == {"effort": "medium"}
    assert kwargs["text_format"] is ProductivityVerdict
    user_content = kwargs["input"][-1]["content"]
    images = [c for c in user_content if c["type"] == "input_image"]
    assert len(images) == 2                        # every batched capture sent
    # Dense stitched computer screens use original detail so small document,
    # code, and UI changes survive image processing:
    # https://developers.openai.com/api/docs/guides/images-vision#choose-an-image-detail-level
    assert all(i["image_url"].startswith("data:image/jpeg;base64,") for i in images)
    assert all(i["detail"] == "original" for i in images)
    # Persisted exchanges replace base64 with capture-file references while
    # retaining the exact detail level needed to audit model behavior.
    exchange_path = max((tmp_path / "llm").glob("*_vision.json"))
    exchange = json.loads(exchange_path.read_text(encoding="utf-8"))
    stored_content = exchange["request"]["input"][-1]["content"]
    stored_images = [part for part in stored_content
                     if part["type"] == "input_image"]
    assert all(part["detail"] == "original" for part in stored_images)
    assert all("file" in part and "image_url" not in part for part in stored_images)
    # The user's topic is in the text part so the model judges relevance.
    texts = [c for c in user_content if c["type"] == "input_text"]
    assert any("thesis" in t["text"] for t in texts)
    # A sequence label immediately precedes each stitched image so simultaneous
    # Monitor 1/Monitor 2/Webcam panels are not mistaken for time progression.
    assert any("Chronological capture 1 of 2" in t["text"] for t in texts)
    assert any("Chronological capture 2 of 2" in t["text"] for t in texts)
    assert all("one stitched image" in t["text"] for t in texts[1:])


def test_request_marks_task_access_groups_as_conditional_not_automatic_progress(
    tmp_path,
):
    analyzer, client, store = make_analyzer(tmp_path)
    analyzer.add_capture(
        save_named_capture(store, "01.jpg", "red"),
        topic="publish a launch update",
        allowed_groups=("discord", "telegram"),
    )
    header = client.responses.last_kwargs["input"][-1]["content"][0]["text"]
    # Discord is one dual website/app choice and Telegram is app-only, but both
    # use the same policy-owned label expansion in the prompt.
    assert "Permanent task-required website/app access groups: Discord, Telegram" in header
    assert "does not automatically make the activity productive" in header
    assert "visibly serves the stated topic" in header
    assert "allowed website or app" in header
    assert "unless" in SYSTEM_PROMPT.lower()
    assert "explicitly lists" in SYSTEM_PROMPT.lower()
    assert "website/app access group" in SYSTEM_PROMPT.lower()


def test_request_distinguishes_temporary_goal_access_from_permanent_task_groups(
    tmp_path,
):
    analyzer, client, store = make_analyzer(tmp_path)
    full_goal = (
        "Find the complete launch quotation and its surrounding context, then "
        "copy both into the research notes without omitting any qualifiers."
    )

    analyzer.add_capture(
        save_named_capture(store, "01.jpg", "red"),
        topic="prepare the product launch brief",
        allowed_groups=("discord",),
        goal_access_goal=full_goal,
        goal_access_groups=("telegram", "steam"),
    )

    header = client.responses.last_kwargs["input"][-1]["content"][0]["text"]
    assert "Permanent task-required website/app access groups: Discord" in header
    assert "Temporary goal-access website/app access groups: Telegram, Steam" in header
    assert full_goal in header
    assert "both the overall deep-work topic and the explicit temporary goal" in header
    assert "never automatically productive" in header
    assert "allowed website or app" in header
    system_prompt = SYSTEM_PROMPT.lower()
    assert "permanently required" in system_prompt
    assert "temporary goal access" in system_prompt
    assert "both the overall topic and the explicit temporary goal" in system_prompt


def test_request_without_goal_access_describes_inactive_grant(tmp_path):
    analyzer, client, store = make_analyzer(tmp_path)

    analyzer.add_capture(
        save_named_capture(store, "01.jpg", "red"),
        topic="write the thesis",
        allowed_groups=("discord",),
    )

    header = client.responses.last_kwargs["input"][-1]["content"][0]["text"]
    assert "Permanent task-required website/app access groups: Discord" in header
    assert "No temporary goal-access grant is active" in header


@pytest.mark.parametrize(
    "legacy_kwargs",
    [
        {"allowed_sites": ("discord",)},
        {"goal_access_sites": ("telegram",)},
    ],
)
def test_request_rejects_legacy_site_only_arguments(tmp_path, legacy_kwargs):
    """The clean-break analyzer API accepts only canonical access groups."""

    analyzer, _, store = make_analyzer(tmp_path)
    with pytest.raises(TypeError):
        analyzer.add_capture(
            save_named_capture(store, "01.jpg", "red"),
            topic="write the thesis",
            **legacy_kwargs,
        )


def test_request_protects_one_capture_then_compares_from_second(tmp_path):
    analyzer, client, store = make_analyzer(tmp_path, window_size=3)
    paths = [
        save_named_capture(store, "01.jpg", "red"),
        save_named_capture(store, "02.jpg", "green"),
        save_named_capture(store, "03.jpg", "blue"),
    ]

    analyzer.add_capture(paths[0], topic="thesis")
    first_header = client.responses.calls[-1]["input"][-1]["content"][0]["text"]
    assert "SINGLE CAPTURE (1/3)" in first_header
    assert "cannot establish a stall" in first_header
    assert "No chronological comparison is available" in first_header

    analyzer.add_capture(paths[1], topic="thesis")
    second_header = client.responses.calls[-1]["input"][-1]["content"][0]["text"]
    assert "COMPARISON (2/3)" in second_header
    assert "task-dependent stall" in second_header
    assert "meaningfully unchanged" in second_header

    analyzer.add_capture(paths[2], topic="thesis")
    full_header = client.responses.calls[-1]["input"][-1]["content"][0]["text"]
    assert "COMPARISON (3/3)" in full_header
    assert "whole available window" in full_header


def test_complete_text_prompt_and_structured_output_are_logged(tmp_path, caplog):
    verdict = ProductivityVerdict(
        productive=True,
        reason="The implementation is moving.",
        observed="VS Code shows the new rolling-window test.",
    )
    analyzer, _, store = make_analyzer(
        tmp_path,
        verdict=verdict,
        window_size=2,
    )

    with caplog.at_level(logging.INFO, logger="deepwork.monitoring.analyzer"):
        analyzer.add_capture(
            save_named_capture(store, "01.jpg", "red"),
            topic="thesis",
        )

    assert SYSTEM_PROMPT in caplog.text
    assert "SINGLE CAPTURE (1/2)" in caplog.text
    assert "Chronological capture 1 of 1" in caplog.text
    assert verdict.reason in caplog.text
    assert verdict.observed in caplog.text


def test_agent_activity_checker_request_shape_and_persistence(tmp_path):
    verdict = AgentActivityVerdict(agent_working=True, reason="tokens streaming")
    client = FakeClient(verdict)
    store = ResultsStore(tmp_path)
    checker = AgentActivityChecker(
        client=client,
        model="test-model",
        store=store,
    )

    result = checker.check(save_capture(store))
    assert result.agent_working is True
    kwargs = client.responses.last_kwargs
    assert kwargs["model"] == "test-model"
    assert kwargs["reasoning"] == {"effort": "medium"}
    assert kwargs["text_format"] is AgentActivityVerdict
    user_content = kwargs["input"][-1]["content"]
    images = [c for c in user_content if c["type"] == "input_image"]
    # Exactly ONE low-detail capture per check (fast 60s cadence, cheap).
    assert len(images) == 1 and images[0]["detail"] == "low"
    assert images[0]["image_url"].startswith("data:image/jpeg;base64,")
    # Full exchange persisted under its own kind for auditability.
    exchange_path = next((tmp_path / "llm").glob("*_agent_watch.json"))
    exchange = json.loads(exchange_path.read_text(encoding="utf-8"))
    stored_content = exchange["request"]["input"][-1]["content"]
    stored_image = next(part for part in stored_content
                        if part["type"] == "input_image")
    assert stored_image["detail"] == "low"
    assert "file" in stored_image and "image_url" not in stored_image


def test_exchange_persisted_each_tick_and_reset_clears_window(tmp_path):
    analyzer, client, store = make_analyzer(tmp_path, window_size=2)
    analyzer.add_capture(save_named_capture(store, "01.jpg", "red"), topic="t")
    analyzer.add_capture(save_named_capture(store, "02.jpg", "blue"), topic="t")
    saved = list((tmp_path / "llm").glob("*.json"))
    assert len(saved) == 2                         # one full exchange per tick

    analyzer.reset()
    analyzer.add_capture(save_named_capture(store, "03.jpg", "green"), topic="t")
    assert len(image_urls(client.responses.last_kwargs)) == 1


@pytest.mark.parametrize("window_size", [0, 1])
def test_window_size_must_allow_capture_two_comparison(tmp_path, window_size):
    # The product contract starts chronological comparison at capture two, so
    # a one-slot deque would silently disable the feature it claims to provide.
    with pytest.raises(ValueError, match="at least 2"):
        make_analyzer(tmp_path, window_size=window_size)
