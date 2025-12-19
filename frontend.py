#!/usr/bin/env python3
"""Web frontend for Deep Work with Productivity Monitoring."""

import logging
from flask import Flask, render_template_string, jsonify, request

from core import (
    CONFIRMATION_PHRASE,
    SCREENSHOT_MODEL,
    CAPTURE_INTERVAL_SECONDS,
    CAPTURES_BEFORE_ANALYSIS,
    FRONTEND_HTML,
    DeepWorkWithMonitoring,
)

app = Flask(__name__)
logging.getLogger('werkzeug').setLevel(logging.ERROR)

# Global state
state: DeepWorkWithMonitoring | None = None
task: str = ""


@app.route('/')
def index():
    return render_template_string(FRONTEND_HTML, task=task, phrase=CONFIRMATION_PHRASE)


@app.route('/status')
def get_status():
    return jsonify({
        "mode": state.current_mode if state else "off",
        "task": task,
        "last_analysis": state.last_analysis if state else "",
        "is_productive": state.is_productive if state else True,
        "break_remaining": state.break_remaining if state else 0,
    })


@app.route('/set_mode', methods=['POST'])
def set_mode():
    global state, task
    data = request.json
    mode = data.get('mode', 'off')
    new_task = data.get('task', task)
    minutes = data.get('minutes', 5)

    # Recreate state if task changed
    if state is None or state.task != new_task:
        if state:
            state.cleanup()
        state = DeepWorkWithMonitoring(new_task)
    task = new_task

    if mode == 'on':
        state.set_on()
    elif mode == 'off':
        state.set_off()
    elif mode == 'break':
        state.set_break(minutes)

    return jsonify({"status": "ok", "mode": state.current_mode})


if __name__ == '__main__':
    print("Starting Deep Work Frontend...")
    print(f"Model: {SCREENSHOT_MODEL}")
    print(f"Capture interval: {CAPTURE_INTERVAL_SECONDS}s")
    print(f"Captures before analysis: {CAPTURES_BEFORE_ANALYSIS}")
    print("\nOpen http://localhost:5000 in your browser")
    app.run(host='0.0.0.0', port=5000, debug=False)
