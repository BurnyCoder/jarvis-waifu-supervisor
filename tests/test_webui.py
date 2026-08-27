# Tests for deepwork/webui/app.py using Flask's built-in test client —
# https://flask.palletsprojects.com/en/stable/testing/

import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from deepwork.config import CONFIRMATION_PHRASE, SITE_DOMAINS
from deepwork.feedback.goal_access import GoalAccessFeedbackQueue
from deepwork.scheduler import Scheduler
from deepwork.state import GoalAccessInfo, Mode, SessionState
from deepwork.storage import ResultsStore
from deepwork.webui.app import create_app


class FakeBlocker:
    def __init__(self):
        self.applied, self.cleared = [], 0
    def apply(self, domains):
        self.applied.append(tuple(domains))
    def clear(self):
        self.cleared += 1


class FailOnApplyBlocker(FakeBlocker):
    """Fail one selected hosts apply so routes can expose retry semantics."""

    def __init__(self, fail_on_call):
        super().__init__()
        self.apply_calls = 0
        self.fail_on_call = fail_on_call

    def apply(self, domains):
        self.apply_calls += 1
        if self.apply_calls == self.fail_on_call:
            raise RuntimeError("hosts write unavailable")
        super().apply(domains)


class RetryableEventStore(ResultsStore):
    """Raise before selected JSONL flushes while retaining complete lines."""

    def __init__(self, root):
        super().__init__(root)
        self.failures_remaining = 0

    def _flush_session_events_locked(self):
        if self._pending_session_lines and self.failures_remaining:
            self.failures_remaining -= 1
            raise OSError("session disk temporarily unavailable")
        return super()._flush_session_events_locked()


class FakeMessages:
    def __init__(self):
        self.calls = []

    def generate(self, kind, **ctx):
        self.calls.append((kind, ctx))
        return f"<{kind}>"


class FakeSpeech:
    def __init__(self):
        self.spoken = []
    def say(self, text):
        self.spoken.append(text)


class FailingBreakEndMessages(FakeMessages):
    def generate(self, kind, **ctx):
        if kind == "break_end_ack":
            raise RuntimeError("text service unavailable")
        return super().generate(kind, **ctx)


class FailingGoalAccessMessages(FakeMessages):
    """Simulate unavailable optional copy generation for grant transitions."""

    def generate(self, kind, **ctx):
        if kind in {"goal_access_start", "goal_access_end"}:
            raise RuntimeError("text service unavailable")
        return super().generate(kind, **ctx)


class BlockingGoalAccessMessages(FakeMessages):
    """Pause start copy generation so expiry can race optional feedback."""

    def __init__(self):
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def generate(self, kind, **ctx):
        self.calls.append((kind, ctx))
        if kind == "goal_access_start":
            self.started.set()
            assert self.release.wait(timeout=3)
        return f"<{kind}>"


def session_events(client):
    """Read every persisted event in append order for route assertions."""

    root = Path(client.application.config["TEST_RESULTS_ROOT"])
    event_file = next((root / "sessions").glob("*.jsonl"))
    return [
        json.loads(line)
        for line in event_file.read_text(encoding="utf-8").splitlines()
    ]


def make_ui(tmp_path, *, now_fn=None, messages=None, blocker=None, store=None):
    """Build the same dependency-injected Flask UI for fixtures and clock tests."""

    state = SessionState(project_allowlists={"ml-research": ["twitter"]})
    blocker, speech = blocker or FakeBlocker(), FakeSpeech()
    runtime_snapshot = lambda now=None: {
        "running": True,
        "loops": {
            "monitor": {
                "enabled": True,
                "interval_s": 300,
                "phase": "waiting",
                "last_started_at": None,
                "last_finished_at": None,
                "next_due_at": None,
                "next_due_in_s": 120,
                "last_error": None,
                "last_result": None,
            },
        },
    }
    app = create_app(state=state, blocker=blocker,
                     store=store or ResultsStore(tmp_path),
                     messages=messages or FakeMessages(), speech=speech,
                     runtime_snapshot=runtime_snapshot, now_fn=now_fn)
    app.testing = True
    app.config["TEST_RESULTS_ROOT"] = str(tmp_path)
    return app.test_client(), state, blocker, speech


@pytest.fixture
def ui(tmp_path):
    return make_ui(tmp_path)


def test_index_lists_previous_topics(ui):
    client, state, *_ = ui
    state.previous_topics[:] = ["thesis", "emails"]
    html = client.get("/").get_data(as_text=True)
    assert "thesis" in html and "emails" in html   # datalist options present
    assert "AI-generated" in html                  # required TTS disclosure
    assert "ml-research" in html and "X / Twitter" in html


def test_index_uses_actions_first_semantic_dashboard(ui):
    client, *_ = ui
    html = client.get("/").get_data(as_text=True)
    assert 'href="/static/dashboard.css"' in html
    assert 'src="/static/dashboard.js"' in html
    assert html.index('id="controls"') < html.index('id="live-dashboard"')
    assert 'id="connection-status"' in html and 'role="status"' in html
    assert 'id="evaluation-history"' in html
    assert 'id="dashboard-announcement"' in html
    assert 'id="project-detail"' in html
    assert 'aria-live="polite"' in html
    # Placeholders are supplemental; every form field also has a real label.
    assert 'for="session-topic"' in html
    assert 'for="break-purpose"' in html
    assert 'for="disable-phrase"' in html
    assert 'id="stop-break-form"' in html
    assert 'action="/break/stop"' in html
    assert "Stop break and resume work" in html
    assert 'id="goal-access-form"' in html
    assert 'action="/goal-access"' in html
    assert 'id="goal-access-active"' in html
    assert 'action="/goal-access/stop"' in html
    assert "Goal complete — stop access" in html
    break_card = html[
        html.index('aria-labelledby="break-heading"'):
        html.index('aria-labelledby="disable-heading"')
    ]
    assert 'id="stop-break-form"' in break_card
    goal_card = html[
        html.index('aria-labelledby="goal-access-heading"'):
        html.index('aria-labelledby="agentic-heading"')
    ]
    assert all(f'value="{site}"' in goal_card for site in SITE_DOMAINS)
    assert "<fieldset" in html and "Websites and apps needed for this task" in html
    assert all(f'value="{site}"' in html for site in SITE_DOMAINS)
    assert "X / Twitter" in html and "Hacker News" in html


def test_dashboard_assets_implement_safe_non_overlapping_live_updates(ui):
    client, *_ = ui
    css = client.get("/static/dashboard.css")
    js = client.get("/static/dashboard.js")
    assert css.status_code == 200 and js.status_code == 200

    script = js.get_data(as_text=True)
    assert 'fetch("/status"' in script
    assert "setTimeout" in script                 # recursive, non-overlap poll
    assert "visibilitychange" in script           # pause while tab is hidden
    assert 'createElement("details")' in script   # expandable evidence
    assert "allowed_sites" in script              # break allowances stay visible
    assert "work_access" in script                # task allowances stay visible
    assert "goal_access" in script                # temporary access stays visible
    assert "Last session task access" in script   # OFF state is not misleading
    assert "stop-break-form" in script             # stop control follows live state
    assert "goal-access-form" in script             # form/panel follow live grant
    assert "reconciliation_pending" in script       # failed hosts writes stay visible
    assert "Policy update pending" in script
    assert "another access scope may still keep an option available" in script
    assert ".textContent" in script               # safe LLM text rendering
    assert ".innerHTML" not in script              # no HTML injection sink


def test_start_session_blocks_and_speaks_good_luck(ui):
    client, state, blocker, speech = ui
    resp = client.post("/start", data={"topic": "write thesis"})
    assert resp.status_code in (200, 302)
    assert state.mode is Mode.ON and state.topic == "write thesis"
    assert blocker.applied and "reddit.com" in blocker.applied[-1]
    assert speech.spoken == ["<good_luck>"]        # requirement 4 good-luck


def test_start_session_unblocks_selected_task_sites_only(ui):
    client, state, blocker, _ = ui
    response = client.post(
        "/start",
        data={
            "topic": "publish launch update",
            "allowed_groups": ["twitter", "linkedin"],
        },
    )
    assert response.status_code in (200, 302)
    assert state.work_allowed_sites == ("twitter", "linkedin")
    assert "x.com" not in blocker.applied[-1]
    assert "linkedin.com" not in blocker.applied[-1]
    assert "reddit.com" in blocker.applied[-1]
    assert state.social_minutes_remaining() == 120


def test_start_accepts_unified_groups_and_rejects_legacy_permission_fields(ui):
    """The clean form contract uses repeated canonical groups exclusively."""

    client, state, blocker, _ = ui
    response = client.post(
        "/start",
        data={
            "topic": "coordinate the launch",
            "allowed_groups": ["discord", "telegram"],
        },
    )

    assert response.status_code == 302
    assert state.work_allowed_groups == ("discord", "telegram")
    assert "discord.com" not in blocker.applied[-1]
    assert "discord.exe" not in state.effective_kill_processes()
    assert "telegram.exe" not in state.effective_kill_processes()

    client.post("/disable", data={"phrase": CONFIRMATION_PHRASE})
    legacy = client.post(
        "/start",
        data={"topic": "legacy", "allowed_sites": ["reddit"]},
    )
    assert legacy.status_code == 400
    assert state.mode is Mode.OFF


def test_goal_and_break_routes_expand_one_discord_group_to_web_and_app(ui):
    """Every access route applies the same dual-surface Discord semantics."""

    client, state, blocker, _ = ui
    client.post("/start", data={"topic": "prepare a community release"})

    goal = client.post(
        "/goal-access",
        data={
            "goal": "Confirm the announcement with the community team",
            "allowed_groups": ["discord"],
            "duration_mode": "timed",
            "minutes": "10",
        },
    )
    assert goal.status_code == 302
    assert "discord.com" not in blocker.applied[-1]
    assert "discord.exe" not in state.effective_kill_processes()

    client.post("/goal-access/stop")
    started_break = client.post(
        "/break",
        data={
            "purpose": "community pause",
            "minutes": "10",
            "kind": "social_media",
            "allowed_groups": ["discord"],
        },
    )
    assert started_break.status_code == 302
    assert "discord.com" not in blocker.applied[-1]
    assert "discord.exe" not in state.effective_kill_processes()
    break_status = client.get("/status").get_json()["break"]
    assert break_status["allowed_groups"] == ["discord"]
    assert break_status["allowed_sites"] == ["discord"]
    assert break_status["allowed_apps"] == ["discord"]
    event = session_events(client)[-1]
    assert event["allowed_groups"] == ["discord"]
    assert event["allowed_sites"] == ["discord"]
    assert event["allowed_apps"] == ["discord"]


def test_app_only_routes_do_not_rewrite_or_depend_on_hosts(tmp_path):
    """Telegram and Steam permissions must succeed without a hosts write."""

    blocker = FailOnApplyBlocker(fail_on_call=2)
    client, state, _, _ = make_ui(tmp_path, blocker=blocker)
    assert client.post("/start", data={"topic": "coordinate release"}).status_code == 302

    goal = client.post(
        "/goal-access",
        data={
            "goal": "Ask the coordinator in Telegram.",
            "allowed_groups": ["telegram"],
            "duration_mode": "timed",
            "minutes": "10",
        },
    )
    take_break = client.post(
        "/break",
        data={
            "purpose": "check the Steam build",
            "allowed_groups": ["steam"],
            "kind": "away",
            "minutes": "5",
        },
    )

    assert goal.status_code == 302
    assert take_break.status_code == 302
    assert blocker.apply_calls == 1
    assert not state.enforcement_dirty
    assert "telegram.exe" in state.effective_kill_processes()
    assert "steam.exe" not in state.effective_kill_processes()

    assert client.post("/break/stop").status_code == 302
    assert client.post("/goal-access/stop").status_code == 302
    assert blocker.apply_calls == 1


def test_goal_and_break_reject_legacy_split_access_fields_atomically(ui):
    """Every mutating access route enforces the chosen clean wire break."""

    client, state, blocker, speech = ui
    client.post("/start", data={"topic": "research"})
    applied_count = len(blocker.applied)
    spoken_count = len(speech.spoken)
    event_count = len(session_events(client))

    legacy_goal = client.post(
        "/goal-access",
        data={
            "goal": "legacy research",
            "allowed_sites": ["twitter"],
            "duration_mode": "timed",
            "minutes": "5",
        },
    )
    legacy_break = client.post(
        "/break",
        data={
            "purpose": "legacy pause",
            "minutes": "5",
            "kind": "away",
            "allowed_apps": ["discord"],
        },
    )
    unknown_break = client.post(
        "/break",
        data={
            "purpose": "forged pause",
            "minutes": "5",
            "kind": "away",
            "allowed_groups": ["unknown"],
        },
    )

    assert legacy_goal.status_code == 400
    assert legacy_break.status_code == 400
    assert unknown_break.status_code == 400
    assert state.mode is Mode.ON and state.goal_access is None
    assert state.social_minutes_remaining() == 120
    assert len(blocker.applied) == applied_count
    assert len(speech.spoken) == spoken_count
    assert len(session_events(client)) == event_count


def test_start_session_adds_project_preset_to_one_off_sites(ui):
    client, state, blocker, _ = ui
    response = client.post(
        "/start",
        data={
            "topic": "share model results",
            "project": "ml-research",
            "allowed_groups": ["linkedin"],
        },
    )
    assert response.status_code in (200, 302)
    assert state.work_allowed_sites == ("twitter", "linkedin")
    assert "x.com" not in blocker.applied[-1]
    assert "linkedin.com" not in blocker.applied[-1]


def test_start_rejects_forged_site_without_state_or_hosts_side_effects(ui):
    client, state, blocker, speech = ui
    response = client.post(
        "/start",
        data={"topic": "forged", "allowed_groups": ["unknown"]},
    )
    assert response.status_code == 400
    assert state.mode is Mode.OFF and state.topic == ""
    assert blocker.applied == [] and speech.spoken == []


def test_start_event_records_task_access(ui):
    client, *_ = ui
    client.post(
        "/start",
        data={
            "topic": "publish launch update",
            "project": "ml-research",
            "allowed_groups": ["linkedin"],
            "agentic": "on",
        },
    )
    root = client.application.config["TEST_RESULTS_ROOT"]
    event_file = next((Path(root) / "sessions").glob("*.jsonl"))
    event = json.loads(event_file.read_text(encoding="utf-8").splitlines()[-1])
    assert event["selected_groups"] == ["linkedin"]
    assert event["selected_sites"] == ["linkedin"]
    assert event["selected_apps"] == []
    assert event["allowed_groups"] == ["twitter", "linkedin"]
    assert event["allowed_sites"] == ["twitter", "linkedin"]
    assert event["allowed_apps"] == []
    assert event["project"] == "ml-research"
    assert event["agentic"] is True


def test_timed_goal_access_applies_free_access_speaks_and_records(tmp_path):
    clock = {"now": datetime(2026, 7, 20, 9, 0, 0)}
    messages = FakeMessages()
    client, state, blocker, speech = make_ui(
        tmp_path,
        now_fn=lambda: clock["now"],
        messages=messages,
    )
    client.post("/start", data={"topic": "write launch report"})
    allowance_before = state.social_minutes_remaining(now=clock["now"])

    response = client.post(
        "/goal-access",
        data={
            "goal": "Fetch launch reactions for the report",
            "allowed_groups": ["linkedin", "twitter"],
            "duration_mode": "timed",
            "minutes": "15",
        },
    )

    assert response.status_code == 302
    assert state.goal_access.goal == "Fetch launch reactions for the report"
    assert state.goal_access.allowed_groups == ("twitter", "linkedin")
    assert state.goal_access.start_time == clock["now"]
    assert state.goal_access.end_time == clock["now"] + timedelta(minutes=15)
    assert state.social_minutes_remaining(now=clock["now"]) == allowance_before
    assert "x.com" not in blocker.applied[-1]
    assert "linkedin.com" not in blocker.applied[-1]
    assert "reddit.com" in blocker.applied[-1]
    assert speech.spoken[-1] == "<goal_access_start>"
    message_kind, message_context = messages.calls[-1]
    assert message_kind == "goal_access_start"
    assert message_context["goal"] == "Fetch launch reactions for the report"
    assert message_context["group_labels"] == ["X / Twitter", "LinkedIn"]
    assert message_context["duration_description"] == "15 minutes"
    assert "session_context" in message_context
    event = session_events(client)[-1]
    assert event == {
        "ts": event["ts"],
        "event": "goal_access_started",
        "goal": "Fetch launch reactions for the report",
        "allowed_groups": ["twitter", "linkedin"],
        "allowed_group_labels": ["X / Twitter", "LinkedIn"],
        "allowed_sites": ["twitter", "linkedin"],
        "allowed_site_labels": ["X / Twitter", "LinkedIn"],
        "allowed_apps": [],
        "started_at": "2026-07-20T09:00:00",
        "expires_at": "2026-07-20T09:15:00",
        "requested_minutes": 15,
        "until_session_end": False,
    }


def test_goal_access_start_uses_the_exact_atomic_return_record(
    tmp_path,
    monkeypatch,
):
    """A replacement cannot misrecord or announce the superseded grant."""

    clock = {"now": datetime(2026, 7, 20, 9, 0, 0)}
    messages = FakeMessages()
    client, state, blocker, _ = make_ui(
        tmp_path,
        now_fn=lambda: clock["now"],
        messages=messages,
    )
    client.post("/start", data={"topic": "research"})
    atomic_start = state.start_goal_access

    def start_then_replace(goal, allowed_groups, minutes, now=None):
        started, reason = atomic_start(goal, allowed_groups, minutes, now=now)
        assert isinstance(started, GoalAccessInfo) and reason == ""
        state.stop_goal_access(now=now + timedelta(seconds=1))
        replacement, replacement_reason = atomic_start(
            "Replacement grant",
            ("linkedin",),
            None,
            now=now + timedelta(seconds=2),
        )
        assert isinstance(replacement, GoalAccessInfo)
        assert replacement_reason == ""
        return started, reason

    monkeypatch.setattr(state, "start_goal_access", start_then_replace)

    response = client.post(
        "/goal-access",
        data={
            "goal": "Original route grant",
            "allowed_groups": ["twitter"],
            "duration_mode": "timed",
            "minutes": "5",
        },
    )

    assert response.status_code == 302
    assert state.goal_access.goal == "Replacement grant"
    assert session_events(client)[-1]["goal"] == "Original route grant"
    assert [
        kind for kind, _ in messages.calls if kind.startswith("goal_access_")
    ] == []
    assert "x.com" in blocker.applied[-1]
    assert "linkedin.com" not in blocker.applied[-1]


def test_concurrent_start_and_stop_keep_lifecycle_events_and_speech_ordered(
    tmp_path,
    monkeypatch,
):
    """Threaded Flask requests cannot publish an end before its start."""

    client, state, _, speech = make_ui(tmp_path)
    app = client.application
    client.post("/start", data={"topic": "research"})
    original_start = state.start_goal_access
    original_stop = state.stop_goal_access
    grant_mutated = threading.Event()
    release_start = threading.Event()
    stop_state_entered = threading.Event()

    def paused_start(*args, **kwargs):
        result = original_start(*args, **kwargs)
        grant_mutated.set()
        assert release_start.wait(timeout=2)
        return result

    def observed_stop(*args, **kwargs):
        stop_state_entered.set()
        return original_stop(*args, **kwargs)

    monkeypatch.setattr(state, "start_goal_access", paused_start)
    monkeypatch.setattr(state, "stop_goal_access", observed_stop)
    responses = {}

    def post_start():
        with app.test_client() as threaded_client:
            responses["start"] = threaded_client.post(
                "/goal-access",
                data={
                    "goal": "fetch source",
                    "allowed_groups": ["twitter"],
                    "duration_mode": "timed",
                    "minutes": "5",
                },
            ).status_code

    def post_stop():
        with app.test_client() as threaded_client:
            responses["stop"] = threaded_client.post(
                "/goal-access/stop"
            ).status_code

    start_thread = threading.Thread(target=post_start)
    stop_thread = threading.Thread(target=post_stop)
    start_thread.start()
    assert grant_mutated.wait(timeout=2)
    stop_thread.start()
    assert not stop_state_entered.wait(timeout=0.2)
    release_start.set()
    start_thread.join(timeout=2)
    stop_thread.join(timeout=2)

    assert not start_thread.is_alive() and not stop_thread.is_alive()
    assert stop_state_entered.is_set()
    assert responses == {"start": 302, "stop": 302}
    assert [event["event"] for event in session_events(client)][-2:] == [
        "goal_access_started",
        "goal_access_ended",
    ]
    assert speech.spoken[-2:] == ["<goal_access_start>", "<goal_access_end>"]
    assert state.goal_access is None


def test_concurrent_goal_start_and_break_keep_suspension_ordered(
    tmp_path,
    monkeypatch,
):
    """A break cannot publish before the grant start it will suspend."""

    client, state, _, speech = make_ui(tmp_path)
    app = client.application
    client.post("/start", data={"topic": "research"})
    original_goal_start = state.start_goal_access
    original_break_start = state.start_break
    grant_mutated = threading.Event()
    release_goal_start = threading.Event()
    break_state_entered = threading.Event()

    def paused_goal_start(*args, **kwargs):
        result = original_goal_start(*args, **kwargs)
        grant_mutated.set()
        assert release_goal_start.wait(timeout=2)
        return result

    def observed_break_start(*args, **kwargs):
        break_state_entered.set()
        return original_break_start(*args, **kwargs)

    monkeypatch.setattr(state, "start_goal_access", paused_goal_start)
    monkeypatch.setattr(state, "start_break", observed_break_start)

    def post_goal_start():
        with app.test_client() as threaded_client:
            assert threaded_client.post(
                "/goal-access",
                data={
                    "goal": "fetch source",
                    "allowed_groups": ["twitter"],
                    "duration_mode": "timed",
                    "minutes": "5",
                },
            ).status_code == 302

    def post_break():
        with app.test_client() as threaded_client:
            assert threaded_client.post(
                "/break",
                data={
                    "purpose": "stretch",
                    "minutes": "1",
                    "kind": "away",
                    "allowed_groups": [],
                },
            ).status_code == 302

    goal_thread = threading.Thread(target=post_goal_start)
    break_thread = threading.Thread(target=post_break)
    goal_thread.start()
    assert grant_mutated.wait(timeout=2)
    break_thread.start()
    assert not break_state_entered.wait(timeout=0.2)
    release_goal_start.set()
    goal_thread.join(timeout=2)
    break_thread.join(timeout=2)

    assert not goal_thread.is_alive() and not break_thread.is_alive()
    assert break_state_entered.is_set()
    assert [event["event"] for event in session_events(client)][-2:] == [
        "goal_access_started",
        "break_start",
    ]
    assert speech.spoken[-2:] == ["<goal_access_start>", "<break_ack>"]
    snapshot = state.status_snapshot()
    assert snapshot["mode"] == "break"
    assert snapshot["goal_access"]["suspended"] is True


def test_production_worker_preserves_goal_start_before_break_ack(tmp_path):
    """Async model generation cannot reorder adjacent lifecycle speech."""

    state = SessionState()
    blocker = FakeBlocker()
    store = ResultsStore(tmp_path)
    messages = BlockingGoalAccessMessages()
    speech = FakeSpeech()
    delivery = GoalAccessFeedbackQueue(state, messages, speech)
    app = create_app(
        state=state,
        blocker=blocker,
        store=store,
        messages=messages,
        speech=speech,
        goal_access_feedback=delivery,
    )
    app.testing = True
    client = app.test_client()
    try:
        client.post("/start", data={"topic": "research"})
        assert delivery.wait_idle(timeout=2)

        started = client.post(
            "/goal-access",
            data={
                "goal": "Fetch one source",
                "allowed_groups": ["twitter"],
                "duration_mode": "timed",
                "minutes": "5",
            },
        )
        assert started.status_code == 302
        assert messages.started.wait(timeout=2)

        break_response = client.post(
            "/break",
            data={
                "purpose": "stretch",
                "minutes": "1",
                "kind": "away",
            },
        )
        assert break_response.status_code == 302
        assert state.mode is Mode.BREAK
        assert speech.spoken == ["<good_luck>"]

        messages.release.set()
        assert delivery.wait_idle(timeout=2)
        assert speech.spoken[-2:] == [
            "<goal_access_start>",
            "<break_ack>",
        ]
    finally:
        messages.release.set()
        delivery.stop()
        delivery.thread.join(timeout=2)


def test_goal_access_start_hosts_failure_keeps_active_record_retryable(tmp_path):
    """A failed opening write retains the exact active grant and its event."""

    blocker = FailOnApplyBlocker(fail_on_call=2)
    client, state, blocker, speech = make_ui(tmp_path, blocker=blocker)
    client.post("/start", data={"topic": "research"})

    response = client.post(
        "/goal-access",
        data={
            "goal": "Fetch one source",
            "allowed_groups": ["twitter"],
            "duration_mode": "timed",
            "minutes": "5",
        },
    )

    assert response.status_code == 503
    assert "pending retry" in response.get_data(as_text=True).lower()
    access = state.goal_access
    assert isinstance(access, GoalAccessInfo)
    assert access.goal == "Fetch one source"
    assert state.enforcement_dirty is True
    event = session_events(client)[-1]
    assert event["event"] == "goal_access_started"
    assert event["goal"] == access.goal
    assert event["started_at"] == access.start_time.isoformat()
    assert speech.spoken == ["<good_luck>"]
    status = client.get("/status").get_json()
    assert status["goal_access"]["goal"] == access.goal
    assert status["enforcement"]["reconciliation_pending"] is True

    goal_event_count = len([
        event for event in session_events(client)
        if event["event"].startswith("goal_access_")
    ])
    assert client.post("/agentic", data={}).status_code == 302
    assert state.enforcement_dirty is False
    assert len([
        event for event in session_events(client)
        if event["event"].startswith("goal_access_")
    ]) == goal_event_count
    assert "x.com" not in blocker.applied[-1]
    assert speech.spoken == ["<good_luck>", "<goal_access_start>"]


def test_goal_start_event_failure_does_not_skip_opening_and_retries(tmp_path):
    """JSONL recovery gates speech but never delays successful enforcement."""

    store = RetryableEventStore(tmp_path)
    messages = FakeMessages()
    client, state, blocker, speech = make_ui(
        tmp_path,
        messages=messages,
        store=store,
    )
    client.post("/start", data={"topic": "research"})
    store.failures_remaining = 2

    response = client.post(
        "/goal-access",
        data={
            "goal": "Fetch one source",
            "allowed_groups": ["twitter"],
            "duration_mode": "timed",
            "minutes": "5",
        },
    )

    assert response.status_code == 302
    assert state.goal_access is not None
    assert state.enforcement_dirty is False
    assert "x.com" not in blocker.applied[-1]
    assert store.session_events_pending is True
    assert speech.spoken == ["<good_luck>"]

    scheduler = Scheduler(
        state=state,
        blocker=blocker,
        store=store,
        analyzer=object(),
        messages=messages,
        speech=speech,
        capture_interval_s=300,
        kill_interval_s=3,
        kill_fn=lambda targets: [],
    )
    scheduler._enforcer_tick()

    assert store.session_events_pending is False
    assert session_events(client)[-1]["event"] == "goal_access_started"
    assert speech.spoken[-1] == "<goal_access_start>"


def test_failed_goal_access_start_is_not_spoken_after_timer_expiry(tmp_path):
    """Expiry cancels an opening acknowledgment that was never enforced."""

    clock = {"now": datetime(2026, 7, 20, 9, 0, 0)}
    blocker = FailOnApplyBlocker(fail_on_call=2)
    messages = FakeMessages()
    client, state, blocker, speech = make_ui(
        tmp_path,
        now_fn=lambda: clock["now"],
        messages=messages,
        blocker=blocker,
    )
    scheduler = Scheduler(
        state=state,
        blocker=blocker,
        store=ResultsStore(tmp_path),
        analyzer=object(),
        messages=messages,
        speech=speech,
        capture_interval_s=300,
        kill_interval_s=3,
        kill_fn=lambda targets: [],
        now_fn=lambda: clock["now"],
    )
    client.post("/start", data={"topic": "research"})
    failed = client.post(
        "/goal-access",
        data={
            "goal": "Fetch one source",
            "allowed_groups": ["twitter"],
            "duration_mode": "timed",
            "minutes": "1",
        },
    )
    assert failed.status_code == 503

    clock["now"] += timedelta(minutes=1)
    result = scheduler._enforcer_tick(now=clock["now"])

    assert result["goal_access_ended"] is True
    assert state.goal_access is None
    assert state.enforcement_dirty is False
    assert speech.spoken == ["<good_luck>", "<goal_access_end>"]
    assert [
        kind for kind, _ in messages.calls if kind.startswith("goal_access_")
    ] == ["goal_access_end"]
    grant_events = [
        event for event in session_events(client)
        if event["event"].startswith("goal_access_")
    ]
    assert [event["event"] for event in grant_events] == [
        "goal_access_started",
        "goal_access_ended",
    ]
    assert grant_events[-1]["reason"] == "expired"


def test_failed_goal_access_start_is_not_spoken_after_session_replacement(
    tmp_path,
):
    """A replacement session cancels an unapplied old-grant acknowledgment."""

    blocker = FailOnApplyBlocker(fail_on_call=2)
    messages = FakeMessages()
    client, state, blocker, speech = make_ui(
        tmp_path,
        messages=messages,
        blocker=blocker,
    )
    client.post("/start", data={"topic": "old task"})
    failed = client.post(
        "/goal-access",
        data={
            "goal": "Fetch one source",
            "allowed_groups": ["twitter"],
            "duration_mode": "timed",
            "minutes": "5",
        },
    )
    assert failed.status_code == 503

    replacement = client.post("/start", data={"topic": "replacement task"})

    assert replacement.status_code == 302
    assert state.topic == "replacement task"
    assert state.goal_access is None
    assert state.enforcement_dirty is False
    assert speech.spoken == ["<good_luck>", "<good_luck>"]
    assert [
        kind for kind, _ in messages.calls if kind.startswith("goal_access_")
    ] == []
    grant_events = [
        event for event in session_events(client)
        if event["event"].startswith("goal_access_")
    ]
    assert [event["event"] for event in grant_events] == [
        "goal_access_started",
        "goal_access_ended",
    ]
    assert grant_events[-1]["reason"] == "session_replaced"


def test_failed_goal_access_start_waits_through_break_suspension(tmp_path):
    """A successful BREAK write is not mistaken for opening the grant."""

    blocker = FailOnApplyBlocker(fail_on_call=2)
    messages = FakeMessages()
    client, state, blocker, speech = make_ui(
        tmp_path,
        messages=messages,
        blocker=blocker,
    )
    client.post("/start", data={"topic": "research"})
    failed = client.post(
        "/goal-access",
        data={
            "goal": "Fetch one source",
            "allowed_groups": ["twitter"],
            "duration_mode": "timed",
            "minutes": "5",
        },
    )
    assert failed.status_code == 503

    started_break = client.post(
        "/break",
        data={
            "purpose": "stretch",
            "minutes": "1",
            "kind": "away",
        },
    )

    assert started_break.status_code == 302
    assert state.mode is Mode.BREAK
    assert speech.spoken == ["<good_luck>", "<break_ack>"]
    assert [
        kind for kind, _ in messages.calls if kind.startswith("goal_access_")
    ] == []

    resumed = client.post("/break/stop")

    assert resumed.status_code == 302
    assert state.mode is Mode.ON
    assert state.enforcement_dirty is False
    assert speech.spoken[-2:] == [
        "<goal_access_start>",
        "<break_end_ack>",
    ]


def test_slow_goal_feedback_cannot_delay_expiry_or_reblocking(tmp_path):
    """Optional model work runs outside the wall-clock policy lifecycle."""

    clock = {"now": datetime(2026, 7, 20, 9, 0, 0)}
    messages = BlockingGoalAccessMessages()
    client, state, blocker, speech = make_ui(
        tmp_path,
        now_fn=lambda: clock["now"],
        messages=messages,
    )
    app = client.application
    client.post("/start", data={"topic": "research"})
    responses = {}

    def start_grant():
        with app.test_client() as threaded_client:
            responses["start"] = threaded_client.post(
                "/goal-access",
                data={
                    "goal": "Fetch one source",
                    "allowed_groups": ["twitter"],
                    "duration_mode": "timed",
                    "minutes": "1",
                },
            ).status_code

    start_thread = threading.Thread(target=start_grant)
    start_thread.start()
    assert messages.started.wait(timeout=2)
    assert state.goal_access is not None
    assert "x.com" not in blocker.applied[-1]

    scheduler = Scheduler(
        state=state,
        blocker=blocker,
        store=ResultsStore(tmp_path),
        analyzer=object(),
        messages=messages,
        speech=speech,
        capture_interval_s=300,
        kill_interval_s=3,
        kill_fn=lambda targets: [],
        now_fn=lambda: clock["now"],
    )
    clock["now"] += timedelta(minutes=1)
    expiry_result = {}

    def expire_grant():
        expiry_result.update(scheduler._enforcer_tick())

    expiry_thread = threading.Thread(target=expire_grant)
    expiry_thread.start()
    deadline = time.monotonic() + 2
    while (
        (state.goal_access is not None or state.enforcement_dirty)
        and time.monotonic() < deadline
    ):
        time.sleep(0.01)

    assert state.goal_access is None
    assert state.enforcement_dirty is False
    assert "x.com" in blocker.applied[-1]
    assert expiry_thread.is_alive()  # waits only for ordered feedback delivery

    messages.release.set()
    start_thread.join(timeout=2)
    expiry_thread.join(timeout=2)
    assert not start_thread.is_alive() and not expiry_thread.is_alive()
    assert responses["start"] == 302
    assert expiry_result["goal_access_ended"] is True
    assert speech.spoken[-2:] == [
        "<goal_access_start>",
        "<goal_access_end>",
    ]


def test_goal_access_stop_hosts_failure_records_and_stays_retryable(tmp_path):
    """A failed re-block defers its one acknowledgment until retry succeeds."""

    blocker = FailOnApplyBlocker(fail_on_call=3)
    client, state, blocker, speech = make_ui(tmp_path, blocker=blocker)
    client.post("/start", data={"topic": "research"})
    client.post(
        "/goal-access",
        data={
            "goal": "Fetch one source",
            "allowed_groups": ["twitter"],
            "duration_mode": "timed",
            "minutes": "5",
        },
    )

    response = client.post("/goal-access/stop")

    assert response.status_code == 503
    assert "pending retry" in response.get_data(as_text=True).lower()
    assert state.goal_access is None
    assert state.enforcement_dirty is True
    event = session_events(client)[-1]
    assert event["event"] == "goal_access_ended"
    assert event["goal"] == "Fetch one source"
    assert event["reason"] == "manual"
    assert speech.spoken == ["<good_luck>", "<goal_access_start>"]
    status = client.get("/status").get_json()
    assert status["goal_access"] is None
    assert status["enforcement"]["reconciliation_pending"] is True

    assert client.post("/agentic", data={}).status_code == 302
    assert state.enforcement_dirty is False
    assert "x.com" in blocker.applied[-1]
    assert speech.spoken == [
        "<good_luck>",
        "<goal_access_start>",
        "<goal_access_end>",
    ]


def test_route_recovery_orders_expiry_event_and_feedback_before_replacement(
    tmp_path,
):
    """A route may recover expiry enforcement without crossing lifecycle order."""

    clock = {"now": datetime(2026, 7, 20, 9, 0, 0)}
    blocker = FailOnApplyBlocker(fail_on_call=3)
    messages = FakeMessages()
    client, state, blocker, speech = make_ui(
        tmp_path,
        now_fn=lambda: clock["now"],
        messages=messages,
        blocker=blocker,
    )
    store = ResultsStore(tmp_path)
    scheduler = Scheduler(
        state=state,
        blocker=blocker,
        store=store,
        analyzer=object(),
        messages=messages,
        speech=speech,
        capture_interval_s=300,
        kill_interval_s=3,
        kill_fn=lambda targets: [],
        now_fn=lambda: clock["now"],
    )
    client.post("/start", data={"topic": "research"})
    client.post(
        "/goal-access",
        data={
            "goal": "old timed goal",
            "allowed_groups": ["twitter"],
            "duration_mode": "timed",
            "minutes": "1",
        },
    )
    clock["now"] += timedelta(minutes=1)

    failed = scheduler._enforcer_tick(now=clock["now"])

    assert failed["status"] == "enforcement_failed"
    assert speech.spoken[-1] == "<goal_access_start>"
    response = client.post(
        "/goal-access",
        data={
            "goal": "replacement goal",
            "allowed_groups": ["reddit"],
            "duration_mode": "session_end",
        },
    )

    assert response.status_code == 302
    grant_events = [
        event for event in session_events(client)
        if event["event"].startswith("goal_access_")
    ]
    assert [(event["event"], event["goal"]) for event in grant_events] == [
        ("goal_access_started", "old timed goal"),
        ("goal_access_ended", "old timed goal"),
        ("goal_access_started", "replacement goal"),
    ]
    assert speech.spoken[-2:] == [
        "<goal_access_end>",
        "<goal_access_start>",
    ]
    assert [
        kind for kind, _ in messages.calls if kind.startswith("goal_access_")
    ][-2:] == ["goal_access_end", "goal_access_start"]
    assert state.goal_access is not None
    assert state.goal_access.goal == "replacement goal"
    assert state.enforcement_dirty is False


def test_goal_access_until_session_end_has_no_expiry(ui):
    client, state, _, speech = ui
    client.post("/start", data={"topic": "research"})

    response = client.post(
        "/goal-access",
        data={
            "goal": "Use the forum as a research source",
            "allowed_groups": ["eaforum"],
            "duration_mode": "session_end",
            # Browsers may still submit the duration control; session-end mode
            # deliberately ignores that unrelated value.
            "minutes": "10",
        },
    )

    assert response.status_code == 302
    assert state.goal_access.end_time is None
    assert state.goal_access.requested_minutes is None
    assert speech.spoken[-1] == "<goal_access_start>"
    event = session_events(client)[-1]
    assert event["expires_at"] is None
    assert event["requested_minutes"] is None
    assert event["until_session_end"] is True


def test_status_and_hosts_show_goal_access_suspended_during_break(tmp_path):
    clock = {"now": datetime(2026, 7, 20, 9, 0, 0)}
    client, state, blocker, _ = make_ui(
        tmp_path,
        now_fn=lambda: clock["now"],
    )
    client.post("/start", data={"topic": "research"})
    client.post(
        "/goal-access",
        data={
            "goal": "Collect reactions",
            "allowed_groups": ["twitter"],
            "duration_mode": "timed",
            "minutes": "10",
        },
    )

    active = client.get("/status").get_json()["goal_access"]
    assert active == {
        "goal": "Collect reactions",
        "allowed_groups": ["twitter"],
        "allowed_group_labels": ["X / Twitter"],
        "allowed_sites": ["twitter"],
        "allowed_site_labels": ["X / Twitter"],
        "allowed_apps": [],
        "started_at": "2026-07-20T09:00:00",
        "expires_at": "2026-07-20T09:10:00",
        "requested_minutes": 10,
        "remaining_s": 600,
        "until_session_end": False,
        "suspended": False,
    }
    assert "x.com" not in blocker.applied[-1]

    clock["now"] += timedelta(minutes=1)
    client.post(
        "/break",
        data={"purpose": "stretch", "minutes": "2", "kind": "away"},
    )

    suspended = client.get("/status").get_json()["goal_access"]
    assert state.goal_access is not None
    assert suspended["suspended"] is True
    assert suspended["remaining_s"] == 540
    assert "x.com" in blocker.applied[-1]

    client.post("/break/stop")
    resumed = client.get("/status").get_json()["goal_access"]
    assert resumed["suspended"] is False
    assert resumed["remaining_s"] == 540
    assert "x.com" not in blocker.applied[-1]


@pytest.mark.parametrize(
    ("data", "expected_error"),
    [
        (
            {
                "goal": "",
                "allowed_groups": ["twitter"],
                "duration_mode": "timed",
                "minutes": "10",
            },
            "goal",
        ),
        (
            {
                "goal": "Research",
                "duration_mode": "timed",
                "minutes": "10",
            },
            "access",
        ),
        (
            {
                "goal": "Research",
                "allowed_groups": ["unknown"],
                "duration_mode": "timed",
                "minutes": "10",
            },
            "unknown",
        ),
        (
            {
                "goal": "Research",
                "allowed_groups": ["twitter"],
                "duration_mode": "forever",
                "minutes": "10",
            },
            "duration",
        ),
        (
            {
                "goal": "Research",
                "allowed_groups": ["twitter"],
                "duration_mode": "timed",
                "minutes": "",
            },
            "minutes",
        ),
        (
            {
                "goal": "Research",
                "allowed_groups": ["twitter"],
                "duration_mode": "timed",
                "minutes": "1.5",
            },
            "minutes",
        ),
        (
            {
                "goal": "Research",
                "allowed_groups": ["twitter"],
                "duration_mode": "timed",
                "minutes": "0",
            },
            "1",
        ),
        (
            {
                "goal": "Research",
                "allowed_groups": ["twitter"],
                "duration_mode": "timed",
                "minutes": "241",
            },
            "240",
        ),
    ],
)
def test_goal_access_rejects_malformed_forms_before_side_effects(
    ui,
    data,
    expected_error,
):
    client, state, blocker, speech = ui
    client.post("/start", data={"topic": "t"})
    applied_count = len(blocker.applied)
    spoken_count = len(speech.spoken)
    event_count = len(session_events(client))

    response = client.post("/goal-access", data=data)

    assert response.status_code == 400
    assert expected_error in response.get_data(as_text=True).lower()
    assert state.goal_access is None
    assert len(blocker.applied) == applied_count
    assert len(speech.spoken) == spoken_count
    assert len(session_events(client)) == event_count


def test_goal_access_requires_an_active_on_session(ui):
    client, state, blocker, speech = ui

    response = client.post(
        "/goal-access",
        data={
            "goal": "Fetch a citation",
            "allowed_groups": ["twitter"],
            "duration_mode": "timed",
            "minutes": "5",
        },
    )

    assert response.status_code == 400
    assert state.goal_access is None
    assert blocker.applied == []
    assert speech.spoken == []


def test_second_goal_access_is_rejected_without_changing_the_first(ui):
    client, state, blocker, speech = ui
    client.post("/start", data={"topic": "t"})
    client.post(
        "/goal-access",
        data={
            "goal": "First source",
            "allowed_groups": ["twitter"],
            "duration_mode": "timed",
            "minutes": "5",
        },
    )
    first = state.goal_access
    applied_count = len(blocker.applied)
    spoken_count = len(speech.spoken)
    event_count = len(session_events(client))

    response = client.post(
        "/goal-access",
        data={
            "goal": "Second source",
            "allowed_groups": ["linkedin"],
            "duration_mode": "timed",
            "minutes": "5",
        },
    )

    assert response.status_code == 400
    assert state.goal_access == first
    assert len(blocker.applied) == applied_count
    assert len(speech.spoken) == spoken_count
    assert len(session_events(client)) == event_count


def test_goal_access_can_repeat_after_manual_stop(tmp_path):
    clock = {"now": datetime(2026, 7, 20, 9, 0, 0)}
    messages = FakeMessages()
    client, state, blocker, speech = make_ui(
        tmp_path,
        now_fn=lambda: clock["now"],
        messages=messages,
    )
    client.post("/start", data={"topic": "research"})
    allowance_before = state.social_minutes_remaining(now=clock["now"])
    client.post(
        "/goal-access",
        data={
            "goal": "Fetch first source",
            "allowed_groups": ["twitter"],
            "duration_mode": "timed",
            "minutes": "10",
        },
    )
    clock["now"] += timedelta(minutes=2)

    stop_response = client.post("/goal-access/stop")

    assert stop_response.status_code == 302
    assert state.goal_access is None
    assert "x.com" in blocker.applied[-1]
    assert speech.spoken[-1] == "<goal_access_end>"
    assert messages.calls[-1][0] == "goal_access_end"
    assert messages.calls[-1][1]["end_reason"] == "manual"
    ended = session_events(client)[-1]
    assert ended["event"] == "goal_access_ended"
    assert ended["reason"] == "manual"
    assert ended["started_at"] == "2026-07-20T09:00:00"
    assert ended["ended_at"] == "2026-07-20T09:02:00"
    assert ended["requested_minutes"] == 10

    repeat_response = client.post(
        "/goal-access",
        data={
            "goal": "Fetch second source",
            "allowed_groups": ["linkedin"],
            "duration_mode": "session_end",
            "minutes": "10",
        },
    )

    assert repeat_response.status_code == 302
    assert state.goal_access.goal == "Fetch second source"
    assert state.goal_access.allowed_groups == ("linkedin",)
    assert state.social_minutes_remaining(now=clock["now"]) == allowance_before
    assert [event["event"] for event in session_events(client)] == [
        "session_start",
        "goal_access_started",
        "goal_access_ended",
        "goal_access_started",
    ]


def test_goal_access_stop_without_active_grant_is_side_effect_free(ui):
    client, state, blocker, speech = ui
    client.post("/start", data={"topic": "t"})
    applied_count = len(blocker.applied)
    spoken_count = len(speech.spoken)
    event_count = len(session_events(client))

    response = client.post("/goal-access/stop")

    assert response.status_code == 302
    assert state.goal_access is None
    assert len(blocker.applied) == applied_count
    assert len(speech.spoken) == spoken_count
    assert len(session_events(client)) == event_count


def test_goal_access_state_changes_survive_feedback_failures(tmp_path):
    clock = {"now": datetime(2026, 7, 20, 9, 0, 0)}
    client, state, blocker, speech = make_ui(
        tmp_path,
        now_fn=lambda: clock["now"],
        messages=FailingGoalAccessMessages(),
    )
    client.post("/start", data={"topic": "t"})

    started = client.post(
        "/goal-access",
        data={
            "goal": "Fetch source",
            "allowed_groups": ["twitter"],
            "duration_mode": "timed",
            "minutes": "5",
        },
    )
    assert started.status_code == 302
    assert state.goal_access is not None
    assert "x.com" not in blocker.applied[-1]
    assert session_events(client)[-1]["event"] == "goal_access_started"

    clock["now"] += timedelta(minutes=1)
    stopped = client.post("/goal-access/stop")

    assert stopped.status_code == 302
    assert state.goal_access is None
    assert "x.com" in blocker.applied[-1]
    assert session_events(client)[-1]["event"] == "goal_access_ended"
    assert speech.spoken == ["<good_luck>"]


def test_replacement_session_records_goal_access_end_without_extra_end_speech(ui):
    client, state, _, speech = ui
    client.post("/start", data={"topic": "first"})
    client.post(
        "/goal-access",
        data={
            "goal": "Fetch source",
            "allowed_groups": ["twitter"],
            "duration_mode": "session_end",
            "minutes": "10",
        },
    )

    response = client.post("/start", data={"topic": "second"})

    assert response.status_code == 302
    assert state.goal_access is None
    assert [event["event"] for event in session_events(client)][-2:] == [
        "goal_access_ended",
        "session_start",
    ]
    assert session_events(client)[-2]["reason"] == "session_replaced"
    assert speech.spoken == [
        "<good_luck>",
        "<goal_access_start>",
        "<good_luck>",
    ]


def test_disable_records_goal_access_end_without_extra_end_speech(ui):
    client, state, _, speech = ui
    client.post("/start", data={"topic": "t"})
    client.post(
        "/goal-access",
        data={
            "goal": "Fetch source",
            "allowed_groups": ["twitter"],
            "duration_mode": "session_end",
            "minutes": "10",
        },
    )

    response = client.post(
        "/disable",
        data={"phrase": CONFIRMATION_PHRASE},
    )

    assert response.status_code == 302
    assert state.goal_access is None
    assert [event["event"] for event in session_events(client)][-2:] == [
        "goal_access_ended",
        "disabled",
    ]
    assert session_events(client)[-2]["reason"] == "disabled"
    assert speech.spoken == ["<good_luck>", "<goal_access_start>"]


def test_disable_needs_exact_phrase(ui):
    client, state, blocker, _ = ui
    client.post("/start", data={"topic": "t"})
    assert client.post("/disable", data={"phrase": "wrong"}).status_code == 403
    assert state.mode is Mode.ON                   # still enforced
    resp = client.post("/disable", data={"phrase": CONFIRMATION_PHRASE})
    assert resp.status_code in (200, 302)
    assert state.mode is Mode.OFF and blocker.cleared == 1


def test_break_rejected_beyond_allowance(ui):
    client, state, *_ = ui
    client.post("/start", data={"topic": "t"})
    resp = client.post("/break", data={"purpose": "scroll", "minutes": "999",
                                       "kind": "social_media",
                                       "allowed_groups": ["reddit"]})
    assert resp.status_code == 400                 # cap enforced server-side
    assert state.mode is Mode.ON


def test_break_applies_allowance_and_speaks_ack(ui):
    client, state, blocker, speech = ui
    client.post("/start", data={"topic": "t"})
    resp = client.post("/break", data={"purpose": "reddit pause", "minutes": "10",
                                       "kind": "social_media",
                                       "allowed_groups": ["reddit"]})
    assert resp.status_code in (200, 302)
    assert state.mode is Mode.BREAK
    assert "reddit.com" not in blocker.applied[-1] # reddit freed during break
    assert "<break_ack>" in speech.spoken          # TTS acknowledges purpose


def test_stop_break_restores_focus_refunds_allowance_and_speaks(tmp_path):
    clock = {"now": datetime(2026, 7, 20, 9, 0, 0)}
    client, state, blocker, speech = make_ui(
        tmp_path,
        now_fn=lambda: clock["now"],
    )
    client.post(
        "/start",
        data={"topic": "publish update", "allowed_groups": ["twitter"]},
    )
    client.post(
        "/break",
        data={
            "purpose": "reddit pause",
            "minutes": "10",
            "kind": "social_media",
            "allowed_groups": ["reddit", "discord"],
        },
    )
    assert state.social_minutes_remaining(now=clock["now"]) == 110
    clock["now"] += timedelta(seconds=61)

    response = client.post("/break/stop")

    assert response.status_code == 302
    assert state.mode is Mode.ON and state.current_break is None
    assert state.social_minutes_remaining(now=clock["now"]) == 118
    assert "x.com" not in blocker.applied[-1]      # task access remains open
    assert "reddit.com" in blocker.applied[-1]    # break access closes immediately
    assert speech.spoken[-1] == "<break_end_ack>"
    status = client.get("/status").get_json()
    assert status["break"] is None
    assert status["monitoring_active"] is True

    event_file = next((Path(tmp_path) / "sessions").glob("*.jsonl"))
    event = json.loads(event_file.read_text(encoding="utf-8").splitlines()[-1])
    assert event["event"] == "break_stopped"
    assert event["purpose"] == "reddit pause"
    assert event["requested_minutes"] == 10
    assert event["charged_minutes"] == 2
    assert event["refunded_minutes"] == 8


def test_stop_break_without_active_break_is_a_side_effect_free_redirect(ui):
    client, state, blocker, speech = ui
    client.post("/start", data={"topic": "t"})
    applied_count = len(blocker.applied)
    spoken_count = len(speech.spoken)

    response = client.post("/break/stop")

    assert response.status_code == 302
    assert state.mode is Mode.ON
    assert len(blocker.applied) == applied_count
    assert len(speech.spoken) == spoken_count


def test_stop_break_succeeds_even_when_feedback_generation_fails(tmp_path):
    clock = {"now": datetime(2026, 7, 20, 9, 0, 0)}
    client, state, blocker, speech = make_ui(
        tmp_path,
        now_fn=lambda: clock["now"],
        messages=FailingBreakEndMessages(),
    )
    client.post("/start", data={"topic": "t"})
    client.post(
        "/break",
        data={"purpose": "walk", "minutes": "10", "kind": "away"},
    )
    clock["now"] += timedelta(minutes=2)

    response = client.post("/break/stop")

    assert response.status_code == 302
    assert state.mode is Mode.ON
    assert "reddit.com" in blocker.applied[-1]
    assert speech.spoken == ["<good_luck>", "<break_ack>"]


def test_status_json_shape(ui):
    client, state, *_ = ui
    client.post("/start", data={"topic": "t"})
    response = client.get("/status")
    data = response.get_json()
    assert data["mode"] == "on" and data["topic"] == "t"
    assert "social_minutes_remaining" in data and "last_verdict" in data
    assert "agentic_mode" in data and "agent_busy" in data
    assert "server_time" in data and "session_elapsed_s" in data
    assert data["monitoring_active"] is True
    assert data["evaluation_history"] == []
    assert data["work_access"] == {
        "project": None,
        "selected_groups": [],
        "allowed_groups": [],
        "allowed_group_labels": [],
        "selected_sites": [],
        "selected_apps": [],
        "allowed_sites": [],
        "allowed_site_labels": [],
        "allowed_apps": [],
    }
    assert data["goal_access"] is None
    assert data["enforcement"]["blocked_domain_count"] > 0
    assert data["runtime"]["loops"]["monitor"]["next_due_in_s"] == 120
    assert response.headers["Cache-Control"] == "no-store"


def test_status_returns_current_session_history_newest_first(ui):
    client, state, *_ = ui
    client.post("/start", data={"topic": "t"})
    first = datetime(2026, 7, 20, 9, 0, 0)
    state.record_verdict(True, 5, reason="first", observed="document v1",
                         now=first)
    state.record_verdict(False, 5, reason="second", observed="video open",
                         now=first + timedelta(minutes=5))

    data = client.get("/status").get_json()
    assert [item["reason"] for item in data["evaluation_history"]] == [
        "second",
        "first",
    ]
    assert data["last_verdict"]["observed"] == "video open"


def test_latest_verdict_correction_is_audited_spoken_and_reversible(tmp_path):
    """One explicit correction updates effective accounting without a new check."""

    clock = {"now": datetime(2026, 7, 20, 9, 5, 0)}
    messages = FakeMessages()
    client, state, blocker, speech = make_ui(
        tmp_path,
        now_fn=lambda: clock["now"],
        messages=messages,
    )
    client.post("/start", data={"topic": "write thesis"})
    state.record_verdict(
        False,
        5,
        reason="The document looked unchanged.",
        observed="A thesis document was open.",
        now=clock["now"],
    )
    original = dict(state.last_verdict)
    applied_policies = len(blocker.applied)

    clock["now"] += timedelta(seconds=10)
    corrected = client.post("/verdict/correct", data={
        "verdict_id": original["verdict_id"],
        "expected_revision": "0",
        "productive": "true",
    })

    assert corrected.status_code == 302
    assert f"verdict_corrected={original['verdict_id']}" in corrected.location
    assert "correction_revision=1" in corrected.location
    latest = state.last_verdict
    assert latest["productive"] is True
    assert latest["model_productive"] is False
    assert latest["correction_revision"] == 1
    assert latest["corrected_at"] == clock["now"].isoformat()
    assert latest["reason"] == original["reason"]
    assert len(state.evaluation_history) == 1
    assert state.productive_streak_min == 5
    assert len(blocker.applied) == applied_policies
    event = session_events(client)[-1]
    assert event["event"] == "verdict_corrected"
    assert event["verdict_id"] == original["verdict_id"]
    assert event["model_productive"] is False
    assert event["from_productive"] is False
    assert event["to_productive"] is True
    assert event["correction_revision"] == 1
    assert event["productive_streak_min"] == 5
    assert event["streak_adjusted"] is True
    assert messages.calls[-1][0] == "verdict_correction"
    assert speech.spoken[-1] == "<verdict_correction>"

    clock["now"] += timedelta(seconds=10)
    restored = client.post("/verdict/correct", data={
        "verdict_id": original["verdict_id"],
        "expected_revision": "1",
        "productive": "false",
    })

    assert restored.status_code == 302
    assert f"verdict_corrected={original['verdict_id']}" in restored.location
    assert "correction_revision=2" in restored.location
    latest = state.last_verdict
    assert latest["productive"] is False
    assert latest["model_productive"] is False
    assert latest["correction_revision"] == 2
    assert latest["corrected_at"] is None
    assert state.productive_streak_min == 0
    assert [event["event"] for event in session_events(client)[-2:]] == [
        "verdict_corrected",
        "verdict_corrected",
    ]
    assert [call[0] for call in messages.calls].count("verdict_correction") == 2
    assert speech.spoken[-1] == "<verdict_correction>"


def test_verdict_correction_validates_staleness_revision_and_duplicates(tmp_path):
    """Explicit desired state is idempotent and stale multi-tab writes conflict."""

    messages = FakeMessages()
    client, state, _, speech = make_ui(tmp_path, messages=messages)
    client.post("/start", data={"topic": "research"})

    assert client.post("/verdict/correct", data={
        "verdict_id": str(uuid4()),
        "expected_revision": "0",
        "productive": "true",
    }).status_code == 409

    state.record_verdict(False, 5, reason="model result")
    verdict_id = state.last_verdict["verdict_id"]
    for malformed in (
        {"expected_revision": "0", "productive": "true"},
        {"verdict_id": "not-a-uuid", "expected_revision": "0", "productive": "true"},
        {"verdict_id": verdict_id, "expected_revision": "x", "productive": "true"},
        {"verdict_id": verdict_id, "expected_revision": "-1", "productive": "true"},
        {"verdict_id": verdict_id, "expected_revision": "0", "productive": "yes"},
    ):
        assert client.post("/verdict/correct", data=malformed).status_code == 400

    first = client.post("/verdict/correct", data={
        "verdict_id": verdict_id,
        "expected_revision": "0",
        "productive": "true",
    })
    duplicate = client.post("/verdict/correct", data={
        "verdict_id": verdict_id,
        "expected_revision": "0",
        "productive": "true",
    })
    assert first.status_code == 302 and duplicate.status_code == 302
    assert duplicate.location.endswith("/")
    assert len([e for e in session_events(client) if e["event"] == "verdict_corrected"]) == 1
    assert [call[0] for call in messages.calls].count("verdict_correction") == 1
    assert speech.spoken.count("<verdict_correction>") == 1

    assert client.post("/verdict/correct", data={
        "verdict_id": verdict_id,
        "expected_revision": "1",
        "productive": "false",
    }).status_code == 302
    # An old tab cannot replay its pre-restore command after the ABA cycle.
    stale_revision = client.post("/verdict/correct", data={
        "verdict_id": verdict_id,
        "expected_revision": "0",
        "productive": "true",
    })
    assert stale_revision.status_code == 409

    assert client.post("/verdict/correct", data={
        "verdict_id": verdict_id,
        "expected_revision": "2",
        "productive": "true",
    }).status_code == 302
    # Returning to the same label does not make a pre-ABA payload a duplicate.
    stale_same_label = client.post("/verdict/correct", data={
        "verdict_id": verdict_id,
        "expected_revision": "0",
        "productive": "true",
    })
    assert stale_same_label.status_code == 409

    state.record_verdict(False, 5, reason="newer result")
    stale_latest = client.post("/verdict/correct", data={
        "verdict_id": verdict_id,
        "expected_revision": "3",
        "productive": "true",
    })
    assert stale_latest.status_code == 409


def test_off_correction_acknowledgement_uses_frozen_session_duration(tmp_path):
    """A later OFF-mode correction must not tell the model work kept running."""

    clock = {"now": datetime(2026, 7, 20, 9, 0, 0)}
    messages = FakeMessages()
    client, state, _, _ = make_ui(
        tmp_path,
        now_fn=lambda: clock["now"],
        messages=messages,
    )
    client.post("/start", data={"topic": "write thesis"})
    state.record_verdict(False, 5, reason="model result", now=clock["now"])
    target = dict(state.last_verdict)
    clock["now"] += timedelta(minutes=10)
    assert client.post("/disable", data={
        "phrase": CONFIRMATION_PHRASE,
    }).status_code == 302
    clock["now"] += timedelta(minutes=50)

    response = client.post("/verdict/correct", data={
        "verdict_id": target["verdict_id"],
        "expected_revision": "0",
        "productive": "true",
    })

    assert response.status_code == 302
    kind, context = messages.calls[-1]
    assert kind == "verdict_correction"
    assert "minutes into session: 10" in context["session_context"]


def test_correction_feedback_waits_for_retryable_event_durability(tmp_path):
    """The live correction survives I/O failure, while speech waits for JSONL."""

    store = RetryableEventStore(tmp_path)
    messages = FakeMessages()
    client, state, blocker, speech = make_ui(
        tmp_path,
        store=store,
        messages=messages,
    )
    client.post("/start", data={"topic": "research"})
    state.record_verdict(False, 5, reason="model result")
    latest = dict(state.last_verdict)
    store.failures_remaining = 1

    response = client.post("/verdict/correct", data={
        "verdict_id": latest["verdict_id"],
        "expected_revision": "0",
        "productive": "true",
    })

    assert response.status_code == 302
    assert state.last_verdict["productive"] is True
    assert store.session_events_pending is True
    assert speech.spoken == ["<good_luck>"]

    scheduler = Scheduler(
        state=state,
        blocker=blocker,
        store=store,
        analyzer=object(),
        messages=messages,
        speech=speech,
        capture_interval_s=300,
        kill_interval_s=3,
        kill_fn=lambda targets: [],
    )
    scheduler._enforcer_tick()

    assert store.session_events_pending is False
    assert session_events(client)[-1]["event"] == "verdict_corrected"
    assert speech.spoken[-1] == "<verdict_correction>"


def test_latest_verdict_remains_correctable_during_break_and_after_disable(tmp_path):
    """Review modes preserve history while a completed break keeps streak reset."""

    client, state, _, _ = make_ui(tmp_path)
    client.post("/start", data={"topic": "research"})
    state.record_verdict(False, 5, reason="model result")
    verdict_id = state.last_verdict["verdict_id"]
    assert client.post("/break", data={
        "purpose": "walk",
        "minutes": "5",
        "kind": "away",
    }).status_code == 302

    during_break = client.post("/verdict/correct", data={
        "verdict_id": verdict_id,
        "expected_revision": "0",
        "productive": "true",
    })
    assert during_break.status_code == 302
    assert state.mode is Mode.BREAK
    assert state.productive_streak_min == 5

    assert client.post("/break/stop").status_code == 302
    assert state.mode is Mode.ON and state.productive_streak_min == 0
    assert client.post("/disable", data={
        "phrase": CONFIRMATION_PHRASE,
    }).status_code == 302

    after_disable = client.post("/verdict/correct", data={
        "verdict_id": verdict_id,
        "expected_revision": "1",
        "productive": "false",
    })
    assert after_disable.status_code == 302
    assert state.mode is Mode.OFF
    assert state.last_verdict["productive"] is False
    assert state.productive_streak_min == 0
    assert session_events(client)[-1]["streak_adjusted"] is False


def test_status_extends_break_with_countdown_and_allowances(ui):
    client, state, *_ = ui
    client.post("/start", data={"topic": "t"})
    client.post("/break", data={
        "purpose": "call",
        "minutes": "10",
        "kind": "social_media",
        "allowed_groups": ["reddit", "discord"],
    })

    br = client.get("/status").get_json()["break"]
    assert 0 < br["remaining_s"] <= 600
    assert br["allowed_groups"] == ["reddit", "discord"]
    assert br["allowed_group_labels"] == ["Reddit", "Discord"]
    assert br["allowed_sites"] == ["reddit", "discord"]
    assert br["allowed_apps"] == ["discord"]


def test_start_with_agentic_checkbox_enables_agentic_mode(ui):
    client, state, *_ = ui
    client.post("/start", data={"topic": "agent run", "agentic": "on"})
    assert state.agentic_mode is True
    # Without the checkbox a later session resets it.
    client.post("/start", data={"topic": "solo work"})
    assert state.agentic_mode is False


def test_agentic_toggle_route_avoids_rewriting_an_identical_blocklist(ui):
    client, state, blocker, _ = ui
    client.post("/start", data={"topic": "t"})
    n = len(blocker.applied)
    resp = client.post("/agentic", data={"enabled": "on"})
    assert resp.status_code in (200, 302)
    assert state.agentic_mode is True
    assert len(blocker.applied) == n               # idle policy is unchanged
