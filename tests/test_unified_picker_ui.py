# Focused contract tests for the dashboard's shared access-group picker.
# Global context: these tests render the real Jinja template without constructing
# SessionState so UI regressions stay isolated from policy and route behavior.
# Flask rendering guidance: https://flask.palletsprojects.com/en/stable/templating/

import re
from pathlib import Path

from flask import Flask, render_template

from deepwork.access_policy import access_options


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "deepwork" / "webui" / "templates"
STATIC_DIR = ROOT / "deepwork" / "webui" / "static"

# Render the production catalog so this focused UI test cannot drift from the
# shared policy module it is meant to verify.
ACCESS_OPTIONS = access_options()


def _render_dashboard() -> str:
    """Render the production template with the smallest complete view model."""

    app = Flask(
        __name__,
        template_folder=str(TEMPLATE_DIR),
        static_folder=str(STATIC_DIR),
    )
    with app.test_request_context("/"):
        return render_template(
            "index.html",
            topics=(),
            mode="off",
            projects=(),
            access_options=ACCESS_OPTIONS,
            goal_access_active=False,
        )


def _form_body(html: str, action: str) -> str:
    """Return one non-nested form body selected by its exact POST action."""

    match = re.search(
        rf'<form\b[^>]*action="{re.escape(action)}"[^>]*>(.*?)</form>',
        html,
        flags=re.DOTALL,
    )
    assert match is not None, f"missing form for {action}"
    return match.group(1)


def test_all_access_forms_render_the_same_accessible_fourteen_choice_picker():
    """Every scope uses one semantic, repeated-value access-group control."""

    html = _render_dashboard()
    expected_values = [option.key for option in ACCESS_OPTIONS]

    for action, prefix in (
        ("/start", "task"),
        ("/goal-access", "goal"),
        ("/break", "break"),
    ):
        form = _form_body(html, action)
        assert "<fieldset" in form and "<legend>" in form
        assert f'aria-describedby="{prefix}-access-help"' in form
        assert f'id="{prefix}-access-help"' in form
        assert re.findall(r'name="allowed_groups" value="([^"]+)"', form) == (
            expected_values
        )
        ids = re.findall(
            r'<input\s+id="(' + prefix + r'-access-[^"]+)"\s+type="checkbox"',
            form,
        )
        assert len(ids) == len(ACCESS_OPTIONS) and len(set(ids)) == len(ids)
        assert all(f'for="{control_id}"' in form for control_id in ids)
        assert form.count('value="discord"') == 1
        assert form.count('class="access-capability"') == len(ACCESS_OPTIONS)
        assert "Web + App" in form and "App" in form and "Web" in form

    assert 'name="allowed_sites"' not in html
    assert 'name="allowed_apps"' not in html


def test_template_uses_one_macro_and_status_assets_use_unified_access_copy():
    """The shared renderer and live dashboard speak in access-group terms."""

    template = (TEMPLATE_DIR / "index.html").read_text(encoding="utf-8")
    script = (STATIC_DIR / "dashboard.js").read_text(encoding="utf-8")
    stylesheet = (STATIC_DIR / "dashboard.css").read_text(encoding="utf-8")

    assert template.count("{% macro access_picker(") == 1
    assert template.count("{{ access_picker(") == 3
    assert "<dt>Access groups</dt>" in template
    assert 'id="goal-access-groups"' in template

    assert "allowed_group_labels" in script
    assert "allowed_groups" in script
    assert "accessLabels" in script
    assert "`sites:" not in script and "`apps:" not in script
    assert "Task access groups remain available" in script
    assert "Temporary access goal" in script

    assert ".access-choice-field" in stylesheet
    assert ".access-choice-grid" in stylesheet
    assert ".access-capability" in stylesheet
    assert "@media (max-width: 480px)" in stylesheet


def test_latest_verdict_gets_one_native_idempotent_correction_form():
    """Only the newest verdict submits its identity, revision, and new label."""

    script = (STATIC_DIR / "dashboard.js").read_text(encoding="utf-8")

    # A real form preserves keyboard/browser behavior and keeps POST as the
    # server-side mutation boundary:
    # https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/form
    assert 'form.method = "post"' in script
    assert 'form.action = "/verdict/correct"' in script
    assert 'createHiddenInput("verdict_id", item.verdict_id)' in script
    assert (
        'createHiddenInput("expected_revision", correction.revision)' in script
    )
    assert 'createHiddenInput("productive", correction.desiredProductive)' in script
    assert "index === 0 && item.verdict_id" in script
    assert "Actually productive" in script
    assert "Actually off track" in script
    assert "Restore model verdict" in script


def test_corrected_verdict_keeps_the_model_judgment_visible_and_text_safe():
    """An override changes the effective badge without rewriting model evidence."""

    script = (STATIC_DIR / "dashboard.js").read_text(encoding="utf-8")

    assert "model_productive" in script
    assert "Corrected by you" in script
    assert "Original model verdict" in script
    assert "Original model explanation" in script
    assert "reason.textContent" in script
    assert ".innerHTML" not in script
    # Dashboard totals must use the effective user-overridable classification.
    assert "history.filter((item) => item.productive).length" in script


def test_corrections_update_runtime_copy_and_the_polite_live_announcement():
    """Polling and POST redirects both announce the effective same-ID edit."""

    script = (STATIC_DIR / "dashboard.js").read_text(encoding="utf-8")

    assert "result.verdict_id" in script
    assert "corrected from" in script
    assert "correction_revision" in script
    assert "Productivity evaluation corrected" in script
    assert '"dashboard-announcement"' in script
    assert 'initialQuery.get("verdict_corrected")' in script
    assert "redirectedCorrectionMatches" in script
    assert "clearCorrectionAnnouncementQuery" in script
    assert "window.history.replaceState" in script


def test_verdict_correction_controls_are_compact_and_responsive():
    """Correction metadata and its action remain readable on narrow screens."""

    stylesheet = (STATIC_DIR / "dashboard.css").read_text(encoding="utf-8")

    assert ".verdict-correction" in stylesheet
    assert ".verdict-correction-marker" in stylesheet
    assert ".verdict-correction-form" in stylesheet
    assert ".verdict-correction-button" in stylesheet
    correction_button = stylesheet[
        stylesheet.index(".verdict-correction-button"):
    ]
    assert "min-height: 2.75rem" in correction_button
    reason_label = stylesheet[stylesheet.index(".verdict-reason-label"):
                              stylesheet.index(".verdict-correction {")]
    assert "color: var(--muted)" in reason_label
    mobile = stylesheet[stylesheet.index("@media (max-width: 480px)"):]
    assert ".verdict-correction-form" in mobile
    assert ".verdict-correction-button" in mobile
