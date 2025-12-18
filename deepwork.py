#!/usr/bin/env python3
"""Deep Work Script - Interactive mode for blocking distractions."""

import sys
import platform
import threading

from deepwork import (
    CONFIRMATION_PHRASE,
    is_admin,
    run_as_admin,
    prompt_confirmation,
    modify_hosts,
    cancel_break,
    stop_killer_thread,
    start_killer_thread,
    break_timer_thread,
)


def main():
    # Check OS
    if platform.system() != "Windows":
        print("Error: This script is designed for Windows only.")
        sys.exit(1)

    # Check and request admin privileges
    if not is_admin():
        print("Administrator privileges required. Requesting elevation...")
        run_as_admin()  # This will exit the current script if elevation is successful/attempted

    # --- Interactive Mode ---
    current_mode = "on"  # Start in 'on' mode
    killer_thread = None
    stop_event = threading.Event()
    break_end_event = threading.Event()
    break_cancelled_event = threading.Event()
    break_thread = None

    print("--- Initializing: Ensuring system is in 'on' mode ---")
    modify_hosts(block=True)  # Ensure blocked state initially
    # Start the killer thread immediately for the initial 'on' state
    killer_thread = start_killer_thread(stop_event)

    print("\n--- Deep Work Script Interactive Mode ---")
    print("Commands:")
    print("  on           - Block distractions")
    print("  off          - Unblock distractions (requires confirmation)")
    print("  break <min>  - Take a timed break (e.g., 'break 5' for 5 minutes)")
    print("  exit         - Exit the script")

    try:
        while True:
            # Check if break timer has expired
            if break_end_event.is_set():
                print("\n--- Break ended, re-enabling blocks ---")
                modify_hosts(block=True)
                # Restart the killer thread
                if killer_thread is None or not killer_thread.is_alive():
                    killer_thread = start_killer_thread(stop_event)
                current_mode = "on"
                break_end_event.clear()
                break_thread = None
                print("--- Block ('on' mode) re-activated after break ---")

            try:
                # Add a newline before the prompt for cleaner output
                user_input = input(f"\nCurrent mode: {current_mode}. \nEnter command (on/off/break <min>/exit): \n").strip().lower()
            except EOFError:  # Handle Ctrl+Z or pipe closing
                print("\nEOF received, exiting...")
                user_input = "exit"

            if user_input == "on":
                if current_mode == "on":
                    print("Already in 'on' mode.")
                    continue

                # Cancel any active break
                break_thread = cancel_break(break_thread, break_cancelled_event, break_end_event)

                print("--- Switching to Block ('on' mode) ---")
                modify_hosts(block=True)
                current_mode = "on"
                # Start the killer thread if it's not running
                if killer_thread is None or not killer_thread.is_alive():
                    killer_thread = start_killer_thread(stop_event)
                print("--- Block ('on' mode) activated ---")

            elif user_input == "off":
                if current_mode == "off":
                    print("Already in 'off' mode.")
                    continue
                print("--- Switching to Unblock ('off' mode) ---")

                # Cancel any active break
                break_thread = cancel_break(break_thread, break_cancelled_event, break_end_event)

                # Confirmation prompt
                if not prompt_confirmation(CONFIRMATION_PHRASE, "'off' switch"):
                    continue

                # Stop the killer thread if it's running
                killer_thread = stop_killer_thread(killer_thread, stop_event)
                modify_hosts(block=False)
                current_mode = "off"
                print("--- Unblock ('off' mode) activated ---")

            elif user_input.startswith("break"):
                # Parse the break command
                parts = user_input.split()
                if len(parts) != 2:
                    print("Usage: break <minutes>  (e.g., 'break 5' for a 5-minute break)")
                    continue

                try:
                    break_minutes = float(parts[1])
                    if break_minutes <= 0:
                        print("Break duration must be a positive number of minutes.")
                        continue
                    if break_minutes > 60:
                        print("Warning: Break duration is longer than 60 minutes. Are you sure?")
                        try:
                            confirm = input("Type 'yes' to confirm long break: ").strip().lower()
                            if confirm != 'yes':
                                print("Break cancelled.")
                                continue
                        except EOFError:
                            print("\nBreak cancelled.")
                            continue
                except ValueError:
                    print(f"Invalid duration: '{parts[1]}'. Please enter a number of minutes.")
                    continue

                # Confirmation prompt for break
                if not prompt_confirmation(CONFIRMATION_PHRASE, "break"):
                    continue

                # If already on break, cancel current break first
                if current_mode == "break":
                    print("Cancelling current break and starting new one...")
                    break_thread = cancel_break(break_thread, break_cancelled_event, break_end_event)

                print(f"--- Starting {break_minutes}-minute break ---")

                # Stop the killer thread if running
                killer_thread = stop_killer_thread(killer_thread, stop_event)

                # Unblock sites
                modify_hosts(block=False)
                current_mode = "break"

                # Start the break timer thread
                break_cancelled_event.clear()
                break_end_event.clear()
                break_thread = threading.Thread(
                    target=break_timer_thread,
                    args=(break_minutes, break_end_event, break_cancelled_event),
                    daemon=True
                )
                break_thread.start()

                print(f"--- Break mode active for {break_minutes} minute(s) ---")
                print("Sites and apps are temporarily unblocked.")
                print("Type 'on' to end break early, or wait for timer to expire.")

            elif user_input == "exit":
                print("--- Exiting Script ---")

                # Cancel any active break
                break_thread = cancel_break(break_thread, break_cancelled_event, break_end_event)

                # Ensure everything is unblocked on exit
                if current_mode == "on" or current_mode == "break":
                    print("Switching to 'off' mode before exiting...")
                    killer_thread = stop_killer_thread(killer_thread, stop_event)
                    modify_hosts(block=False)
                    current_mode = "off"  # Update status for final message
                    print("'off' mode restored.")
                print("Exiting.")
                break  # Exit the main loop

            else:
                print(f"Invalid command: '{user_input}'. Please use 'on', 'off', 'break <min>', or 'exit'.")

    except KeyboardInterrupt:
        print("\nCtrl+C detected. Exiting gracefully...")
        # Cancel any active break
        break_thread = cancel_break(break_thread, break_cancelled_event, break_end_event)
        # Perform cleanup similar to 'exit' command
        if current_mode == "on" or current_mode == "break":
            print("Switching to 'off' mode before exiting...")
            killer_thread = stop_killer_thread(killer_thread, stop_event, timeout=2.0)
            modify_hosts(block=False)
            print("'off' mode restored.")
        print("Exiting.")
    finally:
        # Final check to ensure thread is stopped if still alive somehow
        if killer_thread is not None and killer_thread.is_alive():
            print("Final check: Stopping lingering process killer thread...")
            stop_event.set()
            # No long join here, as we are force exiting

        print("\nScript finished.")


if __name__ == "__main__":
    main()
