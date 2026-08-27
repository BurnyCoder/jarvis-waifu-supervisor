# Flask control panel. Global context: this is the ONLY user interface —
# every mode change flows through these routes, which mutate SessionState and
# re-apply/clear the hosts blocker accordingly. App-factory pattern so tests
# can build an app around fakes:
# https://flask.palletsprojects.com/en/stable/patterns/appfactories/

import logging
from datetime import datetime
from uuid import UUID

# Flask quickstart: https://flask.palletsprojects.com/en/stable/quickstart/
from flask import Flask, jsonify, redirect, render_template, request, url_for

from deepwork.access_policy import (
    access_app_keys,
    access_labels,
    access_options,
    access_site_keys,
    normalize_access_keys,
)
from deepwork.feedback.goal_access import (
    InlineGoalAccessFeedback,
    queue_goal_access_feedback,
    queue_transition_feedback,
)
from deepwork.state import goal_access_event
from deepwork.webui.status import build_status_payload, empty_runtime_snapshot

log = logging.getLogger(__name__)

# These legacy names represented split site/app inputs. Rejecting them avoids
# silently weakening a clean-contract request that an older caller believes
# granted access.
_LEGACY_ACCESS_FIELDS = frozenset({"allowed_sites", "allowed_apps"})


def _parse_allowed_groups(form, *, required: bool = False) -> tuple[str, ...]:
    """Validate repeated canonical checkbox values from an untrusted form."""

    # Werkzeug MultiDict membership detects even an explicitly empty legacy
    # field, giving old callers a clear migration failure instead of a no-op:
    # https://werkzeug.palletsprojects.com/en/stable/datastructures/#werkzeug.datastructures.MultiDict
    submitted_legacy = sorted(_LEGACY_ACCESS_FIELDS.intersection(form))
    if submitted_legacy:
        raise ValueError(
            "Legacy allowed_sites/allowed_apps fields are no longer accepted; "
            "submit repeated allowed_groups values.",
        )
    # getlist preserves every same-name checkbox value:
    # https://werkzeug.palletsprojects.com/en/stable/datastructures/#werkzeug.datastructures.MultiDict.getlist
    groups = normalize_access_keys(form.getlist("allowed_groups"))
    if required and not groups:
        raise ValueError("Choose at least one access group.")
    return groups


def _parse_goal_access_form(form) -> tuple[str, tuple[str, ...], int | None]:
    """Validate one untrusted grant form before state or enforcement changes."""

    goal = form.get("goal", "").strip()
    if not goal:
        raise ValueError("A temporary-access goal is required.")

    allowed_groups = _parse_allowed_groups(form, required=True)

    duration_mode = form.get("duration_mode", "")
    if duration_mode not in {"timed", "session_end"}:
        raise ValueError("Duration mode must be timed or session_end.")
    if duration_mode == "session_end":
        return goal, allowed_groups, None

    raw_minutes = form.get("minutes", "").strip()
    try:
        minutes = int(raw_minutes)
    except (TypeError, ValueError) as exc:
        raise ValueError("Timed access minutes must be a whole number.") from exc
    if not 1 <= minutes <= 240:
        raise ValueError("Timed access must be between 1 and 240 minutes.")
    return goal, allowed_groups, minutes


def _parse_verdict_correction_form(form) -> tuple[str, int, bool]:
    """Validate the optimistic latest-verdict correction command."""

    verdict_id = form.get("verdict_id", "").strip()
    if not verdict_id:
        raise ValueError("A verdict ID is required.")
    try:
        verdict_id = str(UUID(verdict_id))
    except ValueError as exc:
        raise ValueError("Verdict ID must be a valid UUID.") from exc

    raw_revision = form.get("expected_revision", "").strip()
    try:
        expected_revision = int(raw_revision)
    except (TypeError, ValueError) as exc:
        raise ValueError("The correction revision must be a whole number.") from exc
    if expected_revision < 0:
        raise ValueError("The correction revision cannot be negative.")

    raw_productive = form.get("productive", "")
    if raw_productive not in {"true", "false"}:
        raise ValueError("Productive must be exactly true or false.")
    return verdict_id, expected_revision, raw_productive == "true"


def _verdict_label(productive: bool) -> str:
    """Return the same human label used by the dashboard verdict badge."""

    return "productive" if productive else "off track"


def create_app(
    state,
    blocker,
    store,
    messages,
    speech,
    runtime_snapshot=None,
    now_fn=None,
    goal_access_feedback=None,
) -> Flask:
    app = Flask(__name__)                          # templates/ auto-discovered
    # Optional providers preserve the app factory's dependency-injected tests.
    get_runtime_snapshot = runtime_snapshot or empty_runtime_snapshot
    get_now = now_fn or datetime.now
    goal_feedback = (
        goal_access_feedback
        or InlineGoalAccessFeedback(state, messages, speech)
    )

    def append_session_event(event: dict, action: str) -> None:
        """Retain a failed JSONL append for retry without skipping policy work."""

        try:
            store.append_session_event(event)
        except Exception:
            log.exception("%s session-event persistence pending retry", action)

    def save_state(action: str) -> None:
        """Keep a state-file failure from preventing current hosts enforcement."""

        try:
            store.save_state(state.to_dict())
        except Exception:
            log.exception("%s persistent-state save failed", action)

    def reconcile_or_503(action: str) -> tuple[str, int] | None:
        """Apply the latest locked policy or expose its automatic retry state."""

        retry_events = getattr(store, "retry_session_events", None)
        if retry_events is not None:
            try:
                retry_events()
            except Exception:
                # Event durability and hosts safety are independent: continue
                # enforcement, but keep transition speech pending behind JSONL.
                log.exception("%s session-event retry failed", action)
        try:
            state.reconcile_enforcement(blocker)
        except Exception:
            # Dirty policy and ordered feedback remain queued for a later
            # enforcer retry; never announce access before it is applied.
            log.exception(
                "%s enforcement failed; current policy is pending retry",
                action,
            )
            return "State changed, but hosts enforcement is pending retry.", 503
        state.mark_goal_access_feedback_policy_applied()
        # Publishing is lock-local and fast. Slow model/TTS delivery begins
        # only after the caller releases the lifecycle coordinator.
        if not getattr(store, "session_events_pending", False):
            state.release_goal_access_feedback()
        return None

    @app.get("/")
    def index():
        # Jinja template gets the topic history for the <datalist> dropdown
        # and current mode for display:
        # https://flask.palletsprojects.com/en/stable/quickstart/#rendering-templates
        projects = [
            {
                "name": name,
                "groups": list(access_labels(state.project_allowlists[name])),
            }
            for name in sorted(state.project_allowlists)
        ]
        return render_template(
            "index.html",
            topics=state.previous_topics,
            mode=state.mode.value,
            projects=projects,
            access_options=access_options(),
            goal_access_active=state.goal_access is not None,
        )

    @app.post("/start")
    def start():
        # Entering a topic starts ON mode; one-off access groups and an optional
        # saved preset permit only the websites/apps the task needs.
        form = request.form
        topic = form["topic"].strip()
        project = form.get("project") or None
        agentic = form.get("agentic") == "on"
        try:
            selected_groups = _parse_allowed_groups(form)
        except ValueError as exc:
            log.warning("session start refused: %s", exc)
            return str(exc), 400
        with state.goal_access_lifecycle():
            started_at = get_now()
            try:
                replaced_goal_access = state.start_session(
                    topic,
                    now=started_at,
                    allowed_groups=selected_groups,
                    project=project,
                    agentic=agentic,
                )
            except ValueError as exc:
                # Browser constraints are UX only; reject forged values before
                # a hosts write, event, prompt, or spoken response.
                log.warning("session start refused: %s", exc)
                return str(exc), 400
            except RuntimeError as exc:
                # A late dashboard request cannot reverse terminal shutdown.
                log.info("session start unavailable: %s", exc)
                return str(exc), 503
            allowed_groups = list(state.work_allowed_groups)
            allowed_sites = list(access_site_keys(allowed_groups))
            allowed_apps = list(access_app_keys(allowed_groups))
            if replaced_goal_access is not None:
                state.cancel_pending_goal_access_start(replaced_goal_access)
                # The replacement good-luck message is sufficient spoken context.
                append_session_event(goal_access_event(
                    "goal_access_ended",
                    replaced_goal_access,
                    ended_at=started_at,
                    reason="session_replaced",
                ), "session-replacement-goal-access-end")
            append_session_event({
                "event": "session_start",
                "topic": topic,
                "project": state.active_project,
                "selected_groups": list(state.task_allowed_groups),
                "allowed_groups": allowed_groups,
                "allowed_group_labels": list(access_labels(allowed_groups)),
                # Preserve derived policy arrays for auditability without
                # making either split representation canonical.
                "selected_sites": list(
                    access_site_keys(state.task_allowed_groups)
                ),
                "selected_apps": list(
                    access_app_keys(state.task_allowed_groups)
                ),
                "allowed_sites": allowed_sites,
                "allowed_apps": allowed_apps,
                "agentic": state.agentic_mode,
            }, "session-start")
            save_state("session-start")            # topic history survives restart
            session_context = state.context_summary()
            queue_transition_feedback(
                state,
                "good_luck",
                topic=topic,
                session_context=session_context,
            )
            enforcement_error = reconcile_or_503("session-start")
            if enforcement_error is not None:
                return enforcement_error
            active_project = state.active_project
            task_groups = list(state.task_allowed_groups)
            active_agentic = state.agentic_mode
        goal_feedback.wake()
        log.info(
            "session started: topic=%r project=%r selected_groups=%s "
            "allowed_groups=%s allowed_sites=%s allowed_apps=%s agentic=%s",
            topic,
            active_project,
            task_groups,
            allowed_groups,
            allowed_sites,
            allowed_apps,
            active_agentic,
        )
        return redirect("/")

    @app.post("/goal-access")
    def start_goal_access():
        """Permit selected website/app groups for one monitored goal."""

        try:
            goal, allowed_groups, minutes = _parse_goal_access_form(request.form)
        except ValueError as exc:
            # HTML constraints are convenience only; forged requests must fail
            # before state, hosts, records, model calls, or speech can change.
            log.warning("goal access refused: %s", exc)
            return str(exc), 400

        with state.goal_access_lifecycle():
            started_at = get_now()
            try:
                access, reason = state.start_goal_access(
                    goal,
                    allowed_groups,
                    minutes,
                    now=started_at,
                )
            except ValueError as exc:
                # Keep this guard for non-HTTP state validation so route
                # behavior stays a clean 400 as validation grows stricter.
                log.warning("goal access refused: %s", exc)
                return str(exc), 400
            if access is None:
                log.info("goal access refused: %s", reason)
                return reason, 400

            append_session_event(goal_access_event(
                "goal_access_started",
                access,
            ), "goal-access-start")
            queue_goal_access_feedback(
                state,
                "goal_access_start",
                access,
                now=started_at,
            )
            enforcement_error = reconcile_or_503("goal-access-start")
            if enforcement_error is not None:
                return enforcement_error
        goal_feedback.wake()
        log.info(
            "goal access started: goal=%r groups=%s requested_minutes=%r "
            "expires_at=%s",
            access.goal,
            list(access.allowed_groups),
            access.requested_minutes,
            access.end_time.isoformat() if access.end_time else None,
        )
        return redirect("/")

    @app.post("/goal-access/stop")
    def stop_goal_access():
        """End the active grant early; stale repeated submissions are harmless."""

        with state.goal_access_lifecycle():
            stopped_at = get_now()
            access = state.stop_goal_access(now=stopped_at)
            if access is None:
                log.info("goal access stop ignored - no active grant")
                return redirect("/")

            state.cancel_pending_goal_access_start(access)
            append_session_event(goal_access_event(
                "goal_access_ended",
                access,
                ended_at=stopped_at,
                reason="manual",
            ), "goal-access-stop")
            queue_goal_access_feedback(
                state,
                "goal_access_end",
                access,
                now=stopped_at,
                reason="manual",
            )
            enforcement_error = reconcile_or_503("goal-access-stop")
            if enforcement_error is not None:
                return enforcement_error
        goal_feedback.wake()
        log.info(
            "goal access stopped: goal=%r groups=%s reason=manual",
            access.goal,
            list(access.allowed_groups),
        )
        return redirect("/")

    @app.post("/break")
    def take_break():
        # The break form shares the same repeated, server-validated group
        # contract as permanent task and temporary goal access.
        form = request.form
        try:
            allowed_groups = _parse_allowed_groups(form)
        except ValueError as exc:
            log.warning("break refused: %s", exc)
            return str(exc), 400
        minutes = int(form["minutes"])
        kind = form.get("kind", "away")
        with state.goal_access_lifecycle():
            try:
                ok, reason = state.start_break(
                    purpose=form["purpose"],
                    minutes=minutes,
                    kind=kind,
                    allowed_groups=allowed_groups,
                    now=get_now(),
                )
            except ValueError as exc:
                # State remains the validation boundary for programmatic
                # callers; preserve an explicit HTTP 400 for forged forms.
                log.warning("break refused: %s", exc)
                return str(exc), 400
            if not ok:                             # e.g. social cap exhausted
                log.info("break refused: %s", reason)
                return reason, 400
            append_session_event({
                "event": "break_start",
                "purpose": form["purpose"],
                "minutes": minutes,
                "kind": kind,
                "allowed_groups": list(allowed_groups),
                "allowed_group_labels": list(access_labels(allowed_groups)),
                "allowed_sites": list(access_site_keys(allowed_groups)),
                "allowed_apps": list(access_app_keys(allowed_groups)),
            }, "break-start")
            save_state("break-start")              # allowance survives restart
            session_context = state.context_summary()
            queue_transition_feedback(
                state,
                "break_ack",
                purpose=form["purpose"],
                minutes=form["minutes"],
                session_context=session_context,
            )
            enforcement_error = reconcile_or_503("break-start")
            if enforcement_error is not None:
                return enforcement_error
        goal_feedback.wake()
        return redirect("/")

    @app.post("/break/stop")
    def stop_break():
        # A state-changing form uses POST; redirecting afterward prevents a
        # browser refresh from presenting a resubmission prompt:
        # https://flask.palletsprojects.com/en/stable/quickstart/#redirects-and-errors
        with state.goal_access_lifecycle():
            stopped_at = get_now()
            result = state.stop_break(now=stopped_at)
            if result is None:
                # The watchdog can expire a break between the dashboard poll
                # and click. A harmless redirect avoids duplicate side effects.
                log.info("break stop ignored - no active break")
                return redirect("/")

            event = {
                "event": "break_stopped",
                "purpose": result.purpose,
                "kind": result.kind,
                "requested_minutes": result.requested_minutes,
                "elapsed_seconds": result.elapsed_seconds,
                "charged_minutes": result.charged_minutes,
                "refunded_minutes": result.refunded_minutes,
            }
            append_session_event(event, "break-stop")
            save_state("break-stop")               # persist any social refund
            session_context = state.context_summary(now=stopped_at)
            queue_transition_feedback(
                state,
                "break_end_ack",
                purpose=result.purpose,
                charged_minutes=result.charged_minutes,
                session_context=session_context,
            )
            enforcement_error = reconcile_or_503("break-stop")
            if enforcement_error is not None:
                return enforcement_error
        goal_feedback.wake()
        log.info(
            "break stopped - purpose=%r kind=%s elapsed_seconds=%d "
            "charged_minutes=%d refunded_minutes=%d; enforcement restored",
            result.purpose,
            result.kind,
            result.elapsed_seconds,
            result.charged_minutes,
            result.refunded_minutes,
        )
        return redirect("/")

    @app.post("/agentic")
    def toggle_agentic():
        # Mid-session toggle for agentic mode; re-apply blocking right away
        # (turning it OFF while the agent was busy must re-block instantly).
        with state.goal_access_lifecycle():
            state.set_agentic(request.form.get("enabled") == "on")
            append_session_event({
                "event": "agentic_toggle",
                "enabled": state.agentic_mode,
            }, "agentic-toggle")
            enforcement_error = reconcile_or_503("agentic-toggle")
            if enforcement_error is not None:
                return enforcement_error
        goal_feedback.wake()
        return redirect("/")

    @app.post("/verdict/correct")
    def correct_verdict():
        """Replace only the effective label of the expected latest verdict."""

        try:
            verdict_id, expected_revision, productive = (
                _parse_verdict_correction_form(request.form)
            )
        except ValueError as exc:
            log.warning("verdict correction refused: %s", exc)
            return str(exc), 400

        # The lifecycle coordinator orders the source verdict event before its
        # correction and prevents a session transition from splitting the
        # state/event/feedback publication sequence.
        with state.goal_access_lifecycle():
            changed_at = get_now()
            result = state.correct_latest_verdict(
                verdict_id,
                expected_revision,
                productive,
                now=changed_at,
            )
            if result is None:
                # RFC 9110 section 15.5.10 defines 409 for a command that no
                # longer matches the target resource's current state:
                # https://www.rfc-editor.org/rfc/rfc9110.html#name-409-conflict
                log.info(
                    "verdict correction conflicted: verdict_id=%r "
                    "expected_revision=%d productive=%s",
                    verdict_id,
                    expected_revision,
                    productive,
                )
                return (
                    "The latest verdict changed. Refresh the dashboard and "
                    "try again.",
                    409,
                )
            if not result.changed:
                # Retried POSTs that already reached their explicit desired
                # state are successful without duplicate events or speech.
                log.info(
                    "verdict correction already applied: verdict_id=%s "
                    "productive=%s",
                    result.verdict_id,
                    result.to_productive,
                )
                return redirect("/")

            append_session_event({
                "event": "verdict_corrected",
                "verdict_id": result.verdict_id,
                "evaluated_at": result.evaluated_at.isoformat(),
                "model_productive": result.model_productive,
                "from_productive": result.from_productive,
                "to_productive": result.to_productive,
                "credited_minutes": result.credited_minutes,
                "correction_revision": result.correction_revision,
                "changed_at": result.changed_at.isoformat(),
                "restored_model_verdict": result.restored_model_verdict,
                "streak_adjusted": result.streak_adjusted,
                "productive_streak_min": result.productive_streak_min,
            }, "verdict-correction")
            correction_action = (
                "restored the monitor's original verdict"
                if result.restored_model_verdict
                else "corrected the monitor"
            )
            queue_transition_feedback(
                state,
                "verdict_correction",
                waits_for_policy=False,
                correction_action=correction_action,
                from_label=_verdict_label(result.from_productive),
                to_label=_verdict_label(result.to_productive),
                session_context=state.context_summary(now=changed_at),
            )
            # Policy-independent feedback is already approved, but every
            # matching utterance still waits until prior JSONL events are
            # durable. The enforcer retry path releases it after recovery.
            if not getattr(store, "session_events_pending", False):
                state.release_goal_access_feedback()
        goal_feedback.wake()
        log.info(
            "verdict corrected: verdict_id=%s from=%s to=%s revision=%d "
            "streak_adjusted=%s productive_streak_min=%d",
            result.verdict_id,
            result.from_productive,
            result.to_productive,
            result.correction_revision,
            result.streak_adjusted,
            result.productive_streak_min,
        )
        # Carry the accepted identity/revision across the POST/redirect so the
        # freshly loaded page can announce this same-tab change exactly once.
        return redirect(url_for(
            "index",
            verdict_corrected=result.verdict_id,
            correction_revision=result.correction_revision,
        ))

    @app.post("/disable")
    def disable():
        # Requirement 6: exact confirmation phrase or a hard 403.
        with state.goal_access_lifecycle():
            disabled_at = get_now()
            ok, ended_goal_access = state.try_disable_with_goal_access(
                request.form.get("phrase", ""),
                now=disabled_at,
            )
            if not ok:
                return "Wrong confirmation phrase - enforcement stays on.", 403
            if ended_goal_access is not None:
                state.cancel_pending_goal_access_start(ended_goal_access)
                # Disable already supplies explicit context, so cleanup is
                # recorded without adding a second spoken transition.
                append_session_event(goal_access_event(
                    "goal_access_ended",
                    ended_goal_access,
                    ended_at=disabled_at,
                    reason="disabled",
                ), "disable-goal-access-end")
            append_session_event({"event": "disabled"}, "disable")
            enforcement_error = reconcile_or_503("disable")
            if enforcement_error is not None:
                return enforcement_error
        goal_feedback.wake()
        return redirect("/")

    @app.get("/status")
    def status():
        # Polled by index.html's JS every few seconds; also handy for curl.
        payload = build_status_payload(
            state,
            runtime_snapshot=get_runtime_snapshot,
            now=get_now(),
        )
        response = jsonify(payload)
        # Realtime status must never be reused from an intermediary cache:
        # https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Cache-Control
        response.headers["Cache-Control"] = "no-store"
        return response

    return app
