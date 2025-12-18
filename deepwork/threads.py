"""Thread management for process killer and break timer."""

import time
import threading

from .processes import kill_target_processes


def cancel_break(break_thread, break_cancelled_event, break_end_event):
    """Cancel any active break timer. Returns None (new break_thread value)."""
    if break_thread is not None and break_thread.is_alive():
        print("Cancelling active break...")
        break_cancelled_event.set()
        break_thread.join(timeout=2.0)
    break_cancelled_event.clear()
    break_end_event.clear()
    return None


def stop_killer_thread(killer_thread, stop_event, timeout=5.0):
    """Stop the process killer thread if running. Returns None (new killer_thread value)."""
    if killer_thread is not None and killer_thread.is_alive():
        print("Stopping process killer thread...")
        stop_event.set()
        killer_thread.join(timeout=timeout)
        if killer_thread.is_alive():
            print("Warning: Process killer thread did not stop gracefully.")
    return None


def start_killer_thread(stop_event):
    """Start a new process killer thread. Returns the new thread."""
    print("Starting process killer thread...")
    stop_event.clear()
    killer_thread = threading.Thread(target=process_killer_loop, args=(stop_event,), daemon=True)
    killer_thread.start()
    return killer_thread


def process_killer_loop(stop_event):
    """Continuously attempts to kill target processes until stop_event is set."""
    print("Process killer thread started.")
    while not stop_event.is_set():
        kill_target_processes()
        # Check stop_event frequently for responsiveness
        time.sleep(0.1)  # Check every 100ms
        if stop_event.wait(timeout=0.9):  # Wait for up to 0.9s
            break  # Exit loop if event is set during wait
    print("Process killer thread stopped.")


def break_timer_thread(minutes, break_end_event, break_cancelled_event):
    """Waits for the specified minutes, then signals that break is over."""
    total_seconds = minutes * 60
    print(f"Break timer started: {minutes} minute(s) ({total_seconds} seconds)")

    for remaining in range(total_seconds, 0, -1):
        if break_cancelled_event.is_set():
            print("\nBreak cancelled early.")
            return
        # Print countdown every 60 seconds or at specific milestones
        if remaining % 60 == 0 or remaining == 30 or remaining <= 10:
            mins, secs = divmod(remaining, 60)
            print(f"Break time remaining: {mins:02d}:{secs:02d}")
        time.sleep(1)

    if not break_cancelled_event.is_set():
        print("\n*** Break time is over! Returning to block mode... ***")
        break_end_event.set()
