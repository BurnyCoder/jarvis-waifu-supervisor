# Ordered state-transition feedback delivery. Global context: grant state,
# JSONL events, hosts reconciliation, and optional model/TTS work live in
# different collaborators, so one worker preserves transition order without
# letting slow model calls hold policy locks.

import logging
import queue
import threading
import time

from deepwork.access_policy import access_labels
from deepwork.state import GoalAccessFeedbackRequest

log = logging.getLogger(__name__)


def _duration_description(access) -> str:
    """Turn one immutable grant duration into concise spoken context."""

    if access.end_time is None:
        return "until this focused session ends"
    unit = "minute" if access.requested_minutes == 1 else "minutes"
    return f"{access.requested_minutes} {unit}"


def queue_goal_access_feedback(
    state,
    kind: str,
    access,
    *,
    now,
    reason: str | None = None,
) -> None:
    """Capture one transition acknowledgment before hosts reconciliation."""

    context = {
        "goal": access.goal,
        "group_labels": access_labels(access.allowed_groups),
        "session_context": state.context_summary(now=now),
    }
    if kind == "goal_access_start":
        context["duration_description"] = _duration_description(access)
    else:
        context["end_reason"] = reason
    queue_transition_feedback(
        state,
        kind,
        grant=access,
        waits_for_goal_open=(kind == "goal_access_start"),
        accepts_later_policy=(kind == "goal_access_end"),
        **context,
    )


def queue_transition_feedback(
    state,
    kind: str,
    *,
    grant=None,
    waits_for_policy: bool = True,
    waits_for_goal_open: bool = False,
    accepts_later_policy: bool = False,
    **context,
) -> None:
    """Freeze one model request behind its required durability gates."""

    frozen_context = tuple(
        (key, tuple(value) if isinstance(value, list) else value)
        for key, value in context.items()
    )
    state.queue_goal_access_feedback(GoalAccessFeedbackRequest(
        kind=kind,
        context=frozen_context,
        policy_revision=state.feedback_policy_revision,
        grant=grant,
        waits_for_policy=waits_for_policy,
        waits_for_goal_open=waits_for_goal_open,
        accepts_later_policy=accepts_later_policy,
    ))


def _deliver_request(request, messages, speech) -> None:
    """Generate and enqueue one immutable transition acknowledgment."""

    try:
        kwargs = dict(request.context)
        if "group_labels" in kwargs:
            kwargs["group_labels"] = list(kwargs["group_labels"])
        text = messages.generate(request.kind, **kwargs)
        speech.say(text)
    except Exception:
        # Claim-before-call gives each transition at most one request while
        # keeping state/enforcement committed when the model or audio fails.
        log.exception("%s spoken feedback failed", request.kind.replace("_", "-"))


class InlineGoalAccessFeedback:
    """Deterministic transition adapter used by dependency-injected tests."""

    def __init__(self, state, messages, speech):
        self.state = state
        self.messages = messages
        self.speech = speech

    def wake(self) -> None:
        """Drain ready requests in FIFO order outside the lifecycle lock."""

        with self.state.goal_access_feedback_delivery():
            while True:
                request = self.state.pop_ready_goal_access_feedback()
                if request is None:
                    return
                _deliver_request(request, self.messages, self.speech)

    def wait_idle(self, timeout: float | None = None) -> bool:
        """Inline delivery is already idle when wake returns."""

        return True

    def stop(self) -> None:
        """Match the queued adapter's shutdown interface without extra work."""


class GoalAccessFeedbackQueue(InlineGoalAccessFeedback):
    """Non-blocking FIFO model/TTS worker for production transitions."""

    _STOP = None

    def __init__(self, state, messages, speech):
        super().__init__(state, messages, speech)
        # Queue.get/task_done provides a small wake/sentinel protocol:
        # https://docs.python.org/3/library/queue.html#queue.Queue.task_done
        self._wakeups: queue.Queue = queue.Queue()
        self.thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="transition-feedback",
        )
        self.thread.start()

    def wake(self) -> None:
        """Wake the worker and return before optional network/model work."""

        self._wakeups.put(True)

    def _run(self) -> None:
        """Drain each published batch while preserving global FIFO order."""

        while True:
            signal = self._wakeups.get()
            try:
                if signal is self._STOP:
                    return
                super().wake()
            finally:
                self._wakeups.task_done()

    def wait_idle(self, timeout: float | None = None) -> bool:
        """Wait a bounded time for queued prompt generation to finish."""

        deadline = time.monotonic() + (timeout or 0)
        while self._wakeups.unfinished_tasks:
            if timeout is not None and time.monotonic() > deadline:
                return False
            time.sleep(0.01)
        return True

    def stop(self) -> None:
        """Ask the daemon worker to exit after earlier wakeups finish."""

        self._wakeups.put(self._STOP)
