"""
Core module for Deep Work with Productivity Monitoring.

This module provides:
- Website and app blocking functionality
- Screen/webcam capture and AI productivity analysis
- Text-to-speech feedback
- Result saving utilities
"""

# Configuration
from .config import (
    WEBSITES_TO_BLOCK,
    APP_PATHS,
    HOSTS_FILE_PATH,
    REDIRECT_IP,
    HOSTS_MARKER,
    CONFIRMATION_PHRASE,
)

# Prompts
from .prompts import PRODUCTIVITY_PROMPT_TEMPLATE

# Utilities
from .utils import is_admin, run_as_admin, flush_dns, prompt_confirmation

# Blocking
from .hosts import modify_hosts
from .processes import kill_target_processes

# Capture and LLM
from .capture_describer import SCREENSHOT_MODEL
from .llm_api import is_local_model

# Monitoring
from .monitoring import (
    capture_all_stitched,
    parse_productivity_response,
    analyze_captures,
    speak_result,
    save_analysis,
)

# Save results
from .save_results import save_image, save_text, get_timestamp

__all__ = [
    # Config
    "WEBSITES_TO_BLOCK",
    "APP_PATHS",
    "HOSTS_FILE_PATH",
    "REDIRECT_IP",
    "HOSTS_MARKER",
    "CONFIRMATION_PHRASE",
    # Prompts
    "PRODUCTIVITY_PROMPT_TEMPLATE",
    # Utils
    "is_admin",
    "run_as_admin",
    "flush_dns",
    "prompt_confirmation",
    # Blocking
    "modify_hosts",
    "kill_target_processes",
    # Capture/LLM
    "SCREENSHOT_MODEL",
    "is_local_model",
    # Monitoring
    "capture_all_stitched",
    "parse_productivity_response",
    "analyze_captures",
    "speak_result",
    "save_analysis",
    # Save results
    "save_image",
    "save_text",
    "get_timestamp",
]
