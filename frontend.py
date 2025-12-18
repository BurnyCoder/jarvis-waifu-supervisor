#!/usr/bin/env python3
"""Simple web frontend for Deep Work with Productivity Monitoring."""

import os
import sys
import threading
from flask import Flask, render_template_string, jsonify, request

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from blocking import (
    CONFIRMATION_PHRASE,
    modify_hosts,
    kill_target_processes,
)
from productivity_monitor import (
    capture_all_stitched,
    parse_productivity_response,
    PRODUCTIVITY_PROMPT_TEMPLATE,
    CAPTURE_INTERVAL_SECONDS,
    CAPTURES_BEFORE_ANALYSIS,
)
from capture_describer import SCREENSHOT_MODEL
from llm_api import complete_vision, is_local_model
from save_results import save_image, save_text, get_timestamp

app = Flask(__name__)

# Global state
state = {
    "mode": "off",
    "task": "coding or learning",
    "last_analysis": "",
    "is_productive": True,
    "monitor_thread": None,
    "killer_thread": None,
    "stop_event": threading.Event(),
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
                    status.textContent = data.mode.toUpperCase();
                    status.className = 'status ' + data.mode;

                    const analysis = document.getElementById('analysis');
                    if (data.last_analysis) {
                        analysis.textContent = data.last_analysis;
                        analysis.className = 'analysis ' + (data.is_productive ? 'productive' : 'not-productive');
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

        // Update every 5 seconds
        setInterval(updateStatus, 5000);
        updateStatus();
    </script>
</body>
</html>
"""


def killer_loop():
    """Continuously kill target processes."""
    while not state["stop_event"].is_set():
        kill_target_processes()
        state["stop_event"].wait(timeout=1.0)


def monitor_loop():
    """Productivity monitoring loop."""
    captured_images = []
    productivity_prompt = PRODUCTIVITY_PROMPT_TEMPLATE.format(task=state["task"])

    while not state["stop_event"].is_set():
        try:
            if state["mode"] != "on":
                state["stop_event"].wait(timeout=1.0)
                continue

            stitched_image = capture_all_stitched()
            captured_images.append(stitched_image)

            timestamp = get_timestamp()
            save_image(stitched_image, f"productivity_{timestamp}")

            if len(captured_images) >= CAPTURES_BEFORE_ANALYSIS:
                analysis = complete_vision(
                    captured_images,
                    prompt=productivity_prompt,
                    model=SCREENSHOT_MODEL
                )

                is_productive, reason = parse_productivity_response(analysis)
                state["last_analysis"] = analysis
                state["is_productive"] = is_productive

                save_text(analysis, f"productivity_analysis_{timestamp}")
                captured_images = []

            for _ in range(int(CAPTURE_INTERVAL_SECONDS * 10)):
                if state["stop_event"].is_set() or state["mode"] != "on":
                    break
                state["stop_event"].wait(timeout=0.1)

        except Exception as e:
            print(f"Monitor error: {e}")
            state["stop_event"].wait(timeout=CAPTURE_INTERVAL_SECONDS)


def start_threads():
    """Start killer and monitor threads."""
    state["stop_event"].clear()

    if state["killer_thread"] is None or not state["killer_thread"].is_alive():
        state["killer_thread"] = threading.Thread(target=killer_loop, daemon=True)
        state["killer_thread"].start()

    if state["monitor_thread"] is None or not state["monitor_thread"].is_alive():
        state["monitor_thread"] = threading.Thread(target=monitor_loop, daemon=True)
        state["monitor_thread"].start()


def stop_threads():
    """Stop all threads."""
    state["stop_event"].set()


@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE, task=state["task"], phrase=CONFIRMATION_PHRASE)


@app.route('/status')
def get_status():
    return jsonify({
        "mode": state["mode"],
        "task": state["task"],
        "last_analysis": state["last_analysis"],
        "is_productive": state["is_productive"],
    })


@app.route('/set_mode', methods=['POST'])
def set_mode():
    data = request.json
    mode = data.get('mode', 'off')
    task = data.get('task', state["task"])
    minutes = data.get('minutes', 5)

    state["task"] = task

    if mode == 'on':
        state["mode"] = "on"
        modify_hosts(block=True)
        start_threads()

    elif mode == 'off':
        state["mode"] = "off"
        stop_threads()
        modify_hosts(block=False)

    elif mode == 'break':
        state["mode"] = "break"
        stop_threads()
        modify_hosts(block=False)

        # Start break timer
        def break_timer():
            import time
            time.sleep(minutes * 60)
            if state["mode"] == "break":
                state["mode"] = "on"
                modify_hosts(block=True)
                start_threads()

        threading.Thread(target=break_timer, daemon=True).start()

    return jsonify({"status": "ok", "mode": state["mode"]})


if __name__ == '__main__':
    print("Starting Deep Work Frontend...")
    print(f"Model: {SCREENSHOT_MODEL}")
    print(f"Capture interval: {CAPTURE_INTERVAL_SECONDS}s")
    print(f"Captures before analysis: {CAPTURES_BEFORE_ANALYSIS}")
    print("\nOpen http://localhost:5000 in your browser")
    app.run(host='0.0.0.0', port=5000, debug=False)
