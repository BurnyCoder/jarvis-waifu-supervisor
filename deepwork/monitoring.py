"""Productivity monitoring helpers - capture, analysis, and TTS."""

import json
from capture_describer import (
    capture_screenshot, capture_webcam, stitch_images,
    get_monitor_count, get_webcam_count, SCREENSHOT_MODEL
)
from llm_api import complete_vision, is_local_model
from save_results import save_text, get_timestamp
from tts import speak


def parse_productivity_response(analysis: str) -> tuple[bool, str]:
    """Parse the LLM's JSON response to extract productivity status and reason."""
    try:
        start = analysis.find("{")
        end = analysis.rfind("}") + 1
        if start != -1 and end > start:
            json_str = analysis[start:end]
            data = json.loads(json_str)
            productive = data.get("productive", "").lower() == "yes"
            reason = data.get("reason", "")
            return productive, reason
    except json.JSONDecodeError:
        pass
    return "productive\": \"yes" in analysis.lower(), ""


def capture_all_stitched() -> bytes:
    """Capture all monitors and webcam, return as single stitched image."""
    images = []
    labels = []
    scale_factors = []

    monitor_count = get_monitor_count()
    for i in range(1, monitor_count + 1):
        images.append(capture_screenshot(i))
        labels.append(f"Monitor {i}")
        scale_factors.append(1.0)

    webcam_count = get_webcam_count()
    if webcam_count > 0:
        try:
            images.append(capture_webcam(0))
            labels.append("Webcam")
            scale_factors.append(3.0)
        except RuntimeError as e:
            print(f"Webcam capture failed: {e}")

    if not images:
        raise RuntimeError("No images captured")

    return stitch_images(images, labels, scale_factors)


def analyze_captures(images: list[bytes], prompt: str) -> tuple[bool, str, str]:
    """
    Send captures to LLM for productivity analysis.

    Returns:
        (is_productive, reason, raw_analysis)
    """
    backend = "local Ollama" if is_local_model(SCREENSHOT_MODEL) else "OpenAI"
    print(f"Sending to {backend} ({SCREENSHOT_MODEL})...")

    analysis = complete_vision(images, prompt=prompt, model=SCREENSHOT_MODEL)

    print("\n" + "=" * 50)
    print("PRODUCTIVITY ANALYSIS:")
    print("=" * 50)
    print(analysis)
    print("=" * 50)

    is_productive, reason = parse_productivity_response(analysis)
    return is_productive, reason, analysis


def speak_result(is_productive: bool, reason: str):
    """Speak the productivity result via TTS."""
    if not is_productive:
        message = f"You are probably not being productive. {reason}"
    else:
        message = reason

    print(f"\n[TTS] {message}")
    speak(message)


def save_analysis(prompt: str, analysis: str, prefix: str = "productivity_analysis"):
    """Save prompt and analysis to disk."""
    timestamp = get_timestamp()
    full_text = f"PROMPT:\n{prompt}\n\n{'='*50}\n\nANALYSIS:\n{analysis}"
    text_path = save_text(full_text, f"{prefix}_{timestamp}")
    print(f"Analysis saved to {text_path}")
    return text_path
