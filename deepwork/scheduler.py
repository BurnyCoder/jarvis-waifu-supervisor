# Background scheduler — the app's heartbeat. Independent daemon loops:
#  * enforcer (every KILL_INTERVAL_S): kills distraction apps and acts as the
#    break watchdog that auto-restores blocking when a break expires.
#  * monitor (every CAPTURE_INTERVAL_S): capture → stitch → save → rolling
#    progress analysis → exactly one feedback utterance.
#  * agent-watch (optional): checks whether an AI coding agent is still active.
# Plain threads (not asyncio) because every underlying call is blocking C or
# subprocess work; loops wait on threading.Event so stop() is instant:
# https://docs.python.org/3/library/threading.html#threading.Event.wait

import logging
import threading
from datetime import datetime

from deepwork.blocking import app_killer
from deepwork.feedback.goal_access import (
    InlineGoalAccessFeedback,
    queue_goal_access_feedback,
    queue_transition_feedback,
)
from deepwork.monitoring import screen_capture, stitcher, webcam_capture
from deepwork.runtime_status import RuntimeStatus
from deepwork.state import goal_access_event, new_verdict_id

log = logging.getLogger(__name__)


def capture_stitched():
    """Default capture_fn: grab all monitors + webcam, return ONE labeled image."""
    tiles = [(f"Monitor {i + 1}", img)
             for i, img in enumerate(screen_capture.capture_monitors())]
    webcam = webcam_capture.capture_webcam()       # None when unavailable
    if webcam is not None:
        tiles.append(("Webcam", webcam))
    # Caption doubles as the capture's timestamp inside the image itself.
    return stitcher.stitch(tiles, caption=f"{datetime.now():%Y-%m-%d %H:%M:%S}")


class Scheduler:
    def __init__(self, state, blocker, store, analyzer, messages, speech,
                 capture_interval_s: int, kill_interval_s: int,
                 capture_fn=None, kill_fn=None,
                 agent_checker=None, agent_check_interval_s: int = 60,
                 now_fn=None, goal_access_feedback=None):
        # Collaborators injected — real objects in main.py, fakes in tests.
        self.state = state
        self.blocker = blocker
        self.store = store
        self.analyzer = analyzer
        self.messages = messages
        self.speech = speech
        # Production injects the daemon-backed adapter; the inline default
        # keeps isolated unit tests deterministic while sharing the same API.
        self.goal_access_feedback = (
            goal_access_feedback
            or InlineGoalAccessFeedback(state, messages, speech)
        )
        self.capture_interval_s = capture_interval_s
        self.kill_interval_s = kill_interval_s
        self.capture_fn = capture_fn or capture_stitched
        # Both vision loops reach the same physical camera. OpenCV documents
        # VideoCapture as non-thread-safe, so one primitive lock serializes the
        # complete injected capture call without delaying model or storage work:
        # https://docs.opencv.org/master/d0/db6/tutorial_orbbec_astra_openni.html
        self._capture_lock = threading.Lock()
        self.kill_fn = kill_fn or app_killer.kill_targets
        # Agentic mode watcher (None = feature off): polls whether the user's
        # AI coding agent is still busy and flips blocking on transitions.
        self.agent_checker = agent_checker
        self.agent_check_interval_s = agent_check_interval_s
        # One clock powers verdict timestamps and runtime countdowns; tests
        # may inject a fixed/mutable clock without patching module globals.
        self.now_fn = now_fn or datetime.now
        # Rolling windows overlap; each new verdict certifies only the newest
        # interval, never the whole historical context.
        self.verdict_minutes = max(1, capture_interval_s // 60)
        # The frozen state snapshot includes both session and temporary-grant
        # identity, preventing captures from leaking across either boundary.
        self._analysis_context = None
        # Event.set() wakes every wait() immediately → instant shutdown.
        self.stop_event = threading.Event()
        self.threads: list[threading.Thread] = []
        # Optional agent watcher remains present in the public snapshot with
        # enabled=False so the frontend has one stable interface.
        self.runtime_status = RuntimeStatus(
            {
                "monitor": self.capture_interval_s,
                "enforcer": self.kill_interval_s,
                "agent_watch": (
                    self.agent_check_interval_s
                    if self.agent_checker is not None
                    else None
                ),
            },
            now_fn=self.now_fn,
        )

    def _capture_image(self, source: str):
        """Run one source-labelled capture while excluding the other vision loop."""
        # Logging before acquisition exposes contention: a request without a
        # matching start is waiting for the active screen/webcam capture.
        log.info("%s capture requested", source)
        # Lock context managers release automatically when capture raises:
        # https://docs.python.org/3/library/threading.html#using-locks-conditions-and-semaphores-in-the-with-statement
        with self._capture_lock:
            log.info("%s capture started", source)
            image = self.capture_fn()
            log.info("%s capture completed", source)
            return image

    def _append_session_event(self, event: dict, action: str) -> None:
        """Keep policy progress independent of a retryable JSONL failure."""

        try:
            self.store.append_session_event(event)
        except Exception:
            log.exception("%s session-event persistence pending retry", action)

    def _retry_session_events(self, action: str) -> None:
        """Retry retained ResultsStore lines without failing the scheduler tick."""

        retry_events = getattr(self.store, "retry_session_events", None)
        if retry_events is None:
            return
        try:
            retry_events()
        except Exception:
            log.exception("%s session-event retry failed", action)

    def _release_transition_feedback(self, action: str) -> None:
        """Publish speech only after earlier JSONL events are durable."""

        self._retry_session_events(action)
        if not getattr(self.store, "session_events_pending", False):
            self.state.release_goal_access_feedback()

    # ---------- tick bodies (called by loops AND directly by tests) ----------

    def _enforcer_tick(self, now: datetime | None = None) -> dict:
        # Expiry, the process sweep, canonical events, reconciliation, and
        # queued speech form one ordered lifecycle relative to Flask requests.
        # Holding the lifecycle lock through kill_fn prevents a newly granted
        # app from being killed by a target list sampled just before its grant.
        with self.state.goal_access_lifecycle():
            # Sample after lock acquisition so a blocked enforcer never checks
            # expiry against an instant from before a slow earlier transition.
            current = now if now is not None else self.now_fn()
            result = self._finish_enforcer_tick(current)
        # wake() is non-blocking in production. Even an injected slow inline
        # adapter cannot hold the lifecycle lock or delay hosts restoration.
        self.goal_access_feedback.wake()
        return result

    def _finish_enforcer_tick(self, current: datetime) -> dict:
        """Expire and enforce one coherent policy under the lifecycle lock."""

        from deepwork.state import Mode

        # Both watchdog transitions only mark state dirty. Reconciliation owns
        # the single final hosts write and also retries a prior failed write.
        self._retry_session_events("enforcer")
        break_ended = self.state.end_break_if_due(now=current)
        goal_access_ended = self.state.end_goal_access_if_due(now=current)
        if break_ended:
            self._append_session_event(
                {"event": "break_ended"},
                "break-expiry",
            )
            log.info("break expired - enforcement restoration requested")
        if goal_access_ended:
            self.state.cancel_pending_goal_access_start(goal_access_ended)
            event = goal_access_event(
                "goal_access_ended",
                goal_access_ended,
                ended_at=current,
                reason="expired",
            )
            # Enqueue for ordered persistence before any later route can start
            # a replacement grant. Transient disk/hosts failures then delay
            # only event durability/feedback, never expiry reblocking.
            self._append_session_event(event, "goal-access-expiry")
            log.info(
                "goal access expired - goal=%r allowed_groups=%s",
                goal_access_ended.goal,
                list(goal_access_ended.allowed_groups),
            )
            queue_goal_access_feedback(
                self.state,
                "goal_access_end",
                goal_access_ended,
                now=current,
                reason="expired",
            )
        # Snapshot after expiry so an app becomes a target on the exact tick its
        # grant ends. Routes cannot change the permission until this call
        # returns because _enforcer_tick still holds the lifecycle lock.
        active = self.state.mode is not Mode.OFF
        killed = (
            list(self.kill_fn(self.state.effective_kill_processes()) or [])
            if active
            else []
        )
        try:
            # This is a no-op while clean; exceptions leave the dirty flag set
            # so this same periodic path retries without unconditional writes.
            self.state.reconcile_enforcement(self.blocker)
        except Exception as exc:
            log.exception("enforcement reconciliation failed")
            return {
                "status": "enforcement_failed",
                "error": f"{type(exc).__name__}: {exc}",
                "killed_processes": killed,
                "break_ended": break_ended,
                "goal_access_ended": goal_access_ended is not None,
            }

        self.state.mark_goal_access_feedback_policy_applied()
        self._release_transition_feedback("enforcer")
        active = self.state.mode is not Mode.OFF
        return {
            "status": "active" if active else "off",
            "killed_processes": killed,
            "break_ended": break_ended,
            "goal_access_ended": goal_access_ended is not None,
        }

    def _monitor_tick(self) -> dict:
        if not self.state.monitoring_active:       # only ON mode is watched
            return {"status": "paused"}
        context = self.state.monitoring_context()
        if self._analysis_context != context:
            # A session, permanent-access, grant-start, or grant-end transition
            # invalidates earlier visuals before the next capture is judged.
            self.analyzer.reset()
            self._analysis_context = context
        try:
            image = self._capture_image("monitor")
        except Exception as exc:                   # capture must never kill the loop
            log.exception("capture failed")
            return {
                "status": "capture_failed",
                "error": f"{type(exc).__name__}: {exc}",
            }
        # A session, break, grant, or agent transition during capture makes the
        # pixels stale before any persistence or model work occurs.
        if (
            not self.state.monitoring_active
            or self.state.monitoring_context() != context
        ):
            return {"status": "context_changed"}
        path = self.store.save_capture(image)
        verdict = self.analyzer.add_capture(
            path,
            topic=context.topic,
            allowed_groups=context.permanent_groups,
            goal_access_goal=context.goal_access_goal,
            goal_access_groups=context.goal_access_groups,
        )
        if verdict is None:                        # defensive fake/legacy support
            if (
                not self.state.monitoring_active
                or self.state.monitoring_context() != context
            ):
                return {"status": "context_changed"}
            return {"status": "no_verdict"}
        # A UUID links this model result across live state, JSONL, runtime
        # telemetry, and any later user correction without relying on timestamps.
        verdict_at = self.now_fn()
        verdict_id = new_verdict_id()
        # The lifecycle coordinator orders accepted state and its source event
        # against Flask transitions/corrections without holding the data lock
        # during filesystem I/O. The context method still atomically rejects a
        # session or policy transition that completed during model work.
        with self.state.goal_access_lifecycle():
            accepted, outcome = self.state.record_verdict_if_context(
                context,
                verdict.productive,
                minutes=self.verdict_minutes,
                observed=verdict.observed,
                reason=verdict.reason,
                now=verdict_at,
                verdict_id=verdict_id,
            )
            if not accepted:
                return {"status": "context_changed"}
            self.store.append_session_event({
                "event": "verdict",
                "verdict_id": verdict_id,
                "evaluated_at": verdict_at.isoformat(),
                "model_productive": verdict.productive,
                "productive": verdict.productive,
                "credited_minutes": self.verdict_minutes,
                "correction_revision": 0,
                "reason": verdict.reason,
                "observed": verdict.observed,
            })
        if outcome:                                # milestone nudge or praise
            # The message model gets what was SEEN plus the whole session
            # snapshot, so the spoken line can quote concrete specifics.
            text = self.messages.generate(outcome, topic=context.topic,
                                          reason=verdict.reason,
                                          observed=verdict.observed,
                                          session_context=self.state.context_summary())
        else:
            # The vision reason is already LLM-generated, fresh, concrete and
            # speech-ready, so ordinary productive ticks need no second call.
            text = verdict.reason
        # A correction can be accepted while the optional message model runs.
        # Recheck under the same coordinator used by the correction route so a
        # stale original nudge/praise can never be enqueued after that override.
        with self.state.goal_access_lifecycle():
            if self.state.verdict_matches(
                verdict_id,
                verdict.productive,
                correction_revision=0,
            ):
                self.speech.say(text)              # exactly one line per verdict
            else:
                log.info(
                    "original verdict speech suppressed after state change: %s",
                    verdict_id,
                )
        model_status = "productive" if verdict.productive else "unproductive"
        return {
            "status": model_status,
            "model_status": model_status,
            "verdict_id": verdict_id,
            "verdict_ts": verdict_at.isoformat(),
        }

    def _agent_watch_tick(self) -> dict:
        # Agentic engineering mode: while the user's AI agent works on another
        # screen, everything unblocks; the moment it finishes, all sites
        # re-block and TTS calls the user back. Only relevant in ON+agentic.
        from deepwork.state import Mode
        if self.agent_checker is None or self.state.mode is not Mode.ON \
                or not self.state.agentic_mode:
            return {"status": "inactive"}
        try:
            image = self._capture_image("agent-watch")
        except Exception as exc:
            log.exception("agent-watch capture failed")
            return {
                "status": "capture_failed",
                "error": f"{type(exc).__name__}: {exc}",
            }
        path = self.store.save_capture(image)
        verdict = self.agent_checker.check(path)
        with self.state.goal_access_lifecycle():
            result = self._finish_agent_watch_tick(verdict)
        self.goal_access_feedback.wake()
        return result

    def _finish_agent_watch_tick(self, verdict) -> dict:
        """Apply one watcher verdict inside the shared policy lifecycle."""

        # A failed transition write remains dirty; even a later steady verdict
        # reaches reconciliation and retries the exact latest state policy.
        changed = self.state.set_agent_busy(verdict.agent_working)
        if changed:
            self._append_session_event(
                {
                    "event": "agent_watch",
                    "agent_working": verdict.agent_working,
                    "reason": verdict.reason,
                },
                "agent-watch",
            )
            queue_transition_feedback(
                self.state,
                "agent_running" if verdict.agent_working else "agent_done",
                reason=verdict.reason,
                session_context=self.state.context_summary(),
            )
        try:
            self.state.reconcile_enforcement(self.blocker)
        except Exception as exc:
            log.exception("agent-watch enforcement reconciliation failed")
            return {
                "status": "enforcement_failed",
                "error": f"{type(exc).__name__}: {exc}",
                "changed": changed,
            }
        self.state.mark_goal_access_feedback_policy_applied()
        self._release_transition_feedback("agent-watch")
        if not changed:
            return {
                "status": "working" if verdict.agent_working else "idle",
                "changed": False,
            }
        return {
            "status": "working" if verdict.agent_working else "idle",
            "changed": True,
        }

    # ---------- thread plumbing ----------

    def _loop(self, name: str, tick, interval_s: int) -> None:
        # wait(timeout) sleeps but returns True instantly when stop() sets the
        # event — the standard interruptible-periodic-thread pattern:
        # https://docs.python.org/3/library/threading.html#threading.Event.wait
        while not self.stop_event.wait(interval_s):
            self.runtime_status.mark_started(name)
            try:
                result = tick()
            except Exception as exc:               # a bad tick must not end the loop
                log.exception("scheduler tick failed")
                self.runtime_status.mark_failed(name, exc)
            else:
                self.runtime_status.mark_finished(name, result)

    def start(self) -> None:
        self.runtime_status.start()
        self.threads = [
            threading.Thread(target=self._loop, name="enforcer", daemon=True,
                             args=("enforcer", self._enforcer_tick,
                                   self.kill_interval_s)),
            threading.Thread(target=self._loop, name="monitor", daemon=True,
                             args=("monitor", self._monitor_tick,
                                   self.capture_interval_s)),
        ]
        if self.agent_checker is not None:         # agentic watcher (optional)
            self.threads.append(
                threading.Thread(target=self._loop, name="agent-watch", daemon=True,
                                 args=("agent_watch", self._agent_watch_tick,
                                       self.agent_check_interval_s)))
        for t in self.threads:
            t.start()
        log.info("scheduler started (kill every %ss, capture every %ss)",
                 self.kill_interval_s, self.capture_interval_s)

    def stop(self) -> None:
        self.stop_event.set()                      # wake both loops → exit
        for t in self.threads:
            t.join(timeout=5)                      # bounded wait, no hang
        self.runtime_status.stop()
        log.info("scheduler stopped")

    def runtime_snapshot(self, now: datetime | None = None) -> dict:
        """Expose JSON-safe loop health without leaking mutable internals."""

        return self.runtime_status.snapshot(now=now)
