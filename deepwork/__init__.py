"""Deep Work script - blocks distracting websites and applications."""

from .config import (
    WEBSITES_TO_BLOCK,
    APP_PATHS,
    HOSTS_FILE_PATH,
    REDIRECT_IP,
    HOSTS_MARKER,
    CONFIRMATION_PHRASE,
)
from .utils import is_admin, run_as_admin, flush_dns, prompt_confirmation
from .hosts import modify_hosts
from .processes import kill_target_processes
from .threads import (
    cancel_break,
    stop_killer_thread,
    start_killer_thread,
    process_killer_loop,
    break_timer_thread,
)

__all__ = [
    "WEBSITES_TO_BLOCK",
    "APP_PATHS",
    "HOSTS_FILE_PATH",
    "REDIRECT_IP",
    "HOSTS_MARKER",
    "CONFIRMATION_PHRASE",
    "is_admin",
    "run_as_admin",
    "flush_dns",
    "prompt_confirmation",
    "modify_hosts",
    "kill_target_processes",
    "cancel_break",
    "stop_killer_thread",
    "start_killer_thread",
    "process_killer_loop",
    "break_timer_thread",
]
