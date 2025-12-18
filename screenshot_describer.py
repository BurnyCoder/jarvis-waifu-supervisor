"""
Screenshot Describer - Captures screen and sends to OpenAI Vision API for description.

Requirements:
    pip install openai pillow mss python-dotenv

Usage:
    Create a .env file with OPENAI_API_KEY=your-api-key, then run:
    python screenshot_describer.py

    For local Gemma 3 model, set SCREENSHOT_MODEL=gemma3:4b
"""

import io
import os
import mss
from PIL import Image

from llm_api import complete_vision, is_local_model
from save_results import save_screenshot_with_analysis

# Screenshot-specific model (defaults to local Gemma 3 4B)
# SCREENSHOT_MODEL = os.environ.get("SCREENSHOT_MODEL", "gpt-5-mini")
SCREENSHOT_MODEL = os.environ.get("SCREENSHOT_MODEL", "gemma3:4b")


def get_monitor_count() -> int:
    """Get the number of available monitors."""
    with mss.mss() as sct:
        # monitors[0] is all combined, monitors[1:] are individual monitors
        return len(sct.monitors) - 1


def capture_screenshot(monitor_number: int = 1) -> bytes:
    """
    Capture a screenshot of the specified monitor.

    Args:
        monitor_number: Monitor index (1 = primary monitor, 0 = all monitors combined)

    Returns:
        PNG image bytes
    """
    with mss.mss() as sct:
        monitor = sct.monitors[monitor_number]
        screenshot = sct.grab(monitor)

        # Convert to PIL Image
        img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")

        # Convert to PNG bytes
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        return buffer.getvalue()


def describe_screenshot(
    image_bytes: bytes,
    prompt: str = "Briefly describe what you see in this screenshot.",
    model: str | None = None,
    max_completion_tokens: int = 4000,
    detail: str = "auto"
) -> str:
    """
    Send a screenshot to OpenAI Vision API or local LLM and get a description.

    Args:
        image_bytes: PNG image bytes
        prompt: The question/prompt to ask about the image
        model: Model to use (defaults to SCREENSHOT_MODEL)
        max_completion_tokens: Maximum tokens in response
        detail: Image detail level - "low", "high", or "auto"

    Returns:
        Description text from the API
    """
    return complete_vision(
        image_bytes=image_bytes,
        prompt=prompt,
        model=model or SCREENSHOT_MODEL,
        max_completion_tokens=max_completion_tokens,
        detail=detail
    )


def capture_and_describe(
    prompt: str = "Briefly describe what you see in this screenshot.",
    monitor_number: int = 0,
    model: str | None = None,
    save_results: bool = False
) -> str:
    """
    Convenience function to capture screenshot and get description in one call.

    Args:
        prompt: The question/prompt to ask about the image
        monitor_number: Monitor to capture (0 = all monitors, 1 = primary, etc.)
        model: Model to use (defaults to SCREENSHOT_MODEL)
        save_results: Whether to save screenshot and analysis to results folders

    Returns:
        Description from OpenAI Vision API or local LLM
    """
    model = model or SCREENSHOT_MODEL

    if monitor_number == 0:
        print("Capturing screenshot from all monitors...")
    else:
        print(f"Capturing screenshot from monitor {monitor_number}...")
    image_bytes = capture_screenshot(monitor_number)

    backend = "local Ollama" if is_local_model(model) else "OpenAI"
    print(f"Sending to {backend} ({model}) for analysis...")
    description = describe_screenshot(image_bytes, prompt=prompt, model=model)

    if save_results:
        image_path, text_path = save_screenshot_with_analysis(image_bytes, description)
        print(f"Screenshot saved to {image_path}")
        print(f"Analysis saved to {text_path}")

    return description


if __name__ == "__main__":
    if not is_local_model(SCREENSHOT_MODEL) and not os.environ.get("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY environment variable not set.")
        print("Set it with: export OPENAI_API_KEY='your-api-key'")
        print("Or use local model: set SCREENSHOT_MODEL=gemma3:4b")
        exit(1)

    monitor_count = get_monitor_count()
    print(f"Detected {monitor_count} monitor(s)")

    description = capture_and_describe(
        prompt="Briefly describe what's on screen. What apps are open and what is the user doing?",
        monitor_number=0,
        save_results=True
    )

    print("\n" + "=" * 50)
    print("SCREENSHOT DESCRIPTION:")
    print("=" * 50)
    print(description)
