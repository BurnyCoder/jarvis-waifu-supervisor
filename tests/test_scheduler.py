# Tests for deepwork/scheduler.py — the tick methods are called directly so
# tests are deterministic (no sleeping); one test exercises real threads with
# tiny intervals to prove start/stop works.

import json
import threading
import time
from datetime import datetime, timedelta
from uuid import UUID

import pytest
from PIL import Image

from deepwork.monitoring.analyzer import ProductivityVerdict
from deepwork.scheduler import Scheduler
from deepwork.state import Mode, SessionState, goal_access_event
from deepwork.storage import ResultsStore

T0 = datetime(2026, 7, 7, 9, 0, 0)


class FakeBlocker:
    def __init__(self):
        self.applied = []
        self.cleared = 0

    def apply(self, domains):
        self.applied.append(tuple(domains))

    def clear(self):
        self.cleared += 1


class FakeAnalyzer:
    # Returns a verdict every call (rolling evaluation behavior) unless None.
    def __init__(self, verdict):
        self.verdict = verdict
        self.captures = []
        self.resets = 0

    def add_capture(
        self,
        path,
        topic,
        allowed_groups=(),
        goal_access_goal=None,
        goal_access_groups=(),
    ):
        self.captures.append(
            (
                path,
                topic,
                tuple(allowed_groups),
                goal_access_goal,
                tuple(goal_access_groups),
            )
        )
        return self.verdict

    def reset(self):
        self.resets += 1


class FakeAgentChecker:
    # Scriptable sequence of agent_working booleans, one per check() call.
    def __init__(self, sequence):
        self.sequence = list(sequence)
        self.checks = 0

    def check(self, path):
        self.checks += 1
        from deepwork.monitoring.analyzer import AgentActivityVerdict
        return AgentActivityVerdict(agent_working=self.sequence.pop(0),
                                    reason="scripted")


class FakeMessages:
    def __init__(self):
        self.calls = []                            # (kind, kwargs) history

    def generate(self, kind, **ctx):
        self.calls.append((kind, ctx))
        return f"<{kind}>"


class FakeSpeech:
    def __init__(self):
        self.spoken = []

    def say(self, text):
        self.spoken.append(text)


def make_scheduler(tmp_path, verdict=None, state=None, agent_checker=None):
    state = state or SessionState()
    kills = []
    sched = Scheduler(
        state=state,
        blocker=FakeBlocker(),
        store=ResultsStore(tmp_path),
        analyzer=FakeAnalyzer(verdict),
        messages=FakeMessages(),
        speech=FakeSpeech(),
        capture_interval_s=1,
        kill_interval_s=1,
        # capture_fn returns an already-stitched PIL image (hardware-free)
        capture_fn=lambda: Image.new("RGB", (8, 8), "green"),
        kill_fn=lambda names: kills.append(tuple(names)) or [],
        agent_checker=agent_checker,
        agent_check_interval_s=1,
    )
    return sched, state, kills


def test_enforcer_tick_kills_only_when_not_off(tmp_path):
    sched, state, kills = make_scheduler(tmp_path)
    sched._enforcer_tick(now=T0)                   # OFF → no sweep
    assert kills == []
    state.start_session("t", now=T0)
    sched._enforcer_tick(now=T0)                   # ON → sweep with kill list
    assert len(kills) == 1 and "discord.exe" in kills[0]


def test_enforcer_kill_sweep_uses_scope_aware_access_groups(tmp_path):
    """The scheduler must pass task, goal, and break app policy to the killer."""

    sched, state, kills = make_scheduler(tmp_path)
    state.start_session(
        "coordinate the release",
        now=T0,
        allowed_groups=["telegram"],
    )
    state.start_goal_access(
        "Confirm the announcement in Discord.",
        ["discord"],
        10,
        now=T0,
    )

    sched._enforcer_tick(now=T0)

    assert "telegram.exe" not in kills[-1]
    assert "discord.exe" not in kills[-1]
    assert "steam.exe" in kills[-1]

    state.start_break(
        "check the build queue",
        5,
        "away",
        allowed_groups=["steam"],
        now=T0 + timedelta(minutes=1),
    )
    sched._enforcer_tick(now=T0 + timedelta(minutes=1))

    # Task Telegram stays spared, the goal-only Discord permission suspends,
    # and the break-only Steam permission becomes active.
    assert "telegram.exe" not in kills[-1]
    assert "discord.exe" in kills[-1]
    assert "steam.exe" not in kills[-1]
    assert "steamwebhelper.exe" not in kills[-1]


def test_enforcer_targets_an_app_on_the_tick_its_grant_expires(tmp_path):
    """Expiry must update app policy before the current kill sweep snapshots it."""

    sched, state, kills = make_scheduler(tmp_path)
    state.start_session("check the build", now=T0)
    access, reason = state.start_goal_access(
        "Inspect the Steam build.",
        ["steam"],
        1,
        now=T0,
    )
    assert access is not None and reason == ""

    result = sched._enforcer_tick(now=T0 + timedelta(minutes=1))

    assert result["goal_access_ended"] is True
    assert "steam.exe" in kills[-1]
    assert "steamwebhelper.exe" in kills[-1]


def test_enforcer_serializes_kill_snapshot_against_a_new_app_grant(tmp_path):
    """A route-style grant cannot become active during a stale kill sweep."""

    sched, state, kills = make_scheduler(tmp_path)
    state.start_session("coordinate the release", now=T0)
    kill_started = threading.Event()
    release_kill = threading.Event()
    grant_finished = threading.Event()
    grant_result = {}

    def blocking_kill(targets):
        kills.append(tuple(targets))
        kill_started.set()
        assert release_kill.wait(timeout=2)
        return []

    def grant_from_route_boundary():
        with state.goal_access_lifecycle():
            grant_result["value"] = state.start_goal_access(
                "Ask the team in Discord.",
                ["discord"],
                10,
                now=T0,
            )
        grant_finished.set()

    sched.kill_fn = blocking_kill
    enforcer = threading.Thread(target=lambda: sched._enforcer_tick(now=T0))
    grant = threading.Thread(target=grant_from_route_boundary)
    enforcer.start()
    assert kill_started.wait(timeout=1)
    grant.start()

    grant_was_blocked = not grant_finished.wait(timeout=0.05)
    release_kill.set()
    enforcer.join(timeout=2)
    grant.join(timeout=2)

    assert grant_was_blocked
    assert not enforcer.is_alive() and not grant.is_alive()
    assert "discord.exe" in kills[-1]
    access, reason = grant_result["value"]
    assert access is not None and reason == ""
    assert "discord.exe" not in state.effective_kill_processes()


def test_enforcer_tick_restores_after_break_expiry(tmp_path):
    sched, state, _ = make_scheduler(tmp_path)
    state.start_session("t", now=T0)
    state.start_break("stretch", 10, "away", now=T0)
    sched._enforcer_tick(now=T0 + timedelta(minutes=5))
    assert state.mode is Mode.BREAK                # not due yet
    sched._enforcer_tick(now=T0 + timedelta(minutes=10))
    assert state.mode is Mode.ON                   # watchdog restored ON
    # Hosts re-applied with the FULL blocklist (allowances gone).
    assert sched.blocker.applied and "reddit.com" in sched.blocker.applied[-1]


def test_enforcer_expires_goal_during_break_and_applies_hosts_once(tmp_path):
    """Coincident break/grant expiry performs one final hosts-file rewrite."""

    sched, state, _ = make_scheduler(tmp_path)
    events = []
    sched.store.append_session_event = events.append
    state.start_session("research", now=T0)
    state.start_goal_access("fetch quote", ["twitter"], 10, now=T0)
    state.start_break("walk", 10, "away", now=T0)

    result = sched._enforcer_tick(now=T0 + timedelta(minutes=10))

    assert state.mode is Mode.ON
    assert state.goal_access is None
    assert len(sched.blocker.applied) == 1
    assert "x.com" in sched.blocker.applied[0]
    assert result["break_ended"] is True
    assert result["goal_access_ended"] is True
    assert events == [
        {"event": "break_ended"},
        {
                "event": "goal_access_ended",
                "reason": "expired",
                "goal": "fetch quote",
                "allowed_groups": ["twitter"],
                "allowed_group_labels": ["X / Twitter"],
                "allowed_sites": ["twitter"],
                "allowed_site_labels": ["X / Twitter"],
                "allowed_apps": [],
                "started_at": T0.isoformat(),
            "expires_at": (T0 + timedelta(minutes=10)).isoformat(),
            "requested_minutes": 10,
            "until_session_end": False,
            "ended_at": (T0 + timedelta(minutes=10)).isoformat(),
        },
    ]
    assert sched.messages.calls == [
        (
            "goal_access_end",
            {
                "goal": "fetch quote",
                "group_labels": ["X / Twitter"],
                "end_reason": "expired",
                "session_context": state.context_summary(
                    now=T0 + timedelta(minutes=10)
                ),
            },
        )
    ]
    assert sched.speech.spoken == ["<goal_access_end>"]


@pytest.mark.parametrize("failure_point", ["message", "speech"])
def test_goal_expiry_survives_optional_feedback_failure(
    tmp_path,
    failure_point,
):
    """State, event, and enforcement stay committed when message/TTS fails."""

    sched, state, _ = make_scheduler(tmp_path)
    events = []
    sched.store.append_session_event = events.append
    state.start_session("research", now=T0)
    state.start_goal_access("fetch quote", ["twitter"], 1, now=T0)

    def fail_generate(*args, **kwargs):
        raise RuntimeError("model unavailable")

    def fail_say(*args, **kwargs):
        raise RuntimeError("audio unavailable")

    if failure_point == "message":
        sched.messages.generate = fail_generate
    else:
        sched.speech.say = fail_say
    result = sched._enforcer_tick(now=T0 + timedelta(minutes=1))

    assert result["goal_access_ended"] is True
    assert state.goal_access is None
    assert len(sched.blocker.applied) == 1
    assert events[-1]["event"] == "goal_access_ended"
    assert sched.speech.spoken == []


def test_enforcer_samples_wall_clock_after_waiting_for_lifecycle_lock(tmp_path):
    """Lock contention cannot defer an expiry by one complete enforcer cycle."""

    clock = {"now": T0 + timedelta(seconds=30)}
    state = SessionState()
    state.start_session("research", now=T0)
    state.start_goal_access("fetch quote", ["twitter"], 1, now=T0)
    kill_completed = threading.Event()
    sched = Scheduler(
        state=state,
        blocker=FakeBlocker(),
        store=ResultsStore(tmp_path),
        analyzer=FakeAnalyzer(None),
        messages=FakeMessages(),
        speech=FakeSpeech(),
        capture_interval_s=300,
        kill_interval_s=3,
        kill_fn=lambda names: kill_completed.set() or [],
        now_fn=lambda: clock["now"],
    )
    result = {}

    def enforce():
        result.update(sched._enforcer_tick())

    with state.goal_access_lifecycle():
        thread = threading.Thread(target=enforce)
        thread.start()
        # The coherent expiry/kill snapshot now waits behind this same lock.
        assert not kill_completed.wait(timeout=0.05)
        clock["now"] = T0 + timedelta(minutes=1)
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert kill_completed.is_set()
    assert result["goal_access_ended"] is True
    assert state.goal_access is None
    assert "x.com" in sched.blocker.applied[-1]


def test_monitor_tick_skips_when_monitoring_inactive(tmp_path):
    sched, state, _ = make_scheduler(tmp_path)
    sched._monitor_tick()                          # OFF → no capture at all
    assert sched.analyzer.captures == []


def test_capture_verdict_nudge_flows_to_speech(tmp_path):
    verdict = ProductivityVerdict(productive=False, reason="watching videos",
                                  observed="YouTube fullscreen on monitor 1")
    sched, state, _ = make_scheduler(tmp_path, verdict=verdict)
    state.start_session("thesis", now=T0)
    sched._monitor_tick()
    assert sched.analyzer.captures[0][1] == "thesis"   # topic reaches analyzer
    assert sched.speech.spoken == ["<nudge>"]          # unproductive → nudge
    assert state.last_verdict["reason"] == "watching videos"
    # The nudge prompt receives what was SEEN plus the whole session context.
    kind, kwargs = sched.messages.calls[-1]
    assert kind == "nudge"
    assert kwargs["observed"] == "YouTube fullscreen on monitor 1"
    assert "thesis" in kwargs["session_context"]


def test_monitor_links_verdict_identity_across_state_event_and_result(tmp_path):
    """One UUID links the accepted model result to both durable and runtime views."""

    verdict = ProductivityVerdict(
        productive=False,
        reason="watching videos",
        observed="YouTube fullscreen on monitor 1",
    )
    sched, state, _ = make_scheduler(tmp_path, verdict=verdict)
    sched.now_fn = lambda: T0
    state.start_session("thesis", now=T0 - timedelta(minutes=5))

    result = sched._monitor_tick()

    entry = state.last_verdict
    assert entry is not None
    assert str(UUID(entry["verdict_id"])) == entry["verdict_id"]
    event_file = next((tmp_path / "sessions").glob("*.jsonl"))
    event = json.loads(event_file.read_text(encoding="utf-8"))
    assert event["event"] == "verdict"
    assert event["verdict_id"] == entry["verdict_id"] == result["verdict_id"]
    assert event["evaluated_at"] == entry["ts"] == result["verdict_ts"]
    assert event["model_productive"] is False
    assert event["productive"] is False
    assert event["credited_minutes"] == entry["credited_minutes"]
    assert result["model_status"] == "unproductive"


def test_monitor_holds_lifecycle_through_verdict_event_append(tmp_path):
    """A correction/transition cannot overtake its source verdict JSONL event."""

    verdict = ProductivityVerdict(
        productive=True,
        reason="draft advanced",
        observed="new paragraph visible",
    )
    sched, state, _ = make_scheduler(tmp_path, verdict=verdict)
    state.start_session("write", now=T0)
    append_started = threading.Event()
    release_append = threading.Event()
    lifecycle_acquired = threading.Event()
    original_append = sched.store.append_session_event

    def blocking_append(event):
        append_started.set()
        assert release_append.wait(timeout=3)
        original_append(event)

    sched.store.append_session_event = blocking_append
    monitor = threading.Thread(target=sched._monitor_tick)
    monitor.start()
    assert append_started.wait(timeout=3)

    def acquire_lifecycle():
        with state.goal_access_lifecycle():
            lifecycle_acquired.set()

    contender = threading.Thread(target=acquire_lifecycle)
    contender.start()
    assert not lifecycle_acquired.wait(timeout=0.05)
    release_append.set()
    monitor.join(timeout=3)
    contender.join(timeout=3)

    assert not monitor.is_alive()
    assert not contender.is_alive()
    assert lifecycle_acquired.is_set()


@pytest.mark.parametrize(
    ("model_productive", "expected_kind"),
    ((False, "nudge"), (True, "praise")),
)
def test_monitor_suppresses_original_speech_after_in_flight_correction(
    tmp_path,
    model_productive,
    expected_kind,
):
    """A user override during nudge or praise generation cancels stale speech."""

    verdict = ProductivityVerdict(
        productive=model_productive,
        reason="the model supplied its original judgment",
        observed="the captured work state remained available for audit",
    )
    sched, state, _ = make_scheduler(tmp_path, verdict=verdict)
    state.start_session("write", now=T0)
    # A productive result reaches the existing 30-minute boundary so it takes
    # the generated-praise branch; an off-track result naturally takes nudge.
    if model_productive:
        sched.verdict_minutes = 5
        state.productive_streak_min = 25
    generation_started = threading.Event()
    release_generation = threading.Event()

    def blocking_generate(kind, **context):
        sched.messages.calls.append((kind, context))
        generation_started.set()
        assert release_generation.wait(timeout=3)
        return "<nudge>"

    sched.messages.generate = blocking_generate
    result = {}

    def run_monitor():
        result.update(sched._monitor_tick())

    monitor = threading.Thread(target=run_monitor)
    monitor.start()
    assert generation_started.wait(timeout=3)
    assert sched.messages.calls[-1][0] == expected_kind
    target = dict(state.last_verdict)
    with state.goal_access_lifecycle():
        corrected = state.correct_latest_verdict(
            target["verdict_id"],
            expected_revision=0,
            productive=not model_productive,
            now=T0 + timedelta(minutes=1),
        )
    assert corrected is not None and corrected.changed is True
    release_generation.set()
    monitor.join(timeout=3)

    assert not monitor.is_alive()
    assert result["model_status"] == (
        "productive" if model_productive else "unproductive"
    )
    assert state.last_verdict["productive"] is not model_productive
    assert sched.speech.spoken == []


def test_monitor_forwards_task_allowed_groups_to_vision_and_message_context(
    tmp_path,
):
    verdict = ProductivityVerdict(
        productive=True,
        reason="The campaign draft is moving.",
        observed="LinkedIn composer shows a task-aligned draft.",
    )
    sched, state, _ = make_scheduler(tmp_path, verdict=verdict)
    state.start_session(
        "publish campaign",
        now=T0,
        allowed_groups=["linkedin", "twitter"],
    )
    sched._monitor_tick()
    assert sched.analyzer.captures[0][2] == ("twitter", "linkedin")
    assert "linkedin" in state.context_summary(now=T0)


def test_productive_encouragement_is_spoken_once_without_second_llm_call(tmp_path):
    reason = "Nice work—you advanced the test suite with three newly passing tests."
    verdict = ProductivityVerdict(
        productive=True,
        reason=reason,
        observed="IDE shows three newly passing tests",
    )
    sched, state, _ = make_scheduler(tmp_path, verdict=verdict)
    state.start_session("thesis", now=T0)
    sched._monitor_tick()
    # The analyzer-authored encouragement is the one canonical utterance for
    # this verdict, avoiding a duplicate message-model call or double praise.
    assert sched.speech.spoken == [reason]
    assert sched.messages.calls == []
    assert state.last_verdict["reason"] == reason


def test_praise_after_thirty_productive_minutes(tmp_path):
    reason = "Great focus—you are deep in code with the tests green."
    verdict = ProductivityVerdict(
        productive=True,
        reason=reason,
        observed="IDE focused, tests green",
    )
    sched, state, _ = make_scheduler(tmp_path, verdict=verdict)
    state.start_session("thesis", now=T0)
    # Rolling windows overlap, so each verdict advances the streak by only the
    # newest five-minute interval—not the full 25-minute context.
    sched.verdict_minutes = 5
    for _ in range(5):
        sched._monitor_tick()
    assert sched.speech.spoken == [reason] * 5
    sched._monitor_tick()
    assert sched.speech.spoken == [reason] * 5 + ["<praise>"]
    assert [kind for kind, _ in sched.messages.calls] == ["praise"]


def test_progress_window_resets_only_for_a_new_session(tmp_path):
    verdict = ProductivityVerdict(productive=True, reason="progress",
                                  observed="document grew")
    sched, state, _ = make_scheduler(tmp_path, verdict=verdict)
    state.start_session("thesis", now=T0)
    sched._monitor_tick()
    sched._monitor_tick()
    assert sched.analyzer.resets == 1              # one reset for first session

    state.start_session("new topic", now=T0 + timedelta(minutes=1))
    sched._monitor_tick()
    assert sched.analyzer.resets == 2              # changed session → fresh window


def test_progress_window_resets_for_every_goal_access_context_change(tmp_path):
    """Each goal cycle gets an independent rolling vision history."""

    verdict = ProductivityVerdict(
        productive=True,
        reason="progress",
        observed="research draft changed",
    )
    sched, state, _ = make_scheduler(tmp_path, verdict=verdict)
    state.start_session("thesis", now=T0, allowed_groups=["linkedin"])
    sched._monitor_tick()
    assert sched.analyzer.resets == 1

    state.start_goal_access(
        "fetch quote",
        ["twitter"],
        10,
        now=T0 + timedelta(minutes=1),
    )
    sched._monitor_tick()
    assert sched.analyzer.resets == 2
    assert sched.analyzer.captures[-1][2:] == (
        ("linkedin",),
        "fetch quote",
        ("twitter",),
    )

    state.stop_goal_access(now=T0 + timedelta(minutes=2))
    sched._monitor_tick()
    assert sched.analyzer.resets == 3
    assert sched.analyzer.captures[-1][2:] == (("linkedin",), None, ())

    state.start_goal_access(
        "verify response",
        ["reddit"],
        None,
        now=T0 + timedelta(minutes=3),
    )
    sched._monitor_tick()
    assert sched.analyzer.resets == 4
    assert sched.analyzer.captures[-1][2:] == (
        ("linkedin",),
        "verify response",
        ("reddit",),
    )


def test_agent_watch_unblocks_then_reblocks_on_transitions(tmp_path):
    checker = FakeAgentChecker([True, True, False])
    sched, state, _ = make_scheduler(tmp_path, agent_checker=checker)
    state.start_session("agentic coding", now=T0)
    state.set_agentic(True)
    # Tick 1: agent detected busy → transition → everything unblocks + speech.
    sched._agent_watch_tick()
    assert sched.blocker.applied[-1] == ()          # empty blocklist applied
    assert sched.speech.spoken == ["<agent_running>"]
    # Tick 2: still busy → NO new blocker call, NO repeated speech.
    sched._agent_watch_tick()
    assert len(sched.blocker.applied) == 1
    assert sched.speech.spoken == ["<agent_running>"]
    # Tick 3: agent finished → full blocklist restored + agent_done spoken.
    sched._agent_watch_tick()
    assert "reddit.com" in sched.blocker.applied[-1]
    assert sched.speech.spoken == ["<agent_running>", "<agent_done>"]


def test_agent_watch_drops_superseded_unapplied_access_feedback(tmp_path):
    """A failed opening policy must never be announced after reblocking."""

    class FailAgentOpeningPolicy(FakeBlocker):
        def __init__(self):
            super().__init__()
            self.attempts = 0

        def apply(self, domains):
            self.attempts += 1
            if self.attempts == 2:
                raise OSError("hosts file busy")
            super().apply(domains)

    checker = FakeAgentChecker([True, False])
    sched, state, _ = make_scheduler(tmp_path, agent_checker=checker)
    blocker = FailAgentOpeningPolicy()
    sched.blocker = blocker
    state.start_session("agentic coding", now=T0, agentic=True)
    state.reconcile_enforcement(blocker)            # initial blocked policy

    failed_open = sched._agent_watch_tick()

    assert failed_open["status"] == "enforcement_failed"
    assert state.agent_busy is True
    assert sched.speech.spoken == []

    recovered_closed = sched._agent_watch_tick()

    assert recovered_closed["status"] == "idle"
    assert state.agent_busy is False
    assert "reddit.com" in blocker.applied[-1]
    assert sched.speech.spoken == ["<agent_done>"]
    assert [kind for kind, _ in sched.messages.calls] == ["agent_done"]


def test_agent_watch_restores_task_specific_blocklist(tmp_path):
    checker = FakeAgentChecker([True, False])
    sched, state, _ = make_scheduler(tmp_path, agent_checker=checker)
    state.start_session(
        "publish campaign",
        now=T0,
        allowed_groups=["twitter"],
        agentic=True,
    )
    sched._agent_watch_tick()
    assert sched.blocker.applied[-1] == ()
    sched._agent_watch_tick()
    assert "x.com" not in sched.blocker.applied[-1]
    assert "reddit.com" in sched.blocker.applied[-1]


def test_agent_watch_inactive_without_agentic_mode(tmp_path):
    checker = FakeAgentChecker([True])
    sched, state, _ = make_scheduler(tmp_path, agent_checker=checker)
    state.start_session("normal work", now=T0)      # agentic mode NOT enabled
    sched._agent_watch_tick()
    assert checker.checks == 0                      # no capture, no API call


class ObservedLock:
    """Expose lock-attempt timing without weakening the real mutual exclusion."""

    def __init__(self):
        # A normal primitive lock remains the synchronization implementation:
        # https://docs.python.org/3/library/threading.html#lock-objects
        self._lock = threading.Lock()
        self._counter_lock = threading.Lock()
        self.attempts = 0
        self.second_attempted = threading.Event()

    def acquire(self):
        """Signal the second attempt immediately before it blocks on the lock."""
        with self._counter_lock:
            self.attempts += 1
            attempt = self.attempts
        if attempt == 2:
            self.second_attempted.set()
        return self._lock.acquire()

    def release(self):
        """Release the wrapped primitive lock."""
        self._lock.release()

    def locked(self):
        """Expose the wrapped lock state for the exception-release assertion."""
        return self._lock.locked()

    def __enter__(self):
        """Support the context-manager protocol used by Scheduler."""
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Always release the lock when capture returns or raises."""
        self.release()


def test_monitor_and_agent_watch_serialize_shared_capture(tmp_path):
    """The two scheduler consumers must never overlap native capture work."""
    first_capture_started = threading.Event()
    counter_lock = threading.Lock()
    active_captures = 0
    max_active_captures = 0
    capture_calls = 0

    checker = FakeAgentChecker([False])
    verdict = ProductivityVerdict(
        productive=True,
        reason="Focused work is visible.",
        observed="IDE open on monitor 1.",
    )
    sched, state, _ = make_scheduler(
        tmp_path,
        verdict=verdict,
        agent_checker=checker,
    )
    observed_lock = ObservedLock()
    sched._capture_lock = observed_lock
    state.start_session("agentic coding", now=T0, agentic=True)

    def blocking_capture():
        """Hold capture one until the other scheduler path requests the lock."""
        nonlocal active_captures, max_active_captures, capture_calls
        with counter_lock:
            capture_calls += 1
            call_number = capture_calls
            active_captures += 1
            max_active_captures = max(max_active_captures, active_captures)
        try:
            if call_number == 1:
                first_capture_started.set()
                assert observed_lock.second_attempted.wait(timeout=2)
            return Image.new("RGB", (8, 8), "green")
        finally:
            with counter_lock:
                active_captures -= 1

    sched.capture_fn = blocking_capture
    results = {}
    thread_errors = []

    def run_tick(name, tick):
        """Return worker results and exceptions to pytest's main thread."""
        try:
            results[name] = tick()
        except BaseException as exc:                 # retain AssertionError too
            thread_errors.append(exc)

    monitor = threading.Thread(
        target=run_tick,
        args=("monitor", sched._monitor_tick),
    )
    agent_watch = threading.Thread(
        target=run_tick,
        args=("agent_watch", sched._agent_watch_tick),
    )
    monitor.start()
    assert first_capture_started.wait(timeout=1)
    agent_watch.start()
    monitor.join(timeout=3)
    agent_watch.join(timeout=3)

    assert not monitor.is_alive() and not agent_watch.is_alive()
    assert thread_errors == []
    assert results["monitor"]["status"] == "productive"
    assert results["agent_watch"]["status"] == "idle"
    assert capture_calls == 2
    assert max_active_captures == 1


def test_capture_exception_releases_lock_for_next_scheduler_path(tmp_path):
    """A recoverable capture error must not deadlock later capture requests."""
    checker = FakeAgentChecker([False])
    sched, state, _ = make_scheduler(tmp_path, agent_checker=checker)
    state.start_session("agentic coding", now=T0, agentic=True)
    capture_calls = 0

    def fail_once_then_capture():
        """Raise once, then return a valid image to prove lock recovery."""
        nonlocal capture_calls
        capture_calls += 1
        if capture_calls == 1:
            raise RuntimeError("camera unavailable")
        return Image.new("RGB", (8, 8), "green")

    sched.capture_fn = fail_once_then_capture
    failed = sched._monitor_tick()

    assert failed == {
        "status": "capture_failed",
        "error": "RuntimeError: camera unavailable",
    }
    assert not sched._capture_lock.locked()

    recovered = sched._agent_watch_tick()

    assert recovered["status"] == "idle"
    assert capture_calls == 2


def test_threads_start_and_stop_cleanly(tmp_path):
    sched, state, kills = make_scheduler(tmp_path)
    state.start_session("t", now=T0)
    sched.start()
    time.sleep(0.15)                               # let loops tick at least once
    sched.stop()                                   # must return promptly
    assert not any(t.is_alive() for t in sched.threads)


def test_enforcer_retries_dirty_policy_and_publishes_expiry_once(tmp_path):
    """A transient hosts failure delays, but never loses or duplicates, expiry."""

    class FailFirstApply(FakeBlocker):
        def __init__(self):
            super().__init__()
            self.attempts = 0

        def apply(self, domains):
            self.attempts += 1
            if self.attempts == 1:
                raise OSError("hosts file busy")
            super().apply(domains)

    sched, state, _ = make_scheduler(tmp_path)
    sched.blocker = FailFirstApply()
    events = []
    sched.store.append_session_event = events.append
    state.start_session("research", now=T0)
    access, _ = state.start_goal_access(
        "fetch quote",
        ["twitter"],
        1,
        now=T0,
    )
    assert access is not None

    failed = sched._enforcer_tick(now=T0 + timedelta(minutes=1))

    assert failed["status"] == "enforcement_failed"
    assert failed["goal_access_ended"] is True
    assert state.goal_access is None
    assert state.enforcement_dirty
    assert len(events) == 1
    assert events[0]["event"] == "goal_access_ended"
    assert events[0]["reason"] == "expired"
    assert sched.speech.spoken == []

    replacement, reason = state.start_goal_access(
        "new grant after failure",
        ["reddit"],
        10,
        now=T0 + timedelta(minutes=1, microseconds=1),
    )
    assert replacement is not None and reason == ""

    recovered = sched._enforcer_tick(now=T0 + timedelta(minutes=1, seconds=1))

    assert recovered["status"] == "active"
    assert not state.enforcement_dirty
    assert sched.blocker.attempts == 2
    assert len(events) == 1
    assert events[0]["event"] == "goal_access_ended"
    assert events[0]["reason"] == "expired"
    assert sched.speech.spoken == ["<goal_access_end>"]
    expiry_context = sched.messages.calls[-1][1]["session_context"]
    assert "new grant after failure" not in expiry_context

    sched._enforcer_tick(now=T0 + timedelta(minutes=1, seconds=2))
    assert sched.blocker.attempts == 2
    assert len(events) == 1
    assert sched.speech.spoken == ["<goal_access_end>"]


def test_expiry_event_failure_still_reblocks_and_retries_complete_cycle(
    tmp_path,
    monkeypatch,
):
    """A transient JSONL failure cannot leave expired website access open."""

    store = ResultsStore(tmp_path)
    state = SessionState()
    blocker = FakeBlocker()
    messages = FakeMessages()
    speech = FakeSpeech()
    sched = Scheduler(
        state=state,
        blocker=blocker,
        store=store,
        analyzer=FakeAnalyzer(None),
        messages=messages,
        speech=speech,
        capture_interval_s=300,
        kill_interval_s=3,
        kill_fn=lambda targets: [],
    )
    state.start_session("research", now=T0)
    access, reason = state.start_goal_access(
        "fetch quote",
        ["twitter"],
        1,
        now=T0,
    )
    assert access is not None and reason == ""
    store.append_session_event(goal_access_event("goal_access_started", access))
    state.reconcile_enforcement(blocker)
    assert "x.com" not in blocker.applied[-1]

    original_flush = store._flush_session_events_locked
    failures = {"remaining": 2}

    def fail_twice():
        if store._pending_session_lines and failures["remaining"]:
            failures["remaining"] -= 1
            raise OSError("session disk temporarily unavailable")
        return original_flush()

    monkeypatch.setattr(store, "_flush_session_events_locked", fail_twice)

    expired = sched._enforcer_tick(now=T0 + timedelta(minutes=1))

    assert expired["goal_access_ended"] is True
    assert state.goal_access is None
    assert state.enforcement_dirty is False
    assert "x.com" in blocker.applied[-1]
    assert store.session_events_pending is True
    assert speech.spoken == []

    retry = sched._enforcer_tick(now=T0 + timedelta(minutes=1, seconds=3))

    assert retry["goal_access_ended"] is False
    assert store.session_events_pending is False
    event_file = next((tmp_path / "sessions").glob("*.jsonl"))
    events = [
        json.loads(line)
        for line in event_file.read_text(encoding="utf-8").splitlines()
    ]
    assert [event["event"] for event in events] == [
        "goal_access_started",
        "goal_access_ended",
    ]
    assert speech.spoken == ["<goal_access_end>"]


def test_enforcer_does_not_rewrite_hosts_when_policy_is_clean(tmp_path):
    """Periodic retries invoke the backend only while state reports dirty."""

    sched, state, _ = make_scheduler(tmp_path)
    state.start_session("write", now=T0)

    sched._enforcer_tick(now=T0)
    sched._enforcer_tick(now=T0 + timedelta(seconds=1))

    assert len(sched.blocker.applied) == 1
    assert not state.enforcement_dirty


def test_monitor_discards_capture_when_context_changes_during_capture(tmp_path):
    """Pixels captured under an old grant context never reach the analyzer."""

    verdict = ProductivityVerdict(
        productive=True,
        reason="stale progress",
        observed="old screen",
    )
    sched, state, _ = make_scheduler(tmp_path, verdict=verdict)
    events = []
    sched.store.append_session_event = events.append
    state.start_session("write", now=T0)

    def capture_then_transition():
        access, reason = state.start_goal_access(
            "new research",
            ["twitter"],
            10,
            now=T0 + timedelta(minutes=1),
        )
        assert access is not None and reason == ""
        return Image.new("RGB", (8, 8), "green")

    sched.capture_fn = capture_then_transition

    assert sched._monitor_tick() == {"status": "context_changed"}
    assert sched.analyzer.captures == []
    assert state.last_verdict is None
    assert events == []
    assert sched.speech.spoken == []


def test_monitor_atomically_rejects_transition_during_analysis(tmp_path):
    """Model work that finishes after a revision change has no side effects."""

    verdict = ProductivityVerdict(
        productive=False,
        reason="stale distraction",
        observed="old screen",
    )
    sched, state, _ = make_scheduler(tmp_path, verdict=verdict)
    events = []
    sched.store.append_session_event = events.append
    state.start_session("write", now=T0)
    original_add_capture = sched.analyzer.add_capture
    transitioned = False

    def analyze_then_transition(*args, **kwargs):
        nonlocal transitioned
        result = original_add_capture(*args, **kwargs)
        if not transitioned:
            transitioned = True
            access, reason = state.start_goal_access(
                "new research",
                ["twitter"],
                10,
                now=T0 + timedelta(minutes=1),
            )
            assert access is not None and reason == ""
        return result

    sched.analyzer.add_capture = analyze_then_transition

    assert sched._monitor_tick() == {"status": "context_changed"}
    assert state.last_verdict is None
    assert events == []
    assert sched.speech.spoken == []
    assert sched.analyzer.resets == 1

    result = sched._monitor_tick()

    assert result["status"] == "unproductive"
    assert sched.analyzer.resets == 2
    assert len(events) == 1 and events[0]["event"] == "verdict"
    assert sched.speech.spoken == ["<nudge>"]
