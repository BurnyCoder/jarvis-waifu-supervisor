# Session state machine — the single source of truth for what the app is
# doing right now. Global context: the scheduler threads, the Flask UI and
# the blockers all read/mutate state ONLY through these lock-guarded methods,
# which is the standard way to share state between Python threads:
# https://docs.python.org/3/library/threading.html#lock-objects

# Enum gives named, identity-comparable modes (Mode.ON is Mode.ON):
# https://docs.python.org/3/library/enum.html
import enum
import math
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID, uuid4

# Config owns the domain/app tables; state only computes "effective" views.
from deepwork.config import (
    APP_PROCESSES,
    CONFIRMATION_PHRASE,
    SITE_DOMAINS,
    all_blocked_domains,
    expand_www,
)
from deepwork.access_policy import (
    access_app_keys,
    access_labels,
    access_site_keys,
    normalize_access_keys,
    resolve_work_allowed_groups,
)


class Mode(enum.Enum):
    # The three operating modes from requirement 5.
    ON = "on"        # blocking + killing + monitoring all active
    OFF = "off"      # everything disabled
    BREAK = "break"  # timed exception window, auto-restores to ON


@dataclass
class BreakInfo:
    # One active break: what for, which kind, until when, what it unlocks.
    purpose: str                                  # user's stated reason
    kind: str                                     # "social_media" | "away"
    start_time: datetime                          # local instant reservation began
    end_time: datetime                            # absolute expiry instant
    requested_minutes: int                        # whole minutes reserved up front
    allowed_groups: tuple[str, ...] = ()          # canonical web/app permissions


@dataclass(frozen=True)
class BreakStopResult:
    """Immutable accounting record returned after a user stops a break."""

    purpose: str                                  # reason retained for event/TTS
    kind: str                                     # determines allowance accounting
    requested_minutes: int                        # original reservation
    elapsed_seconds: int                          # elapsed time capped at duration
    charged_minutes: int                          # every started minute counts
    refunded_minutes: int                         # social reservation returned


@dataclass(frozen=True)
class GoalAccessInfo:
    """Immutable description of one active goal-based access grant."""

    # Frozen records cannot be accidentally edited after an event captures
    # them: https://docs.python.org/3/library/dataclasses.html#frozen-instances
    goal: str                                      # concrete reason for access
    start_time: datetime                           # grant identity + start instant
    end_time: datetime | None                      # None means session-end access
    requested_minutes: int | None                  # original timed request or None
    allowed_groups: tuple[str, ...]                # normalized access-policy keys


@dataclass(frozen=True)
class GoalAccessFeedbackRequest:
    """One immutable, exactly-once state-transition acknowledgment."""

    kind: str                                      # MessageGenerator template key
    context: tuple[tuple[str, object], ...]         # frozen keyword arguments
    policy_revision: int                           # desired hosts-policy identity
    # Verdict corrections have no hosts-policy claim, so they bypass policy
    # approval while still waiting for earlier JSONL records to become durable.
    waits_for_policy: bool = True
    grant: GoalAccessInfo | None = None             # goal-start cancellation ID
    waits_for_goal_open: bool = False               # BREAK cannot publish start
    accepts_later_policy: bool = False              # truthful after supersession


@dataclass(frozen=True)
class VerdictCorrectionResult:
    """Immutable outcome returned to the correction HTTP boundary."""

    changed: bool                                  # False makes retry a no-op
    verdict_id: str                                # stable analyzer-result identity
    evaluated_at: datetime                         # original evaluation instant
    model_productive: bool                         # immutable vision classification
    from_productive: bool                          # effective label before request
    to_productive: bool                            # requested effective label
    credited_minutes: int                          # interval represented by verdict
    correction_revision: int                       # post-request optimistic version
    changed_at: datetime | None                    # None for idempotent duplicate
    streak_adjusted: bool                          # False after a later streak reset
    productive_streak_min: int                     # effective current remainder
    restored_model_verdict: bool                   # override now equals model again


@dataclass(frozen=True)
class _LatestVerdictAccounting:
    """Private inputs needed to replay only the current streak's last verdict."""

    verdict_id: str                                # exact latest verdict identity
    streak_before_min: int                         # accumulator before that verdict
    credited_minutes: int                          # configured newest-interval credit


def new_verdict_id() -> str:
    """Return one collision-resistant UUID for state, events, and telemetry."""

    # UUID4 is generated from the platform's cryptographic randomness source:
    # https://docs.python.org/3/library/uuid.html#uuid.uuid4
    return str(uuid4())


def _canonical_verdict_id(verdict_id: str) -> str:
    """Validate and normalize an untrusted UUID string at the state boundary."""

    if not isinstance(verdict_id, str) or not verdict_id:
        raise ValueError("Verdict ID must be a UUID string.")
    try:
        return str(UUID(verdict_id))
    except ValueError as exc:
        raise ValueError("Verdict ID must be a valid UUID.") from exc


def _fold_productive_streak(
    streak_before_min: int,
    productive: bool,
    credited_minutes: int,
) -> tuple[int, str | None]:
    """Apply the canonical nudge/praise accounting to one verdict interval."""

    if not productive:
        return 0, "nudge"
    advanced_streak = streak_before_min + credited_minutes
    if advanced_streak >= 30:
        return 0, "praise"
    return advanced_streak, None


def goal_access_event(
    event_name: str,
    access: GoalAccessInfo,
    *,
    ended_at: datetime | None = None,
    reason: str | None = None,
) -> dict:
    """Build one canonical JSON-safe start/end record for any event producer."""

    # ISO strings preserve full local date/time information while remaining
    # directly JSON serializable:
    # https://docs.python.org/3/library/datetime.html#datetime.datetime.isoformat
    event = {
        "event": event_name,
        "goal": access.goal,
        "allowed_groups": list(access.allowed_groups),
        "allowed_group_labels": list(access_labels(access.allowed_groups)),
        # Derived arrays retain useful wire compatibility while the canonical
        # group list prevents Discord from being represented twice in the UI.
        "allowed_sites": list(access_site_keys(access.allowed_groups)),
        "allowed_site_labels": list(
            access_labels(access_site_keys(access.allowed_groups))
        ),
        "allowed_apps": list(access_app_keys(access.allowed_groups)),
        "started_at": access.start_time.isoformat(),
        "expires_at": access.end_time.isoformat() if access.end_time else None,
        "requested_minutes": access.requested_minutes,
        "until_session_end": access.end_time is None,
    }
    if ended_at is not None:
        event["ended_at"] = ended_at.isoformat()
    if reason is not None:
        event["reason"] = reason
    return event


@dataclass(frozen=True)
class MonitoringContext:
    """One atomic analyzer context used as the rolling-window cache key."""

    session_start: datetime | None                 # current session identity
    revision: int                                  # monotonic transition identity
    topic: str                                     # task the user committed to
    permanent_groups: tuple[str, ...]              # task/project permission union
    goal_access_start_time: datetime | None        # active grant identity
    goal_access_goal: str | None                   # active temporary objective
    goal_access_groups: tuple[str, ...]             # active temporary permission union


@dataclass
class SessionState:
    # Behavior knobs are injected so tests construct states in one line.
    daily_social_cap_min: int = 120
    # project name -> canonical access groups that project may use while ON
    project_allowlists: dict[str, list[str] | tuple[str, ...]] = field(
        default_factory=dict
    )

    # --- runtime fields (not constructor-tuned) ---
    mode: Mode = Mode.OFF
    topic: str = ""
    previous_topics: list[str] = field(default_factory=list)
    active_project: str | None = None
    # One-off website/app groups chosen for the current task. Unlike project
    # presets, these runtime choices deliberately do not survive a restart.
    task_allowed_groups: tuple[str, ...] = ()
    # At most one temporary grant is active; completed grants are written as
    # session events rather than retained in mutable/persisted state.
    goal_access: GoalAccessInfo | None = None
    current_break: BreakInfo | None = None
    # date-iso -> minutes of social break reserved that day; keying by date
    # string makes the midnight rollover automatic and JSON-friendly.
    social_used_by_date: dict[str, int] = field(default_factory=dict)
    productive_streak_min: int = 0                # consecutive productive mins
    last_verdict: dict | None = None              # latest analyzer result
    # Complete in-memory verdict history for the current session. The web UI
    # shows all entries; context_summary() independently slices the newest 5.
    evaluation_history: list[dict] = field(default_factory=list)
    session_start: datetime | None = None         # when ON began (for records)
    session_end: datetime | None = None           # freezes elapsed time after OFF
    # Agentic engineering mode: while an AI coding agent is detected working
    # on another screen, the whole blocklist opens; when it finishes,
    # everything re-blocks (user is "waiting", not slacking).
    agentic_mode: bool = False                    # opted in for this session
    agent_busy: bool = False                      # latest vision verdict

    def __post_init__(self):
        # RLock (reentrant) so a locked method may call another locked method:
        # https://docs.python.org/3/library/threading.html#rlock-objects
        self._lock = threading.RLock()
        # Lifecycle side effects (event -> reconciliation -> queued speech)
        # span multiple collaborators. This separate reentrant coordinator lets
        # Flask, expiry, and shutdown keep those ordered without exposing the
        # state-data lock or holding it during model/TTS work.
        self._goal_access_lifecycle_lock = threading.RLock()
        # Slow optional model/TTS delivery is serialized independently so it
        # can never delay a wall-clock expiry or hosts reconciliation.
        self._goal_access_feedback_delivery_lock = threading.Lock()
        # Dirty state is the retryable contract between mutations and the one
        # serialized hosts-file reconciliation operation. The revision is an
        # ABA-safe analyzer context identity: even restoring identical values
        # after an intervening transition produces a different key.
        self._enforcement_dirty = False
        self._monitoring_revision = 0
        self._shutting_down = False
        self._pending_goal_access_feedback: list[
            GoalAccessFeedbackRequest
        ] = []
        # Acknowledgments move here only after their claimed hosts policy was
        # really applied. They remain separate from the delivery-ready queue
        # until all earlier session JSONL records are durable.
        self._enforced_goal_access_feedback: list[
            GoalAccessFeedbackRequest
        ] = []
        self._ready_goal_access_feedback: list[
            GoalAccessFeedbackRequest
        ] = []
        # This private snapshot is sufficient to replay the latest verdict
        # exactly, but is invalidated once a completed break starts a new streak.
        self._latest_verdict_accounting: _LatestVerdictAccounting | None = None

    @contextmanager
    def goal_access_lifecycle(self):
        """Serialize one complete grant lifecycle flow across collaborators."""

        # RLock is a context manager and permits nested same-thread use:
        # https://docs.python.org/3/library/threading.html#rlock-objects
        with self._goal_access_lifecycle_lock:
            yield

    def queue_goal_access_feedback(
        self,
        request: GoalAccessFeedbackRequest,
    ) -> None:
        """Retain feedback behind its policy and/or event-durability gates."""

        with self._lock:
            if request.waits_for_policy:
                self._pending_goal_access_feedback.append(request)
            else:
                # A correction acknowledgment makes no enforcement claim. Put
                # it after the policy gate immediately, but keep it out of the
                # delivery-ready queue until the route confirms JSONL durability.
                self._enforced_goal_access_feedback.append(request)

    @property
    def feedback_policy_revision(self) -> int:
        """Return the locked policy identity captured by a queued message."""

        with self._lock:
            return self._monitoring_revision

    def mark_goal_access_feedback_policy_applied(self) -> bool:
        """Approve only acknowledgments supported by the applied policy.

        The monotonic revision prevents a later successful reconciliation from
        falsely publishing a superseded transition whose own hosts write
        failed. Goal starts are the deliberate exception: an active grant may
        wait through BREAK until a later ON policy really opens its sites.
        Goal ends remain true after later policy transitions, so they may be
        approved by a newer successful revision.
        """

        with self._lock:
            if not self._pending_goal_access_feedback:
                return False
            enforced, pending = [], []
            applied_revision = self._monitoring_revision
            for request in self._pending_goal_access_feedback:
                if request.waits_for_goal_open:
                    if self.goal_access is not request.grant:
                        # Defensive stale-request cleanup complements each
                        # terminal transition's explicit cancellation call.
                        continue
                    if self.mode is Mode.ON:
                        enforced.append(request)
                    elif self.mode is Mode.BREAK:
                        # BREAK applies a suspended policy, not the grant's
                        # opening policy. Retain the start until ON resumes.
                        pending.append(request)
                    # OFF cannot legitimately retain an active grant; drop a
                    # malformed stale start instead of claiming open access.
                elif request.accepts_later_policy:
                    if request.policy_revision <= applied_revision:
                        enforced.append(request)
                    else:
                        pending.append(request)
                elif request.policy_revision == applied_revision:
                    enforced.append(request)
                elif request.policy_revision > applied_revision:
                    # Defensive support for callers that enqueue a future
                    # revision before an earlier reconciliation completes.
                    pending.append(request)
                else:
                    # A newer policy reached the backend without this exact
                    # transition ever applying. Its permission-bearing speech
                    # would now be false, so discard the superseded request.
                    continue
            self._enforced_goal_access_feedback.extend(enforced)
            self._pending_goal_access_feedback = pending
            return bool(enforced)

    def release_goal_access_feedback(self) -> bool:
        """Publish policy-approved requests after session events are durable."""

        with self._lock:
            if not self._enforced_goal_access_feedback:
                return False
            self._ready_goal_access_feedback.extend(
                self._enforced_goal_access_feedback
            )
            self._enforced_goal_access_feedback = []
            return True

    def pop_ready_goal_access_feedback(
        self,
    ) -> GoalAccessFeedbackRequest | None:
        """Claim the oldest enforcement-approved acknowledgment exactly once."""

        with self._lock:
            if not self._ready_goal_access_feedback:
                return None
            return self._ready_goal_access_feedback.pop(0)

    @contextmanager
    def goal_access_feedback_delivery(self):
        """Serialize acknowledgments without serializing enforcement."""

        with self._goal_access_feedback_delivery_lock:
            yield

    def cancel_pending_goal_access_start(
        self,
        access: GoalAccessInfo,
    ) -> bool:
        """Drop an unapplied start acknowledgment when that grant ends first."""

        with self._lock:
            previous_count = len(self._pending_goal_access_feedback)
            self._pending_goal_access_feedback = [
                pending
                for pending in self._pending_goal_access_feedback
                if not (
                    pending.kind == "goal_access_start"
                    # The exact active-record object survives stop, expiry,
                    # replacement, Disable, and shutdown. Object identity
                    # avoids collisions when tests or fast requests reuse the
                    # same injected timestamp and otherwise identical values.
                    and pending.grant is access
                )
            ]
            return len(self._pending_goal_access_feedback) != previous_count

    def _hosts_policy_signature(self) -> tuple[str, tuple[str, ...]]:
        """Return the exact hosts backend action desired by current state."""

        # OFF clears the managed section; every other mode applies the current
        # domain tuple. Including the action distinguishes OFF from an unusual
        # active policy whose effective blocklist is empty.
        if self.mode is Mode.OFF:
            return "clear", ()
        return "apply", self.effective_blocklist()

    def _mark_policy_changed(
        self,
        previous_hosts_policy: tuple[str, tuple[str, ...]] | None = None,
    ) -> None:
        """Advance monitoring identity and dirty hosts only when it changed."""

        # App-only transitions still reset analyzer context but must not rewrite
        # an identical hosts section or flush DNS.
        if (
            previous_hosts_policy is None
            or previous_hosts_policy != self._hosts_policy_signature()
        ):
            self._enforcement_dirty = True
        self._monitoring_revision += 1

    # ---------- mode transitions ----------

    def start_session(
        self,
        topic: str,
        now: datetime | None = None,
        *,
        allowed_groups: list[str] | tuple[str, ...] | None = None,
        project: str | None = None,
        agentic: bool = False,
    ) -> GoalAccessInfo | None:
        # Requirement 4: topic entered per session, history feeds the dropdown.
        # Validate every option before touching live state, so a forged form
        # value cannot leave a half-started session behind.
        selected_groups = normalize_access_keys(allowed_groups or ())
        project_name = project.strip() if project else None
        resolve_work_allowed_groups(
            selected_groups,
            project_name,
            self.project_allowlists,
        )
        with self._lock:
            if self._shutting_down:
                raise RuntimeError("Application shutdown is already in progress.")
            previous_hosts_policy = self._hosts_policy_signature()
            # Returning the cleared immutable record lets the route log the
            # old grant as session-replaced without a separate unlocked read.
            ended_goal_access = self.goal_access
            self.mode = Mode.ON
            self.session_start = now or datetime.now()
            self.session_end = None
            self.topic = topic
            # A new session is the exact boundary selected for dashboard
            # history; OFF and BREAK deliberately keep the prior entries.
            self.last_verdict = None
            self.evaluation_history.clear()
            self._latest_verdict_accounting = None
            self.current_break = None
            self.goal_access = None
            self.active_project = project_name
            self.task_allowed_groups = selected_groups
            self.agentic_mode = agentic
            self.agent_busy = False
            # Dedup then prepend → most-recent-first history.
            if topic in self.previous_topics:
                self.previous_topics.remove(topic)
            self.previous_topics.insert(0, topic)
            self._mark_policy_changed(previous_hosts_policy)
            self.productive_streak_min = 0
            return ended_goal_access

    def begin_shutdown(
        self,
        now: datetime | None = None,
    ) -> GoalAccessInfo | None:
        """Enter terminal OFF state and reject any later session replacement."""

        with self._lock:
            previous_hosts_policy = self._hosts_policy_signature()
            self._shutting_down = True
            ended_goal_access = self.goal_access
            self.mode = Mode.OFF
            self.current_break = None
            self.goal_access = None
            self.session_end = now or datetime.now()
            self._mark_policy_changed(previous_hosts_policy)
            return ended_goal_access

    def try_disable(self, phrase: str, now: datetime | None = None) -> bool:
        # Requirement 6: only the EXACT phrase flips everything OFF —
        # comparison is deliberately case- and whitespace-sensitive friction.
        ok, _ = self.try_disable_with_goal_access(phrase, now=now)
        return ok

    def try_disable_with_goal_access(
        self,
        phrase: str,
        now: datetime | None = None,
    ) -> tuple[bool, GoalAccessInfo | None]:
        """Disable atomically and return any grant ended by that transition."""

        with self._lock:
            if phrase != CONFIRMATION_PHRASE:
                return False, None
            previous_hosts_policy = self._hosts_policy_signature()
            ended_goal_access = self.goal_access
            self.mode = Mode.OFF
            self.current_break = None
            self.goal_access = None
            self._mark_policy_changed(previous_hosts_policy)
            self.session_end = now or datetime.now()
            return True, ended_goal_access

    # ---------- goal-based temporary website/app access ----------

    def start_goal_access(
        self,
        goal: str,
        allowed_groups: list[str] | tuple[str, ...],
        minutes: int | None,
        now: datetime | None = None,
    ) -> tuple[GoalAccessInfo | None, str]:
        """Start one grant; sequential grants have no count or allowance cap."""

        # Validate external input before constructing the record. Group keys
        # use the same canonical policy order as permanent task access.
        if not isinstance(goal, str) or not goal.strip():
            return None, "A temporary-access goal is required."
        try:
            normalized_groups = normalize_access_keys(allowed_groups)
        except (TypeError, ValueError) as exc:
            return None, str(exc)
        if not normalized_groups:
            return None, "Choose at least one access group."
        # bool is an int subclass, so reject it explicitly rather than turning
        # True into an accidental one-minute grant:
        # https://docs.python.org/3/library/functions.html#isinstance
        if minutes is not None and (
            isinstance(minutes, bool) or not isinstance(minutes, int)
        ):
            return None, "Duration must be a whole number of minutes."
        if minutes is not None and not 1 <= minutes <= 240:
            return None, "Duration must be between 1 and 240 minutes."

        current = now or datetime.now()
        with self._lock:
            if self.mode is not Mode.ON:
                return None, "Goal access can only start during an active session."
            if self.goal_access is not None:
                return None, "A goal-based access grant is already active."
            previous_hosts_policy = self._hosts_policy_signature()
            access = GoalAccessInfo(
                goal=goal.strip(),
                start_time=current,
                end_time=(
                    current + timedelta(minutes=minutes)
                    if minutes is not None
                    else None
                ),
                requested_minutes=minutes,
                allowed_groups=normalized_groups,
            )
            self.goal_access = access
            self._mark_policy_changed(previous_hosts_policy)
            return access, ""

    def stop_goal_access(
        self,
        now: datetime | None = None,
    ) -> GoalAccessInfo | None:
        """End and return the current grant; stale repeated stops are no-ops."""

        # ``now`` keeps every state transition clock-injectable and gives the
        # route one uniform interface; timing fields remain the original grant.
        _ = now
        with self._lock:
            ended = self.goal_access
            if ended is not None:
                previous_hosts_policy = self._hosts_policy_signature()
                self.goal_access = None
                self._mark_policy_changed(previous_hosts_policy)
            return ended

    def end_goal_access_if_due(
        self,
        now: datetime | None = None,
    ) -> GoalAccessInfo | None:
        """Expire a timed grant in any mode and return its immutable record."""

        current = now or datetime.now()
        with self._lock:
            active = self.goal_access
            if (
                active is None
                or active.end_time is None
                or current < active.end_time
            ):
                return None
            previous_hosts_policy = self._hosts_policy_signature()
            self.goal_access = None
            self._mark_policy_changed(previous_hosts_policy)
            return active

    # ---------- breaks & allowance ----------

    def social_minutes_remaining(self, now: datetime | None = None) -> int:
        # Cap minus what today already reserved; unknown dates count as 0 used,
        # which IS the midnight rollover (new date → fresh key).
        now = now or datetime.now()
        used = self.social_used_by_date.get(now.date().isoformat(), 0)
        return max(0, self.daily_social_cap_min - used)

    def start_break(
        self,
        purpose: str,
        minutes: int,
        kind: str,
        allowed_groups: list[str] | tuple[str, ...] | None = None,
        now: datetime | None = None,
    ) -> tuple[bool, str]:
        """Begin a timed break; returns (ok, reason-if-refused)."""
        # Checkbox values are untrusted HTTP input in production. Normalize
        # before allowance reservation so a forged key cannot partly mutate
        # the daily cap and then fail.
        normalized_groups = normalize_access_keys(allowed_groups or ())
        now = now or datetime.now()
        with self._lock:
            if self.mode is not Mode.ON:
                return False, "Breaks can only start from an active session."
            if kind == "social_media":
                remaining = self.social_minutes_remaining(now)
                if minutes > remaining:
                    # Requirement 5: hard 2 h/day cap — refuse, don't clamp.
                    return False, (f"Only {remaining} social-media minutes left "
                                   f"today (cap {self.daily_social_cap_min}).")
                # Reserve the minutes up front so parallel requests can't
                # double-spend the allowance.
                key = now.date().isoformat()
                self.social_used_by_date[key] = self.social_used_by_date.get(key, 0) + minutes
            previous_hosts_policy = self._hosts_policy_signature()
            # timedelta arithmetic:
            # https://docs.python.org/3/library/datetime.html#timedelta-objects
            self.current_break = BreakInfo(
                purpose=purpose, kind=kind,
                start_time=now,
                end_time=now + timedelta(minutes=minutes),
                requested_minutes=minutes,
                allowed_groups=normalized_groups,
            )
            self.mode = Mode.BREAK
            self._mark_policy_changed(previous_hosts_policy)
            return True, ""

    def _restore_after_break(self) -> None:
        """Restore focus-mode fields while the caller holds ``self._lock``."""

        previous_hosts_policy = self._hosts_policy_signature()
        self.current_break = None                  # remove temporary exceptions
        self.mode = Mode.ON                        # resume the active session
        self.productive_streak_min = 0             # restart post-break streak
        # The last visible verdict remains correctable as history, but it no
        # longer contributes to the newly started post-break streak.
        self._latest_verdict_accounting = None
        self._mark_policy_changed(previous_hosts_policy)

    def end_break_if_due(self, now: datetime | None = None) -> bool:
        # Called by the enforcer watchdog every few seconds; True = restored.
        now = now or datetime.now()
        with self._lock:
            if self.mode is Mode.BREAK and self.current_break and now >= self.current_break.end_time:
                # Expiry consumes the full up-front reservation, so only the
                # shared mode transition is needed here.
                self._restore_after_break()
                return True
            return False

    def stop_break(self, now: datetime | None = None) -> BreakStopResult | None:
        """Stop the active break and refund unelapsed social-media minutes."""

        current = now or datetime.now()
        with self._lock:
            if self.mode is not Mode.BREAK or self.current_break is None:
                # A stale browser click can race the expiry watchdog; treating
                # it as a no-op keeps the POST idempotent and side-effect free.
                return None

            active_break = self.current_break
            requested_minutes = max(0, active_break.requested_minutes)
            # datetime subtraction yields timedelta; total_seconds preserves
            # sub-second precision before the explicit started-minute rounding:
            # https://docs.python.org/3/library/datetime.html#datetime.timedelta.total_seconds
            raw_elapsed_seconds = max(
                0.0,
                (current - active_break.start_time).total_seconds(),
            )
            capped_elapsed_seconds = min(
                raw_elapsed_seconds,
                requested_minutes * 60,
            )
            # ceil implements the chosen "every started minute counts" rule:
            # https://docs.python.org/3.13/library/math.html#math.ceil
            charged_minutes = min(
                requested_minutes,
                math.ceil(capped_elapsed_seconds / 60),
            )
            refunded_minutes = 0
            if active_break.kind == "social_media":
                refunded_minutes = requested_minutes - charged_minutes
                allowance_date = active_break.start_time.date().isoformat()
                reserved_total = self.social_used_by_date.get(allowance_date, 0)
                # Clamp protects an already-corrupt legacy state value from a
                # refund making the daily usage even more invalid.
                self.social_used_by_date[allowance_date] = max(
                    0,
                    reserved_total - refunded_minutes,
                )

            result = BreakStopResult(
                purpose=active_break.purpose,
                kind=active_break.kind,
                requested_minutes=active_break.requested_minutes,
                elapsed_seconds=math.ceil(capped_elapsed_seconds),
                charged_minutes=charged_minutes,
                refunded_minutes=refunded_minutes,
            )
            self._restore_after_break()
            return result

    # ---------- effective enforcement views ----------

    @property
    def enforcement_dirty(self) -> bool:
        """Whether desired hosts policy still needs a successful backend write."""

        with self._lock:
            return self._enforcement_dirty

    def reconcile_enforcement(self, blocker) -> bool:
        """Atomically publish the latest desired hosts policy when it is dirty.

        The state lock spans policy computation and the backend call, so an
        older writer can never land after a newer transition. Exceptions
        deliberately propagate while ``_enforcement_dirty`` remains true for
        the scheduler's next retry.
        """

        with self._lock:
            if not self._enforcement_dirty:
                return False
            if self.mode is Mode.OFF:
                blocker.clear()
            else:
                blocker.apply(self.effective_blocklist())
            self._enforcement_dirty = False
            return True

    def _allowed_group_keys(self) -> set[str]:
        """Return the scope-aware union used by both enforcement backends."""

        # Task/preset permissions remain active during focused work and breaks.
        allowed = set(self.work_allowed_groups)
        # Goal access is deliberately absent during BREAK: its wall-clock timer
        # continues, but every grant-only website/app permission is suspended.
        if self.mode is Mode.ON and self.goal_access:
            allowed |= set(self.goal_access.allowed_groups)
        if self.mode is Mode.BREAK and self.current_break:
            allowed |= set(self.current_break.allowed_groups)
        return allowed

    @property
    def work_allowed_groups(self) -> tuple[str, ...]:
        """Return the ordered union of one-off and saved-preset task groups."""

        with self._lock:
            return resolve_work_allowed_groups(
                self.task_allowed_groups,
                self.active_project,
                self.project_allowlists,
            )

    @property
    def work_allowed_sites(self) -> tuple[str, ...]:
        """Derive task website groups for hosts/status compatibility."""

        with self._lock:
            return access_site_keys(self.work_allowed_groups)

    @property
    def work_allowed_apps(self) -> tuple[str, ...]:
        """Derive task app groups for process enforcement and status."""

        with self._lock:
            return access_app_keys(self.work_allowed_groups)

    def effective_blocklist(self) -> tuple[str, ...]:
        # Full blocklist minus every domain variant of the allowed site keys.
        with self._lock:
            # Agentic mode + agent working = sanctioned waiting time: the
            # ENTIRE blocklist opens (user decision); re-applied full the
            # moment the agent is detected idle.
            if self.mode is Mode.ON and self.agentic_mode and self.agent_busy:
                return ()
            freed = {d for key in access_site_keys(self._allowed_group_keys())
                     for d in expand_www(SITE_DOMAINS.get(key, []))}
            return tuple(d for d in all_blocked_domains() if d not in freed)

    def effective_kill_processes(self) -> tuple[str, ...]:
        # Use the identical scope union as hosts enforcement, so a dual-surface
        # key such as Discord cannot drift between website and app behavior.
        with self._lock:
            spared_keys = set(access_app_keys(self._allowed_group_keys()))
            spared = {p for key in spared_keys for p in APP_PROCESSES.get(key, [])}
            return tuple(p for procs in APP_PROCESSES.values() for p in procs
                         if p not in spared)

    def set_agentic(self, on: bool) -> None:
        # Enable/disable agentic mode; busy flag resets so unblocking only
        # ever follows a fresh vision verdict, never a stale one.
        with self._lock:
            changed = on != self.agentic_mode or self.agent_busy
            previous_hosts_policy = (
                self._hosts_policy_signature() if changed else None
            )
            self.agentic_mode = on
            self.agent_busy = False
            if changed:
                self._mark_policy_changed(previous_hosts_policy)

    def set_agent_busy(self, busy: bool) -> bool:
        """Record the latest agent-activity verdict; True only on CHANGE so
        the scheduler applies hosts/speech on transitions, not every poll."""
        with self._lock:
            changed = busy != self.agent_busy
            previous_hosts_policy = (
                self._hosts_policy_signature() if changed else None
            )
            self.agent_busy = busy
            if changed:
                self._mark_policy_changed(previous_hosts_policy)
            return changed

    def set_project(self, name: str | None) -> None:
        # A productive-project preset may allowlist configured website/app
        # groups while enforcement stays ON for everything else.
        project_name = name.strip() if name else None
        with self._lock:
            previous_hosts_policy = self._hosts_policy_signature()
            previous_groups = resolve_work_allowed_groups(
                self.task_allowed_groups,
                self.active_project,
                self.project_allowlists,
            )
            next_groups = resolve_work_allowed_groups(
                self.task_allowed_groups,
                project_name,
                self.project_allowlists,
            )
            self.active_project = project_name
            if next_groups != previous_groups:
                self._mark_policy_changed(previous_hosts_policy)

    # ---------- monitoring hooks ----------

    @property
    def monitoring_active(self) -> bool:
        # Captures/analysis run only during focused work: BREAK of either
        # kind pauses monitoring (nudging someone on a sanctioned break or
        # away from the desk would be noise), OFF disables everything, and
        # agent-busy waiting time is sanctioned too — no nudges while the
        # user's AI agent is still working. Normal monitoring resumes the
        # moment the agent goes idle.
        with self._lock:
            return self._monitoring_active_locked()

    def _monitoring_active_locked(self) -> bool:
        """Compute capture eligibility while the caller holds ``self._lock``."""

        return self.mode is Mode.ON and not (self.agentic_mode and self.agent_busy)

    def monitoring_context(self) -> MonitoringContext:
        """Return one locked context/key for a complete analyzer operation."""

        with self._lock:
            return self._monitoring_context_locked()

    def _monitoring_context_locked(self) -> MonitoringContext:
        """Build the immutable analyzer key while the caller holds the lock."""

        permanent_groups = resolve_work_allowed_groups(
            self.task_allowed_groups,
            self.active_project,
            self.project_allowlists,
        )
        grant = self.goal_access
        return MonitoringContext(
            revision=self._monitoring_revision,
            session_start=self.session_start,
            topic=self.topic,
            permanent_groups=permanent_groups,
            goal_access_start_time=(grant.start_time if grant else None),
            goal_access_goal=(grant.goal if grant else None),
            goal_access_groups=(grant.allowed_groups if grant else ()),
        )

    @property
    def recent_verdicts(self) -> list[dict]:
        """Return the bounded five-entry context window used by feedback."""

        with self._lock:
            # Return copies so a prompt builder cannot mutate shared state.
            return [dict(item) for item in self.evaluation_history[-5:]]

    def record_verdict(
        self,
        productive: bool,
        minutes: int,
        observed: str = "",
        reason: str = "",
        now: datetime | None = None,
        verdict_id: str | None = None,
    ) -> str | None:
        """Fold one analyzer verdict into the streak; return 'praise'/'nudge'/None.

        Requirement 4: nudge whenever unproductive; praise once per 30
        consecutive productive minutes (streak then restarts so a long
        session earns praise again every 30 min). Every verdict also joins
        the current-session evaluation history for dashboard and TTS grounding.
        """
        identity = (
            _canonical_verdict_id(verdict_id)
            if verdict_id is not None
            else new_verdict_id()
        )
        with self._lock:
            timestamp = now or datetime.now()
            streak_before_min = self.productive_streak_min
            self.productive_streak_min, outcome = _fold_productive_streak(
                streak_before_min,
                productive,
                minutes,
            )

            # One canonical entry powers last_verdict, full UI history and the
            # bounded TTS slice, preventing timestamp/content drift.
            entry = {
                "verdict_id": identity,
                "ts": timestamp.isoformat(),
                "model_productive": productive,
                "productive": productive,
                "credited_minutes": minutes,
                "correction_revision": 0,
                "corrected_at": None,
                "reason": reason,
                "observed": observed,
            }
            self.evaluation_history.append(entry)
            self.last_verdict = dict(entry)
            self._latest_verdict_accounting = _LatestVerdictAccounting(
                verdict_id=identity,
                streak_before_min=streak_before_min,
                credited_minutes=minutes,
            )
            return outcome

    def record_verdict_if_context(
        self,
        expected_context: MonitoringContext,
        productive: bool,
        minutes: int,
        observed: str = "",
        reason: str = "",
        now: datetime | None = None,
        verdict_id: str | None = None,
    ) -> tuple[bool, str | None]:
        """Record only if monitoring still uses the caller's exact revision."""

        with self._lock:
            if (
                not self._monitoring_active_locked()
                or self._monitoring_context_locked() != expected_context
            ):
                return False, None
            outcome = self.record_verdict(
                productive,
                minutes,
                observed=observed,
                reason=reason,
                now=now,
                verdict_id=verdict_id,
            )
            return True, outcome

    def correct_latest_verdict(
        self,
        verdict_id: str,
        expected_revision: int,
        productive: bool,
        now: datetime | None = None,
    ) -> VerdictCorrectionResult | None:
        """Atomically replace the latest effective label or reject stale input.

        Returning ``None`` gives the HTTP layer one conflict result for a
        replaced verdict and an out-of-date correction revision. Repeating an
        already-applied desired value is an idempotent successful no-op.
        """

        identity = _canonical_verdict_id(verdict_id)
        if (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision < 0
        ):
            raise ValueError("Correction revision must be a non-negative integer.")
        if not isinstance(productive, bool):
            raise ValueError("Corrected productivity must be true or false.")
        changed_at = now or datetime.now()
        with self._lock:
            if not self.evaluation_history:
                return None
            entry = self.evaluation_history[-1]
            if entry["verdict_id"] != identity:
                return None

            current_productive = entry["productive"]
            current_revision = entry["correction_revision"]
            evaluated_at = datetime.fromisoformat(entry["ts"])
            if current_productive is productive:
                # A genuine retry either carries the current revision (a
                # no-op command) or the immediately preceding revision whose
                # one successful toggle produced this exact desired label.
                # Older same-label requests have crossed an ABA cycle and
                # must conflict instead of silently masking stale UI state.
                if expected_revision not in {
                    current_revision,
                    current_revision - 1,
                }:
                    return None
                return VerdictCorrectionResult(
                    changed=False,
                    verdict_id=identity,
                    evaluated_at=evaluated_at,
                    model_productive=entry["model_productive"],
                    from_productive=current_productive,
                    to_productive=productive,
                    credited_minutes=entry["credited_minutes"],
                    correction_revision=current_revision,
                    changed_at=None,
                    streak_adjusted=False,
                    productive_streak_min=self.productive_streak_min,
                    restored_model_verdict=(
                        productive is entry["model_productive"]
                    ),
                )
            if current_revision != expected_revision:
                return None

            accounting = self._latest_verdict_accounting
            streak_adjusted = (
                accounting is not None
                and accounting.verdict_id == identity
            )
            if streak_adjusted:
                # The correction has its own neutral acknowledgment; discard
                # the canonical fold's nudge/praise outcome while preserving
                # exactly the same numeric rollover behavior.
                self.productive_streak_min, _ = _fold_productive_streak(
                    accounting.streak_before_min,
                    productive,
                    accounting.credited_minutes,
                )

            next_revision = current_revision + 1
            entry["productive"] = productive
            entry["correction_revision"] = next_revision
            entry["corrected_at"] = (
                None
                if productive is entry["model_productive"]
                else changed_at.isoformat()
            )
            self.last_verdict = dict(entry)
            return VerdictCorrectionResult(
                changed=True,
                verdict_id=identity,
                evaluated_at=evaluated_at,
                model_productive=entry["model_productive"],
                from_productive=current_productive,
                to_productive=productive,
                credited_minutes=entry["credited_minutes"],
                correction_revision=next_revision,
                changed_at=changed_at,
                streak_adjusted=streak_adjusted,
                productive_streak_min=self.productive_streak_min,
                restored_model_verdict=(productive is entry["model_productive"]),
            )

    def verdict_matches(
        self,
        verdict_id: str,
        productive: bool,
        correction_revision: int,
    ) -> bool:
        """Return whether feedback still describes the unchanged latest verdict."""

        with self._lock:
            return bool(
                self.last_verdict
                and self.last_verdict["verdict_id"] == verdict_id
                and self.last_verdict["productive"] is productive
                and self.last_verdict["correction_revision"]
                == correction_revision
            )

    def context_summary(self, now: datetime | None = None) -> str:
        """Build the bounded current-session snapshot used by message prompts.

        The snapshot covers live session/access state and at most five recent
        monitor observations; it is not a complete session-history export.
        """
        now = now or datetime.now()
        with self._lock:
            # OFF keeps the finished session available for verdict review, so
            # later correction acknowledgements must not imply it kept running.
            elapsed_until = self.session_end or now
            minutes_in = int((elapsed_until - self.session_start).total_seconds() // 60) \
                if self.session_start else 0
            lines = [
                f"topic: {self.topic or '(none)'}",

                f"minutes into session: {minutes_in}",
                f"productive streak: {self.productive_streak_min} min",
                f"social allowance left today: {self.social_minutes_remaining(now)} min",
            ]
            if self.active_project:
                lines.append(f"saved project preset: {self.active_project}")
            if self.work_allowed_groups:
                lines.append(
                    "work-required website/app access groups allowed: "
                    + ", ".join(self.work_allowed_groups)
                )
            if self.goal_access:
                lines.append(f"temporary access goal: {self.goal_access.goal}")
                lines.append(
                    "temporary website/app access groups selected: "
                    + ", ".join(self.goal_access.allowed_groups)
                )
                if self.mode is Mode.BREAK:
                    lines.append(
                        "temporary goal access: all website/app permissions "
                        "suspended during break"
                    )
            if self.agentic_mode:
                lines.append("agentic mode: on, AI agent currently "
                             + ("working" if self.agent_busy else "idle"))
            if self.current_break:
                lines.append(f"on a {self.current_break.kind} break for: "
                             f"{self.current_break.purpose}")
            recent = self.evaluation_history[-5:]
            if recent:
                lines.append("recent monitor observations (oldest first):")
                lines += [f"  [{datetime.fromisoformat(v['ts']):%H:%M}] "
                          f"{'productive' if v['productive'] else 'NOT productive'}"
                          f" - {v['observed'] or v['reason']}"
                          for v in recent]
            return "\n".join(lines)

    def status_snapshot(self, now: datetime | None = None) -> dict:
        """Return one locked, JSON-safe snapshot for the realtime dashboard."""

        current = now or datetime.now()
        with self._lock:
            # Freeze session duration at disable time; active sessions continue
            # advancing on every poll.
            elapsed_until = self.session_end or current
            elapsed_s = (
                max(0, int((elapsed_until - self.session_start).total_seconds()))
                if self.session_start
                else 0
            )
            if self.mode is Mode.OFF:
                pause_reason = "Enforcement is off."
            elif self.mode is Mode.BREAK:
                pause_reason = "A scheduled break is active."
            elif self.agentic_mode and self.agent_busy:
                pause_reason = "The AI coding agent is working."
            else:
                pause_reason = None

            enforcement_on = self.mode is not Mode.OFF
            blocked_domains = self.effective_blocklist() if enforcement_on else ()
            target_processes = (
                self.effective_kill_processes() if enforcement_on else ()
            )
            br = self.current_break
            grant = self.goal_access
            work_groups = self.work_allowed_groups
            work_sites = access_site_keys(work_groups)
            work_apps = access_app_keys(work_groups)
            break_payload = (
                {
                    "purpose": br.purpose,
                    "kind": br.kind,
                    "until": br.end_time.isoformat(),
                    "remaining_s": max(
                        0,
                        int((br.end_time - current).total_seconds()),
                    ),
                    "allowed_groups": list(br.allowed_groups),
                    "allowed_group_labels": list(
                        access_labels(br.allowed_groups)
                    ),
                    "allowed_sites": list(access_site_keys(br.allowed_groups)),
                    "allowed_apps": list(access_app_keys(br.allowed_groups)),
                }
                if br
                else None
            )
            goal_access_payload = (
                {
                    "goal": grant.goal,
                    "allowed_groups": list(grant.allowed_groups),
                    "allowed_group_labels": list(
                        access_labels(grant.allowed_groups)
                    ),
                    "allowed_sites": list(
                        access_site_keys(grant.allowed_groups)
                    ),
                    "allowed_site_labels": list(
                        access_labels(access_site_keys(grant.allowed_groups))
                    ),
                    "allowed_apps": list(access_app_keys(grant.allowed_groups)),
                    "started_at": grant.start_time.isoformat(),
                    "expires_at": (
                        grant.end_time.isoformat() if grant.end_time else None
                    ),
                    "requested_minutes": grant.requested_minutes,
                    "remaining_s": (
                        max(0, int((grant.end_time - current).total_seconds()))
                        if grant.end_time
                        else None
                    ),
                    "until_session_end": grant.end_time is None,
                    "suspended": self.mode is Mode.BREAK,
                }
                if grant
                else None
            )
            # Reversed copies put the newest item first without exposing the
            # mutable list shared with the scheduler thread.
            history = [dict(item) for item in reversed(self.evaluation_history)]
            return {
                "mode": self.mode.value,
                "topic": self.topic,
                "active_project": self.active_project,
                "work_access": {
                    "project": self.active_project,
                    "selected_groups": list(self.task_allowed_groups),
                    "allowed_groups": list(work_groups),
                    "allowed_group_labels": list(access_labels(work_groups)),
                    # Split arrays remain additive diagnostics for callers that
                    # need to inspect the concrete enforcement backends.
                    "selected_sites": list(
                        access_site_keys(self.task_allowed_groups)
                    ),
                    "selected_apps": list(
                        access_app_keys(self.task_allowed_groups)
                    ),
                    "allowed_sites": list(work_sites),
                    "allowed_site_labels": list(access_labels(work_sites)),
                    "allowed_apps": list(work_apps),
                },
                "session_started_at": (
                    self.session_start.isoformat() if self.session_start else None
                ),
                "session_elapsed_s": elapsed_s,
                "productive_streak_min": self.productive_streak_min,
                "social_minutes_remaining": self.social_minutes_remaining(current),
                "social_minutes_cap": self.daily_social_cap_min,
                "last_verdict": dict(self.last_verdict) if self.last_verdict else None,
                "evaluation_history": history,
                "monitoring_active": self.monitoring_active,
                "monitoring_pause_reason": pause_reason,
                "agentic_mode": self.agentic_mode,
                "agent_busy": self.agent_busy,
                "break": break_payload,
                "goal_access": goal_access_payload,
                "enforcement": {
                    "hosts_active": bool(blocked_domains),
                    "blocked_domain_count": len(blocked_domains),
                    "app_killer_active": bool(target_processes),
                    "target_process_count": len(target_processes),
                    "reconciliation_pending": self._enforcement_dirty,
                },
            }

    # ---------- persistence (results/state.json via storage.py) ----------

    def to_dict(self) -> dict:
        # Only what must survive a restart: allowance usage (the 2 h cap must
        # not reset on relaunch) and topic history (UI dropdown). Live mode
        # deliberately resets to OFF for safety on crash/restart.
        with self._lock:
            return {"social_used_by_date": dict(self.social_used_by_date),
                    "previous_topics": list(self.previous_topics)}

    def load_dict(self, data: dict) -> None:
        # Tolerant restore: missing keys default to empty (first run).
        with self._lock:
            self.social_used_by_date = dict(data.get("social_used_by_date", {}))
            self.previous_topics = list(data.get("previous_topics", []))
