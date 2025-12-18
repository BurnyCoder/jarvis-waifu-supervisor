"""Async task management for process killer and break timer."""

import asyncio

from .processes import kill_target_processes


async def cancel_break(break_task, break_cancelled_event, break_end_event):
    """Cancel any active break timer. Returns None (new break_task value)."""
    if break_task is not None and not break_task.done():
        print("Cancelling active break...")
        break_cancelled_event.set()
        break_task.cancel()
        try:
            await break_task
        except asyncio.CancelledError:
            pass
    break_cancelled_event.clear()
    break_end_event.clear()
    return None


async def stop_killer_task(killer_task, stop_event):
    """Stop the process killer task if running. Returns None (new killer_task value)."""
    if killer_task is not None and not killer_task.done():
        print("Stopping process killer task...")
        stop_event.set()
        killer_task.cancel()
        try:
            await killer_task
        except asyncio.CancelledError:
            pass
    return None


async def start_killer_task(stop_event):
    """Start a new process killer task. Returns the new task."""
    print("Starting process killer task...")
    stop_event.clear()
    killer_task = asyncio.create_task(process_killer_loop(stop_event))
    return killer_task


async def process_killer_loop(stop_event):
    """Continuously attempts to kill target processes until stop_event is set."""
    print("Process killer task started.")
    while not stop_event.is_set():
        # Run the blocking kill in a thread to not block the event loop
        await asyncio.to_thread(kill_target_processes)
        # Check every second
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=1.0)
            break  # Event was set
        except asyncio.TimeoutError:
            pass  # Continue loop
    print("Process killer task stopped.")
