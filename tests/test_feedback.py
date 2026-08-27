# Tests for deepwork/feedback/messages.py and tts.py — OpenAI text calls are
# faked (no network); the TTS queue is tested with an injected speak function.

import struct
import threading
import time
from datetime import datetime

from deepwork.feedback.goal_access import (
    GoalAccessFeedbackQueue,
    queue_goal_access_feedback,
    queue_transition_feedback,
)
from deepwork.feedback.messages import MessageGenerator, build_prompt
from deepwork.feedback.tts import SpeechQueue, fix_streamed_wav_header
from deepwork.state import SessionState
from deepwork.storage import ResultsStore


class FakeResponses:
    def __init__(self):
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        class R:                                    # stand-in for Response
            output_text = "You've got this!"        # SDK convenience property:
            # https://github.com/openai/openai-python (responses.create)
            def model_dump(self):
                return {"output_text": self.output_text}
        return R()


class FakeClient:
    def __init__(self):
        self.responses = FakeResponses()


def test_build_prompt_covers_all_message_kinds():
    # Each spec message type has a dedicated prompt containing its context.
    CTX = "topic: thesis / streak: 10 min / seen: Twitter on monitor 2"
    assert "write thesis" in build_prompt("good_luck", topic="write thesis",
                                          session_context=CTX)
    p = build_prompt("nudge", topic="thesis", reason="watching videos",
                     observed="YouTube video about cats on monitor 1",
                     session_context=CTX)
    assert "watching videos" in p and "gentle" in p.lower()
    p = build_prompt("praise", topic="thesis", reason="focused coding",
                     observed="IDE with thesis.tex open", session_context=CTX)
    assert "30" in p                                # praise is for 30 minutes
    p = build_prompt("break_ack", purpose="coffee", minutes=10,
                     session_context=CTX)
    assert "coffee" in p and "10" in p
    p = build_prompt("break_end_ack", purpose="coffee", charged_minutes=2,
                     session_context=CTX)
    assert "coffee" in p and "2" in p and "back" in p.lower()
    p = build_prompt(
        "goal_access_start",
        goal="collect the exact launch quotation",
        group_labels="Discord and Telegram",
        duration_description="for 12 minutes",
        session_context=CTX,
    )
    assert "collect the exact launch quotation" in p
    assert "Discord and Telegram" in p
    assert "for 12 minutes" in p
    p = build_prompt(
        "goal_access_end",
        goal="collect the exact launch quotation",
        group_labels="Discord and Telegram",
        end_reason="the user marked the goal complete",
        session_context=CTX,
    )
    assert "collect the exact launch quotation" in p
    assert "Discord and Telegram" in p
    assert "the user marked the goal complete" in p
    p = build_prompt(
        "verdict_correction",
        correction_action="corrected the monitor",
        from_label="off track",
        to_label="productive",
        session_context=CTX,
    )
    assert "corrected the monitor" in p
    assert "off track" in p and "productive" in p
    assert "do not praise" in p.lower() and "do not nudge" in p.lower()


def test_all_prompts_carry_session_context_and_nudge_quotes_observed():
    # User requirement: TTS mentions what it SAW and has broad context.
    CTX = "42 minutes in; allowance 90 min left; last seen: Discord chat"
    for kind, extra in [("good_luck", {"topic": "t"}),
                        ("nudge", {"topic": "t", "reason": "r",
                                   "observed": "Reddit front page on monitor 2"}),
                        ("praise", {"topic": "t", "reason": "r",
                                    "observed": "VS Code running tests"}),
                        ("break_ack", {"purpose": "p", "minutes": 5}),
                        ("break_end_ack", {"purpose": "p",
                                           "charged_minutes": 2}),
                        ("agent_running", {"reason": "spinner visible"}),
                        ("agent_done", {"reason": "response finished"}),
                        ("goal_access_start", {
                            "goal": "collect citations",
                            "group_labels": "Discord",
                            "duration_description": "until the task ends",
                        }),
                        ("goal_access_end", {
                            "goal": "collect citations",
                            "group_labels": "Discord",
                            "end_reason": "the timer expired",
                        }),
                        ("verdict_correction", {
                            "correction_action": "corrected the monitor",
                            "from_label": "off track",
                            "to_label": "productive",
                        })]:
        p = build_prompt(kind, session_context=CTX, **extra)
        assert CTX in p, f"{kind} prompt missing session context"
    nudge = build_prompt("nudge", topic="t", reason="r",
                         observed="Reddit front page on monitor 2",
                         session_context=CTX)
    assert "Reddit front page on monitor 2" in nudge
    # The template must instruct the model to reference what was seen.
    assert "mention" in nudge.lower()


def test_goal_access_prompts_preserve_full_goal_and_group_labels():
    # Goal text and labels are audit-sensitive user context; prompt generation
    # must preserve them verbatim rather than applying display-style shortening.
    full_goal = (
        "Fetch the complete announcement text, verify each named dependency "
        "against its linked release note, and preserve the author's caveat."
    )
    group_labels = "Discord, Telegram, Steam, LinkedIn"

    start = build_prompt(
        "goal_access_start",
        goal=full_goal,
        group_labels=group_labels,
        duration_description="until the current task ends",
        session_context="topic: prepare a release brief",
    )
    end = build_prompt(
        "goal_access_end",
        goal=full_goal,
        group_labels=group_labels,
        end_reason="automatic timer expiry",
        session_context="topic: prepare a release brief",
    )

    assert full_goal in start and full_goal in end
    assert group_labels in start and group_labels in end
    assert "until the current task ends" in start
    assert "automatic timer expiry" in end


def test_goal_access_prompts_describe_exception_without_overstating_enforcement():
    """Transition speech must stay truthful when another policy overlaps."""
    start = build_prompt(
        "goal_access_start",
        goal="check the source announcement",
        group_labels="Discord and Telegram",
        duration_description="for 10 minutes",
        session_context="topic: write a sourced brief",
    )
    end = build_prompt(
        "goal_access_end",
        goal="check the source announcement",
        group_labels="Discord and Telegram",
        end_reason="the user marked the goal complete",
        session_context="topic: write a sourced brief",
    )

    assert "temporary goal-scoped exception" in start.lower()
    assert "does not imply" in start.lower()
    assert "now available" not in start.lower()
    assert "temporary goal-scoped exception" in end.lower()
    assert "does not claim" in end.lower()
    assert "being re-blocked" not in end.lower()
    # Discord can permit both surfaces and Telegram is app-only, so transition
    # speech context must not describe the unified selection as websites alone.
    combined = f"{start}\n{end}".lower()
    assert "website/app access" in combined
    assert "selected access groups" in combined
    assert "website groups" not in combined
    assert "website access" not in combined


def test_generator_calls_llm_and_persists_exchange(tmp_path):
    client = FakeClient()
    gen = MessageGenerator(
        client=client,
        model="test-model",
        store=ResultsStore(tmp_path),
    )
    text = gen.generate("good_luck", topic="write thesis")
    assert text == "You've got this!"
    assert client.responses.last_kwargs["model"] == "test-model"
    assert client.responses.last_kwargs["reasoning"] == {"effort": "medium"}
    # Full exchange saved to results/llm/ (spec: outputs logged uncut).
    assert list((tmp_path / "llm").glob("*_message.json"))


def test_speech_queue_speaks_in_order_and_survives_errors():
    spoken = []
    def speak(text):
        if text == "boom":
            raise RuntimeError("engine hiccup")    # must not kill the worker
        spoken.append(text)
    q = SpeechQueue(speak)
    q.say("one"); q.say("boom"); q.say("two")
    # queue.join() blocks until every enqueued item is processed:
    # https://docs.python.org/3/library/queue.html#queue.Queue.join
    q.wait_idle(timeout=5)
    q.stop()
    assert spoken == ["one", "two"]                # order kept, error skipped


def test_goal_access_feedback_queue_returns_before_slow_model_work():
    """The production adapter cannot hold up wall-clock policy transitions."""

    started, release = threading.Event(), threading.Event()

    generated = []

    class BlockingMessages:
        def generate(self, kind, **ctx):
            generated.append((kind, ctx))
            started.set()
            assert release.wait(timeout=2)
            return f"<{kind}>"

    class Speech:
        def __init__(self):
            self.spoken = []

        def say(self, text):
            self.spoken.append(text)

    now = datetime(2026, 7, 20, 9, 0, 0)
    state = SessionState()
    state.start_session("research", now=now)
    access, reason = state.start_goal_access(
        "Fetch one source",
        ("discord", "telegram"),
        5,
        now=now,
    )
    assert access is not None and reason == ""
    queue_goal_access_feedback(
        state,
        "goal_access_start",
        access,
        now=now,
    )
    state.mark_goal_access_feedback_policy_applied()
    state.release_goal_access_feedback()
    speech = Speech()
    delivery = GoalAccessFeedbackQueue(state, BlockingMessages(), speech)

    before = time.monotonic()
    delivery.wake()
    elapsed = time.monotonic() - before

    assert elapsed < 0.1
    assert started.wait(timeout=1)
    assert speech.spoken == []
    assert generated[0][0] == "goal_access_start"
    assert generated[0][1]["group_labels"] == ["Discord", "Telegram"]
    assert "site_labels" not in generated[0][1]
    release.set()
    assert delivery.wait_idle(timeout=2) is True
    delivery.stop()
    delivery.thread.join(timeout=1)
    assert speech.spoken == ["<goal_access_start>"]
    assert not delivery.thread.is_alive()


def test_policy_independent_correction_feedback_waits_only_for_event_release():
    """A correction acknowledgment needs durable JSONL, not hosts approval."""

    class Messages:
        def __init__(self):
            self.calls = []

        def generate(self, kind, **context):
            self.calls.append((kind, context))
            return f"<{kind}>"

    class Speech:
        def __init__(self):
            self.spoken = []

        def say(self, text):
            self.spoken.append(text)

    state = SessionState()
    state.start_session("research")
    messages, speech = Messages(), Speech()
    delivery = GoalAccessFeedbackQueue(state, messages, speech)
    queue_transition_feedback(
        state,
        "verdict_correction",
        waits_for_policy=False,
        correction_action="corrected the monitor",
        from_label="off track",
        to_label="productive",
        session_context="topic: research",
    )

    # Event durability is the only gate: no policy-applied call is needed.
    assert state.release_goal_access_feedback() is True
    delivery.wake()
    assert delivery.wait_idle(timeout=2) is True
    delivery.stop()
    delivery.thread.join(timeout=1)

    assert [call[0] for call in messages.calls] == ["verdict_correction"]
    assert speech.spoken == ["<verdict_correction>"]


def test_fix_streamed_wav_header_patches_placeholder_sizes(tmp_path):
    # OpenAI's STREAMED wav responses carry 0xFFFFFFFF in the RIFF and data
    # chunk size fields (length unknown at stream start) — winsound silently
    # refuses such files, which made TTS inaudible. Build a minimal RIFF/WAVE
    # with the same placeholder sizes and assert both get patched to reality.
    # RIFF layout: http://soundfile.sapp.org/doc/WaveFormat/
    fmt = struct.pack("<4sIHHIIHH", b"fmt ", 16, 1, 1, 24000, 48000, 2, 16)
    pcm = b"\x00\x00" * 100                        # 100 silent samples
    body = b"WAVE" + fmt + b"data" + struct.pack("<I", 0xFFFFFFFF) + pcm
    wav = tmp_path / "streamed.wav"
    wav.write_bytes(b"RIFF" + struct.pack("<I", 0xFFFFFFFF) + body)

    fix_streamed_wav_header(wav)

    data = wav.read_bytes()
    assert struct.unpack_from("<I", data, 4)[0] == len(data) - 8
    i = data.find(b"data")
    assert struct.unpack_from("<I", data, i + 4)[0] == len(data) - i - 8


def test_fix_streamed_wav_header_ignores_non_riff(tmp_path):
    # Defensive: a non-WAV file must pass through untouched, not crash.
    f = tmp_path / "not.wav"
    f.write_bytes(b"ID3\x03something-mp3ish")
    fix_streamed_wav_header(f)
    assert f.read_bytes() == b"ID3\x03something-mp3ish"


def test_speech_queue_stop_terminates_worker():
    q = SpeechQueue(lambda t: None)
    q.stop()
    time.sleep(0.05)
    assert not q.thread.is_alive()                 # daemon thread exited
