"""Thread workers for deep work monitoring."""

import threading
import time
from typing import Callable

from .config import CAPTURE_INTERVAL_SECONDS, CAPTURES_BEFORE_ANALYSIS
from .processes import kill_target_processes
from .monitoring import capture_all_stitched, analyze_captures, speak_result, save_analysis
from .save_results import save_image, get_timestamp


class ManagedThread:
    """Base class for threads with clean start/stop lifecycle."""

    def __init__(self, name: str):
        self.name = name
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def start(self):
        """Start the thread if not already running."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
            print(f"{self.name} started.")

    def stop(self, timeout: float = 5.0):
        """Stop the thread and wait for it to finish."""
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                return
            self._stop_event.set()
        self._thread.join(timeout=timeout)
        with self._lock:
            self._thread = None
        print(f"{self.name} stopped.")

    def _run(self):
        """Override in subclass."""
        raise NotImplementedError


class ProcessKillerThread(ManagedThread):
    """Continuously kills distracting processes."""

    def __init__(self):
        super().__init__("Process killer")

    def _run(self):
        while not self._stop_event.is_set():
            kill_target_processes()
            self._stop_event.wait(timeout=1.0)


class ProductivityMonitorThread(ManagedThread):
    """Periodically captures screen/webcam and analyzes productivity."""

    def __init__(self, prompt: str, on_analysis: Callable[[str, bool], None]):
        super().__init__("Productivity monitor")
        self.prompt = prompt
        self.on_analysis = on_analysis

    def _run(self):
        captured_images = []

        while not self._stop_event.is_set():
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
                        captured_images, self.prompt
                    )
                    self.on_analysis(analysis, is_productive)

                    speak_result(is_productive, reason)
                    save_analysis(self.prompt, analysis)

                    captured_images = []

                # Wait for next capture, checking stop event frequently
                for _ in range(int(CAPTURE_INTERVAL_SECONDS * 10)):
                    if self._stop_event.is_set():
                        return
                    time.sleep(0.1)

            except Exception as e:
                print(f"Monitor error: {e}")
                time.sleep(CAPTURE_INTERVAL_SECONDS)


class BreakTimer(ManagedThread):
    """Countdown timer that calls a callback when break ends."""

    def __init__(self, minutes: float, on_tick: Callable[[int], None], on_complete: Callable[[], None]):
        super().__init__("Break timer")
        self.minutes = minutes
        self.on_tick = on_tick
        self.on_complete = on_complete

    def _run(self):
        total_seconds = int(self.minutes * 60)
        print(f"Break timer: {self.minutes} minute(s)")

        for remaining in range(total_seconds, 0, -1):
            self.on_tick(remaining)
            if self._stop_event.is_set():
                self.on_tick(0)
                return
            if remaining % 60 == 0 or remaining == 30 or remaining <= 10:
                mins, secs = divmod(remaining, 60)
                print(f"Break remaining: {mins:02d}:{secs:02d}")
            time.sleep(1)

        self.on_tick(0)
        if not self._stop_event.is_set():
            print("\n*** BREAK OVER - Re-enabling blocks and monitoring ***")
            self.on_complete()
