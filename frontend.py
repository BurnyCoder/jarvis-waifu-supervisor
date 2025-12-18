#!/usr/bin/env python3
"""Simple web frontend for Deep Work with Productivity Monitoring."""

import logging
import os
import sys
from flask import Flask, render_template_string, jsonify, request

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from blocking import CONFIRMATION_PHRASE, modify_hosts
from deepwork_monitor import DeepWorkWithMonitoring
from productivity_monitor import CAPTURE_INTERVAL_SECONDS, CAPTURES_BEFORE_ANALYSIS, GOOD_JOB_INTERVAL_MINUTES
import time
from capture_describer import SCREENSHOT_MODEL

app = Flask(__name__)

# Disable Flask request logging
logging.getLogger('werkzeug').setLevel(logging.ERROR)

# Global state
state = None  # DeepWorkWithMonitoring instance
web_state = {
    "mode": "off",
    "task": "coding or learning",
    "last_analysis": "",
    "is_productive": True,
}

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Deep Work Monitor</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1a1a2e;
            color: #eee;
            min-height: 100vh;
            padding: 20px;
        }
        .container { max-width: 600px; margin: 0 auto; }
        h1 { text-align: center; margin-bottom: 30px; color: #00d4ff; }

        .status {
            text-align: center;
            padding: 30px;
            border-radius: 15px;
            margin-bottom: 20px;
            font-size: 24px;
            font-weight: bold;
        }
        .status.on { background: #2d5a27; }
        .status.off { background: #5a2727; }
        .status.break { background: #5a4a27; }

        .task-input {
            width: 100%;
            padding: 15px;
            font-size: 16px;
            border: none;
            border-radius: 10px;
            margin-bottom: 20px;
            background: #16213e;
            color: #eee;
        }

        .buttons {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
        }
        .btn {
            flex: 1;
            padding: 20px;
            font-size: 18px;
            border: none;
            border-radius: 10px;
            cursor: pointer;
            transition: transform 0.1s;
        }
        .btn:hover { transform: scale(1.02); }
        .btn:active { transform: scale(0.98); }
        .btn-on { background: #27ae60; color: white; }
        .btn-off { background: #e74c3c; color: white; }
        .btn-break { background: #f39c12; color: white; }

        .analysis {
            background: #16213e;
            padding: 20px;
            border-radius: 10px;
            white-space: pre-wrap;
            font-family: monospace;
            font-size: 14px;
            max-height: 300px;
            overflow-y: auto;
        }

        .productive { border-left: 4px solid #27ae60; }
        .not-productive { border-left: 4px solid #e74c3c; }

        .confirmation {
            display: none;
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0,0,0,0.8);
            justify-content: center;
            align-items: center;
        }
        .confirmation.show { display: flex; }
        .confirmation-box {
            background: #16213e;
            padding: 30px;
            border-radius: 15px;
            text-align: center;
        }
        .confirmation-box input {
            width: 100%;
            padding: 10px;
            margin: 15px 0;
            font-size: 16px;
            border: none;
            border-radius: 5px;
        }
        .confirmation-box button {
            padding: 10px 30px;
            margin: 5px;
            border: none;
            border-radius: 5px;
            cursor: pointer;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🧠 Deep Work Monitor</h1>

        <div class="status" id="status">OFF</div>

        <input type="text" class="task-input" id="task" placeholder="What do you want to be doing? (e.g., 'learn quantum physics')" value="{{ task }}">

        <div class="buttons">
            <button class="btn btn-on" onclick="setMode('on')">ON</button>
            <button class="btn btn-break" onclick="promptBreak()">BREAK</button>
            <button class="btn btn-off" onclick="promptOff()">OFF</button>
        </div>

        <div id="goodJobTimer" style="text-align: center; margin-bottom: 15px; color: #888;"></div>

        <h3 style="margin-bottom: 10px;">Last Analysis:</h3>
        <div class="analysis" id="analysis">No analysis yet...</div>
    </div>

    <div class="confirmation" id="confirmDialog">
        <div class="confirmation-box">
            <p>Type the confirmation phrase:</p>
            <p><strong>{{ phrase }}</strong></p>
            <input type="text" id="confirmInput" placeholder="Type phrase here...">
            <div>
                <button onclick="confirmAction()">Confirm</button>
                <button onclick="cancelConfirm()">Cancel</button>
            </div>
        </div>
    </div>

    <script>
        const PHRASE = "{{ phrase }}";
        let pendingAction = null;

        function updateStatus() {
            fetch('/status')
                .then(r => r.json())
                .then(data => {
                    const status = document.getElementById('status');
                    let statusText = data.mode.toUpperCase();
                    if (data.mode === 'break' && data.break_remaining > 0) {
                        const mins = Math.floor(data.break_remaining / 60);
                        const secs = data.break_remaining % 60;
                        statusText += ` (${mins}:${secs.toString().padStart(2, '0')})`;
                    }
                    status.textContent = statusText;
                    status.className = 'status ' + data.mode;

                    const analysis = document.getElementById('analysis');
                    if (data.last_analysis) {
                        // Try to parse and format JSON nicely
                        let displayText = data.last_analysis;
                        try {
                            const jsonStart = data.last_analysis.indexOf('{');
                            const jsonEnd = data.last_analysis.lastIndexOf('}') + 1;
                            if (jsonStart !== -1 && jsonEnd > jsonStart) {
                                const jsonStr = data.last_analysis.substring(jsonStart, jsonEnd);
                                const parsed = JSON.parse(jsonStr);
                                displayText = `Productive: ${parsed.productive}\\n\\nReason: ${parsed.reason}`;
                            }
                        } catch (e) {}
                        analysis.textContent = displayText;
                        analysis.className = 'analysis ' + (data.is_productive ? 'productive' : 'not-productive');
                    }

                    // Update good job timer
                    const goodJobTimer = document.getElementById('goodJobTimer');
                    if (data.mode === 'on' && data.is_productive && data.good_job_remaining > 0) {
                        const mins = Math.floor(data.good_job_remaining / 60);
                        const secs = data.good_job_remaining % 60;
                        goodJobTimer.textContent = `Next encouragement in ${mins}:${secs.toString().padStart(2, '0')}`;
                    } else {
                        goodJobTimer.textContent = '';
                    }
                });
        }

        function setMode(mode, minutes) {
            const task = document.getElementById('task').value;
            fetch('/set_mode', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({mode, task, minutes})
            }).then(updateStatus);
        }

        function promptOff() {
            pendingAction = () => setMode('off');
            document.getElementById('confirmDialog').classList.add('show');
            document.getElementById('confirmInput').value = '';
            document.getElementById('confirmInput').focus();
        }

        function promptBreak() {
            const minutes = prompt('Break duration in minutes:', '5');
            if (minutes && !isNaN(minutes) && parseFloat(minutes) > 0) {
                pendingAction = () => setMode('break', parseFloat(minutes));
                document.getElementById('confirmDialog').classList.add('show');
                document.getElementById('confirmInput').value = '';
                document.getElementById('confirmInput').focus();
            }
        }

        function confirmAction() {
            const input = document.getElementById('confirmInput').value.trim();
            if (input === PHRASE && pendingAction) {
                pendingAction();
                pendingAction = null;
            } else {
                alert('Incorrect phrase!');
            }
            document.getElementById('confirmDialog').classList.remove('show');
        }

        function cancelConfirm() {
            pendingAction = null;
            document.getElementById('confirmDialog').classList.remove('show');
        }

        // Update every second for break countdown, otherwise every 5 seconds
        setInterval(updateStatus, 1000);
        updateStatus();
    </script>
</body>
</html>
"""


@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE, task=web_state["task"], phrase=CONFIRMATION_PHRASE)


@app.route('/status')
def get_status():
    global state
    mode = state.current_mode if state else "off"
    break_remaining = state.break_remaining if state else 0
    last_analysis = state.last_analysis if state else ""
    is_productive = state.is_productive if state else True

    # Calculate seconds until next "good job"
    good_job_remaining = 0
    if state and is_productive:
        elapsed = time.time() - state.last_good_job_time
        good_job_remaining = max(0, int(GOOD_JOB_INTERVAL_MINUTES * 60 - elapsed))

    return jsonify({
        "mode": mode,
        "task": web_state["task"],
        "last_analysis": last_analysis,
        "is_productive": is_productive,
        "break_remaining": break_remaining,
        "good_job_remaining": good_job_remaining,
    })


@app.route('/set_mode', methods=['POST'])
def set_mode():
    global state
    data = request.json
    mode = data.get('mode', 'off')
    task = data.get('task', web_state["task"])
    minutes = data.get('minutes', 5)

    web_state["task"] = task

    # Create new state if task changed or doesn't exist
    if state is None or state.task != task:
        if state:
            state.cancel_break()
            state.stop_killer()
            state.stop_monitor()
        state = DeepWorkWithMonitoring(task)

    if mode == 'on':
        state.cancel_break()
        modify_hosts(block=True)
        state.start_killer()
        state.start_monitor()
        state.current_mode = "on"

    elif mode == 'off':
        state.cancel_break()
        state.stop_killer()
        state.stop_monitor()
        modify_hosts(block=False)
        state.current_mode = "off"

    elif mode == 'break':
        state.cancel_break()
        state.stop_killer()
        state.stop_monitor()
        modify_hosts(block=False)
        state.current_mode = "break"
        state.start_break(minutes)

    return jsonify({"status": "ok", "mode": state.current_mode})


if __name__ == '__main__':
    print("Starting Deep Work Frontend...")
    print(f"Model: {SCREENSHOT_MODEL}")
    print(f"Capture interval: {CAPTURE_INTERVAL_SECONDS}s")
    print(f"Captures before analysis: {CAPTURES_BEFORE_ANALYSIS}")
    print("\nOpen http://localhost:5000 in your browser")
    app.run(host='0.0.0.0', port=5000, debug=False)
