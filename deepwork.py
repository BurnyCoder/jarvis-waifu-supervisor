#!/usr/bin/env python3
"""Deep Work with Productivity Monitoring - Combines blocking and AI monitoring."""

import sys
import platform
import threading
import time

from deepwork import (
    CONFIRMATION_PHRASE,
    is_admin,
    run_as_admin,
    modify_hosts,
    kill_target_processes,
)
from productivity_monitor import (
    capture_all_stitched,
    parse_productivity_response,
    speak,
    PRODUCTIVITY_PROMPT_TEMPLATE,
    CAPTURE_INTERVAL_SECONDS,
    CAPTURES_BEFORE_ANALYSIS,
)
from capture_describer import SCREENSHOT_MODEL
from llm_api import complete_vision, is_local_model
from save_results import save_image, save_text, get_timestamp


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
            self.killer_thread.join(timeout=2.0)
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
            self.monitor_thread.join(timeout=2.0)
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

                    backend = "local Ollama" if is_local_model(SCREENSHOT_MODEL) else "OpenAI"
                    print(f"Sending to {backend} ({SCREENSHOT_MODEL})...")

                    analysis = complete_vision(
                        captured_images,
                        prompt=self.productivity_prompt,
                        model=SCREENSHOT_MODEL
                    )

                    print("\n" + "=" * 50)
                    print("PRODUCTIVITY ANALYSIS:")
                    print("=" * 50)
                    print(analysis)
                    print("=" * 50)

                    is_productive, reason = parse_productivity_response(analysis)
                    if not is_productive:
                        message = f"You are probably not being productive. {reason}"
                        print(f"\n[TTS] {message}")
                        speak(message)

                    text_path = save_text(analysis, f"productivity_analysis_{timestamp}")
                    print(f"Analysis saved to {text_path}")

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
            if self.break_cancel_event.is_set():
                return
            if remaining % 60 == 0 or remaining == 30 or remaining <= 10:
                mins, secs = divmod(remaining, 60)
                print(f"Break remaining: {mins:02d}:{secs:02d}")
            time.sleep(1)

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
    import os
    if not is_local_model(SCREENSHOT_MODEL) and not os.environ.get("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY environment variable not set.")
        print("Set it with: export OPENAI_API_KEY='your-api-key'")
        print("Or use local model: set SCREENSHOT_MODEL=gemma3:4b")
        sys.exit(1)

    # Ask what user wants to be doing
    print("What do you want to be doing? (e.g., 'coding a web app', 'studying Python')")
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
