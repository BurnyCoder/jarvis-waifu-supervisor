"""Blocking functionality re-exports for convenience imports."""

from .config import CONFIRMATION_PHRASE
from .utils import is_admin, run_as_admin, prompt_confirmation
from .hosts import modify_hosts
from .processes import kill_target_processes

__all__ = [
    "CONFIRMATION_PHRASE",
    "is_admin",
    "run_as_admin",
    "prompt_confirmation",
    "modify_hosts",
    "kill_target_processes",
]
