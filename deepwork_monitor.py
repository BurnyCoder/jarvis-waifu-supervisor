#!/usr/bin/env python3
"""Deep Work with Productivity Monitoring - Combines blocking and AI monitoring."""

import os
import sys
import platform
import threading
import time

from blocking import (
    CONFIRMATION_PHRASE,
    is_admin,
    run_as_admin,
    modify_hosts,
    kill_target_processes,
)
from deepwork.monitoring import (
    capture_all_stitched,
    analyze_captures,
    speak_result,
    save_analysis,
)
from capture_describer import SCREENSHOT_MODEL
from llm_api import is_local_model
from save_results import save_image, get_timestamp

# Monitoring configuration via environment variables
CAPTURE_INTERVAL_SECONDS = float(os.environ.get("CAPTURE_INTERVAL_SECONDS", "5"))
CAPTURES_BEFORE_ANALYSIS = int(os.environ.get("CAPTURES_BEFORE_ANALYSIS", "3"))
# CAPTURE_INTERVAL_SECONDS = float(os.environ.get("CAPTURE_INTERVAL_SECONDS", "60"))
# CAPTURES_BEFORE_ANALYSIS = int(os.environ.get("CAPTURES_BEFORE_ANALYSIS", "5"))

PRODUCTIVITY_PROMPT_TEMPLATE = """The user said they want to be doing: {task}

Analyze if the user is productive on their stated task by comparing the screenshots over time.

## Task-Specific Indicators

**Coding / Building an app / Chatbot development:**
- Look for: Code changes between screenshots, new lines written, cursor position changes, different files opened, terminal output changes
- AI-assisted coding (Claude Code, Cursor, Copilot, etc.): User giving prompts, AI generating/modifying code, reviewing AI output, accepting/rejecting changes - this IS productive even if user isn't typing code themselves
- NOT productive if: IDE shows identical code/files in all screenshots, no visible typing or changes, AND no AI agent activity

**Training a model / ML work:**
- Look for: Training logs progressing, loss values changing, new epochs starting, Jupyter notebook cells being executed, TensorBoard graphs updating, GPU utilization visible
- NOT productive if: Training logs are static, notebook cells unchanged, no progress in metrics

**Debugging:**
- Look for: Breakpoints hit, variable inspector changes, stepping through code, console output changes, error messages being investigated, stack traces being examined
- AI-assisted debugging: Pasting errors to AI, AI analyzing code, discussing fixes with Claude/ChatGPT - this IS productive
- NOT productive if: Debugger paused on same line in all screenshots, no investigation happening, no AI conversation about the issue

**Learning / Studying (physics, math, courses, etc.):**
- Look for: Video playing (progress bar moving), page scrolling in textbook/PDF, notes being taken, slides advancing, practice problems being worked on
- AI-assisted learning: Asking Claude/ChatGPT to explain concepts, working through problems together, AI tutoring - this IS productive
- Physical notebook/exercise book: If user is looking DOWN at desk (not at phone) and appears to be writing, they may be doing math exercises on paper - this IS productive. Look for pen/pencil in hand, writing posture, textbook or problem set visible on screen
- NOT productive if: Video paused (same frame), same page/slide visible throughout, no note-taking activity, no AI conversation, AND user not engaged with physical materials

**Note-taking / Obsidian vault / Documentation:**
- Look for: New text being written, links being created, files being organized, markdown being edited, graph view changes, new notes created
- NOT productive if: Same note open with no changes, just browsing without editing

**Reading / Research:**
- Look for: Page scrolling, tab changes, highlighting or annotations, switching between sources, notes being taken alongside
- NOT productive if: Same page visible throughout, no scrolling or interaction

## Important Exception
- Background audio/podcasts on YouTube are OK if user is still working (code changing, notes being taken, etc.) - this helps some people focus
- Only flag YouTube as unproductive if user is WATCHING it (video in focus, no work progress visible)

## Universal Red Flags (Always NOT productive)
- User looking down in webcam (likely on phone)
- Screen unchanged across ALL screenshots AND user not engaged with AI tools
- Actively watching entertainment (social media feed scrolling, games, YouTube video in focus with no work happening)
- Browser showing distraction sites instead of work-related content with no work progress

## Response Format
Respond with JSON containing "productive" (yes/no) and "reason".

Keep your reason to 2 short sentences maximum.

**When productive:** Start your reason with encouraging phrases like "Good job!", "Nice work!", "Great progress!", or "Keep it up!" followed by a specific observation about what you see them accomplishing on their task.

**When NOT productive:** Start your reason with gentle phrases like "Hey, I noticed...", "It looks like you might be...", or "I'm not seeing much progress..." followed by what you observed. Be uncertain and non-judgmental - they might just be thinking or taking a needed break.

Address the user directly with "you" and reference their stated task to make it personal.

Examples:
{{"productive": "yes", "reason": "Nice progress on your chatbot app! I see you added a new function and the tests are running in the terminal. Keep it up!"}}
{{"productive": "yes", "reason": "Good work on your quantum physics notes! You added a new section about wave functions in Obsidian. Stay focused!"}}
{{"productive": "yes", "reason": "Great learning session! The MIT lecture moved from 12:30 to 15:45 and you're looking at the screen taking it in."}}
{{"productive": "yes", "reason": "Solid progress on your AI agent! Claude Code generated a new API endpoint and you're reviewing the diff. Nice teamwork!"}}
{{"productive": "no", "reason": "Hey, I noticed your IDE looks the same in all screenshots. Maybe you got distracted or are stuck on something?"}}
{{"productive": "no", "reason": "It looks like you might be checking your phone? I can't see much progress on the screen."}}
{{"productive": "no", "reason": "The video seems paused - maybe you're taking a break or got sidetracked?"}}"""


def prompt_confirmation(phrase, action_name):
    """Prompt user to type a confirmation phrase. Returns True if confirmed, False otherwise."""
    try:
        confirm_input = input(f"Please type the following phrase exactly to confirm: '{phrase}'\nEnter phrase: ")
    except EOFError:
        print(f"\nEOF received during confirmation, cancelling {action_name}.")
        return False

    if confirm_input.strip() != phrase:
        print(f"Confirmation failed. {action_name.capitalize()} cancelled.")
        return False
    return True


class DeepWorkWithMonitoring:
    """Deep work state with integrated productivity monitoring."""

    def __init__(self, task: str):
        self.task = task
        self.productivity_prompt = PRODUCTIVITY_PROMPT_TEMPLATE.format(task=task)
        self.current_mode = "on"
        self.break_remaining = 0  # seconds remaining in break
        self.last_analysis = ""  # last productivity analysis
        self.is_productive = True  # last productivity status
        # self.last_good_job_time = time.time()  # for tracking good job countdown
        self.lock = threading.Lock()
        self.killer_stop_event = threading.Event()
        self.break_cancel_event = threading.Event()
        self.monitor_stop_event = threading.Event()
        self.killer_thread = None
        self.break_thread = None
        self.monitor_thread = None

    def start_killer(self):
        """Start the process killer thread."""
        with self.lock:
            if self.killer_thread is not None and self.killer_thread.is_alive():
                return
            self.killer_stop_event.clear()
            self.killer_thread = threading.Thread(target=self._killer_loop, daemon=True)
            self.killer_thread.start()
            print("Process killer started.")

    def stop_killer(self):
        """Stop the process killer thread."""
        with self.lock:
            if self.killer_thread is None or not self.killer_thread.is_alive():
                return
            self.killer_stop_event.set()
        self.killer_thread.join(timeout=5.0)
        with self.lock:
            self.killer_thread = None
        print("Process killer stopped.")

    def _killer_loop(self):
        """Continuously kill target processes."""
        while not self.killer_stop_event.is_set():
            kill_target_processes()
            self.killer_stop_event.wait(timeout=1.0)

    def start_monitor(self):
        """Start the productivity monitor thread."""
        with self.lock:
            if self.monitor_thread is not None and self.monitor_thread.is_alive():
                return
            self.monitor_stop_event.clear()
            self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self.monitor_thread.start()
            print("Productivity monitor started.")

    def stop_monitor(self):
        """Stop the productivity monitor thread."""
        with self.lock:
            if self.monitor_thread is None or not self.monitor_thread.is_alive():
                return
            self.monitor_stop_event.set()
        # Join outside lock to avoid deadlock
        self.monitor_thread.join(timeout=5.0)
        with self.lock:
            self.monitor_thread = None
        print("Productivity monitor stopped.")

    def _monitor_loop(self):
        """Productivity monitoring loop."""
        captured_images = []

        while not self.monitor_stop_event.is_set():
            try:
                timestamp = get_timestamp()
                print(f"\n[{timestamp}] Capturing...")

                stitched_image = capture_all_stitched()
                captured_images.append(stitched_image)

                image_path = save_image(stitched_image, f"productivity_{timestamp}")
                print(f"Saved to {image_path}")
                print(f"Captured {len(captured_images)}/{CAPTURES_BEFORE_ANALYSIS}")

                if len(captured_images) >= CAPTURES_BEFORE_ANALYSIS:
                    print(f"\nAnalyzing {len(captured_images)} captures...")

                    is_productive, reason, analysis = analyze_captures(
                        captured_images, self.productivity_prompt
                    )
                    self.last_analysis = analysis
                    self.is_productive = is_productive

                    speak_result(is_productive, reason)
                    save_analysis(self.productivity_prompt, analysis)

                    captured_images = []

                # Wait for next capture, checking stop event frequently
                for _ in range(int(CAPTURE_INTERVAL_SECONDS * 10)):
                    if self.monitor_stop_event.is_set():
                        return
                    time.sleep(0.1)

            except Exception as e:
                print(f"Monitor error: {e}")
                time.sleep(CAPTURE_INTERVAL_SECONDS)

    def start_break(self, minutes):
        """Start a timed break."""
        with self.lock:
            self.break_cancel_event.clear()
            self.break_thread = threading.Thread(
                target=self._break_timer, args=(minutes,), daemon=True
            )
            self.break_thread.start()

    def cancel_break(self):
        """Cancel the current break."""
        with self.lock:
            if self.break_thread is not None and self.break_thread.is_alive():
                self.break_cancel_event.set()
                self.break_thread.join(timeout=2.0)
                print("Break cancelled.")

    def _break_timer(self, minutes):
        """Break timer that auto-restores blocking when done."""
        total_seconds = int(minutes * 60)
        print(f"Break timer: {minutes} minute(s)")

        for remaining in range(total_seconds, 0, -1):
            self.break_remaining = remaining
            if self.break_cancel_event.is_set():
                self.break_remaining = 0
                return
            if remaining % 60 == 0 or remaining == 30 or remaining <= 10:
                mins, secs = divmod(remaining, 60)
                print(f"Break remaining: {mins:02d}:{secs:02d}")
            time.sleep(1)
        self.break_remaining = 0

        if not self.break_cancel_event.is_set():
            print("\n*** BREAK OVER - Re-enabling blocks and monitoring ***")
            with self.lock:
                self.current_mode = "on"
            modify_hosts(block=True)
            self.start_killer()
            self.start_monitor()
            print("Type 'off' or 'break <min>' to disable again.\n")


def main():
    if platform.system() != "Windows":
        print("Error: This script is designed for Windows only.")
        sys.exit(1)

    if not is_admin():
        print("Administrator privileges required. Requesting elevation...")
        run_as_admin()

    # Check API key
    if not is_local_model(SCREENSHOT_MODEL) and not os.environ.get("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY environment variable not set.")
        print("Set it with: export OPENAI_API_KEY='your-api-key'")
        print("Or use local model: set SCREENSHOT_MODEL=gemma3:4b")
        sys.exit(1)

    # Ask what user wants to be doing
    print("What do you want to be doing? (e.g., 'learn quantum physics', 'learn AI', 'research new architecture', 'train a model')")
    task = input("> ").strip()
    if not task:
        task = "coding or learning"

    state = DeepWorkWithMonitoring(task)

    print(f"\n--- Initializing: Task = {task} ---")
    print("--- Ensuring system is in 'on' mode ---")
    modify_hosts(block=True)
    state.start_killer()
    state.start_monitor()

    print(f"\nCapture interval: {CAPTURE_INTERVAL_SECONDS} seconds")
    print(f"Captures before analysis: {CAPTURES_BEFORE_ANALYSIS}")
    print(f"Model: {SCREENSHOT_MODEL}")
    print("\n--- Deep Work with Monitoring - Interactive Mode ---")
    print("Commands: on | off | break <min> | exit\n")

    try:
        while True:
            try:
                user_input = input(f"[{state.current_mode}] > ").strip().lower()
            except EOFError:
                user_input = "exit"

            if user_input == "on":
                if state.current_mode == "on":
                    print("Already in 'on' mode.")
                    continue
                state.cancel_break()
                modify_hosts(block=True)
                state.start_killer()
                state.start_monitor()
                state.current_mode = "on"
                print("--- Block mode + monitoring activated ---")

            elif user_input == "off":
                if state.current_mode == "off":
                    print("Already in 'off' mode.")
                    continue
                if not prompt_confirmation(CONFIRMATION_PHRASE, "'off' switch"):
                    continue
                state.cancel_break()
                state.stop_killer()
                state.stop_monitor()
                modify_hosts(block=False)
                state.current_mode = "off"
                print("--- Unblock mode activated (monitoring stopped) ---")

            elif user_input.startswith("break"):
                parts = user_input.split()
                if len(parts) != 2:
                    print("Usage: break <minutes>")
                    continue
                try:
                    minutes = float(parts[1])
                    if minutes <= 0:
                        print("Duration must be positive.")
                        continue
                except ValueError:
                    print(f"Invalid duration: {parts[1]}")
                    continue

                if not prompt_confirmation(CONFIRMATION_PHRASE, "break"):
                    continue

                state.cancel_break()
                state.stop_killer()
                state.stop_monitor()
                modify_hosts(block=False)
                state.current_mode = "break"
                state.start_break(minutes)
                print(f"--- Break mode: {minutes} min (monitoring paused) ---")

            elif user_input == "exit":
                print("Exiting...")
                state.cancel_break()
                state.stop_killer()
                state.stop_monitor()
                modify_hosts(block=False)
                break

            elif user_input:
                print("Commands: on | off | break <min> | exit")

    except KeyboardInterrupt:
        print("\nCtrl+C - Exiting...")
        state.cancel_break()
        state.stop_killer()
        state.stop_monitor()
        modify_hosts(block=False)

    print("Done.")


if __name__ == "__main__":
    main()
