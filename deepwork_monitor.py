#!/usr/bin/env python3
"""CLI interface for Deep Work with Productivity Monitoring."""

import os
import sys
import platform

from core import (
    CONFIRMATION_PHRASE,
    SCREENSHOT_MODEL,
    CAPTURE_INTERVAL_SECONDS,
    CAPTURES_BEFORE_ANALYSIS,
    is_admin,
    run_as_admin,
    prompt_confirmation,
    is_local_model,
    DeepWorkWithMonitoring,
)


def main():
    if platform.system() != "Windows":
        print("Error: This script is designed for Windows only.")
        sys.exit(1)

    if not is_admin():
        print("Administrator privileges required. Requesting elevation...")
        run_as_admin()

    if not is_local_model(SCREENSHOT_MODEL) and not os.environ.get("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY environment variable not set.")
        print("Set it with: export OPENAI_API_KEY='your-api-key'")
        print("Or use local model: set SCREENSHOT_MODEL=gemma3:4b")
        sys.exit(1)

    print("What do you want to be doing? (e.g., 'learn quantum physics', 'learn AI')")
    task = input("> ").strip() or "coding or learning"

    state = DeepWorkWithMonitoring(task)

    print(f"\n--- Initializing: Task = {task} ---")
    print(f"Capture interval: {CAPTURE_INTERVAL_SECONDS} seconds")
    print(f"Captures before analysis: {CAPTURES_BEFORE_ANALYSIS}")
    print(f"Model: {SCREENSHOT_MODEL}")

    state.set_on()

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
                state.set_on()
                print("--- Block mode + monitoring activated ---")

            elif user_input == "off":
                if state.current_mode == "off":
                    print("Already in 'off' mode.")
                    continue
                if not prompt_confirmation(CONFIRMATION_PHRASE, "'off' switch"):
                    continue
                state.set_off()
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

                state.set_break(minutes)
                print(f"--- Break mode: {minutes} min (monitoring paused) ---")

            elif user_input == "exit":
                print("Exiting...")
                state.cleanup()
                break

            elif user_input:
                print("Commands: on | off | break <min> | exit")

    except KeyboardInterrupt:
        print("\nCtrl+C - Exiting...")
        state.cleanup()

    print("Done.")


if __name__ == "__main__":
    main()
