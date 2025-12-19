"""Deep Work session management with integrated productivity monitoring."""

from .prompts import PRODUCTIVITY_PROMPT_TEMPLATE
from .hosts import modify_hosts
from .workers import ProcessKillerThread, ProductivityMonitorThread, BreakTimer


class DeepWorkWithMonitoring:
    """Deep work state with integrated productivity monitoring.

    Manages three concurrent concerns:
    - Process killing (blocking distracting apps)
    - Break timer (timed breaks with auto-restore)
    - Productivity monitoring (periodic capture and AI analysis)
    """

    def __init__(self, task: str):
        self.task = task
        self.current_mode = "on"
        self.break_remaining = 0
        self.last_analysis = ""
        self.is_productive = True

        prompt = PRODUCTIVITY_PROMPT_TEMPLATE.format(task=task)
        self._killer = ProcessKillerThread()
        self._monitor = ProductivityMonitorThread(prompt, self._on_analysis)
        self._break_timer: BreakTimer | None = None

    def _on_analysis(self, analysis: str, is_productive: bool):
        """Callback when productivity analysis completes."""
        self.last_analysis = analysis
        self.is_productive = is_productive

    def _on_break_complete(self):
        """Callback when break timer ends - restore blocking."""
        self.current_mode = "on"
        modify_hosts(block=True)
        self._killer.start()
        self._monitor.start()
        print("Type 'off' or 'break <min>' to disable again.\n")

    # --- Mode Transitions ---

    def set_on(self):
        """Activate deep work mode with blocking and monitoring."""
        self._cancel_break()
        modify_hosts(block=True)
        self._killer.start()
        self._monitor.start()
        self.current_mode = "on"

    def set_off(self):
        """Deactivate deep work mode."""
        self._cancel_break()
        self._killer.stop()
        self._monitor.stop()
        modify_hosts(block=False)
        self.current_mode = "off"

    def set_break(self, minutes: float):
        """Enter break mode for specified duration."""
        self._cancel_break()
        self._killer.stop()
        self._monitor.stop()
        modify_hosts(block=False)
        self.current_mode = "break"

        self._break_timer = BreakTimer(
            minutes,
            on_tick=lambda remaining: setattr(self, 'break_remaining', remaining),
            on_complete=self._on_break_complete,
        )
        self._break_timer.start()

    def _cancel_break(self):
        """Cancel active break timer if running."""
        if self._break_timer:
            self._break_timer.stop(timeout=2.0)
            self._break_timer = None

    def cleanup(self):
        """Stop all threads and unblock sites."""
        self._cancel_break()
        self._killer.stop()
        self._monitor.stop()
        modify_hosts(block=False)
