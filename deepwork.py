#!/usr/bin/env python3
"""Deep Work Script - Interactive mode for blocking distractions."""

import sys
import platform
import threading
import time

from deepwork import (
    CONFIRMATION_PHRASE,
    is_admin,
    run_as_admin,
    prompt_confirmation,
    modify_hosts,
    kill_target_processes,
)


class DeepWorkState:
    """Shared state for the deep work script."""
    def __init__(self):
        self.current_mode = "on"
        self.lock = threading.Lock()
        self.killer_stop_event = threading.Event()
        self.break_cancel_event = threading.Event()
        self.killer_thread = None
        self.break_thread = None

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
            # Auto-restore blocking - this happens in the background thread
            print("\n*** BREAK OVER - Re-enabling blocks ***")
            with self.lock:
                self.current_mode = "on"
            modify_hosts(block=True)
            self.start_killer()
            print("Type 'off' or 'break <min>' to disable again.\n")


def main():
    if platform.system() != "Windows":
        print("Error: This script is designed for Windows only.")
        sys.exit(1)

    if not is_admin():
        print("Administrator privileges required. Requesting elevation...")
        run_as_admin()

    state = DeepWorkState()

    print("--- Initializing: Ensuring system is in 'on' mode ---")
    modify_hosts(block=True)
    state.start_killer()

    print("\n--- Deep Work Script Interactive Mode ---")
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
                state.current_mode = "on"
                print("--- Block mode activated ---")

            elif user_input == "off":
                if state.current_mode == "off":
                    print("Already in 'off' mode.")
                    continue
                if not prompt_confirmation(CONFIRMATION_PHRASE, "'off' switch"):
                    continue
                state.cancel_break()
                state.stop_killer()
                modify_hosts(block=False)
                state.current_mode = "off"
                print("--- Unblock mode activated ---")

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
                modify_hosts(block=False)
                state.current_mode = "break"
                state.start_break(minutes)
                print(f"--- Break mode: {minutes} min ---")

            elif user_input == "exit":
                print("Exiting...")
                state.cancel_break()
                state.stop_killer()
                modify_hosts(block=False)
                break

            elif user_input:
                print("Commands: on | off | break <min> | exit")

    except KeyboardInterrupt:
        print("\nCtrl+C - Exiting...")
        state.cancel_break()
        state.stop_killer()
        modify_hosts(block=False)

    print("Done.")


if __name__ == "__main__":
    main()
