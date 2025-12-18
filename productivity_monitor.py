"""
Productivity Monitor - Captures screens and webcam periodically and analyzes productivity.

Captures screenshots and webcam at regular intervals, stitches them together,
and after a set number of captures, sends all images to LLM for productivity analysis.
"""

import json
import os
import time
import pyttsx3
from capture_describer import (
    capture_screenshot, capture_webcam, stitch_images,
    get_monitor_count, get_webcam_count, SCREENSHOT_MODEL
)
from llm_api import complete_vision, is_local_model
from save_results import save_image, save_text, get_timestamp

# Configuration via environment variables
# CAPTURE_INTERVAL_SECONDS = float(os.environ.get("CAPTURE_INTERVAL_SECONDS", "5"))
# CAPTURES_BEFORE_ANALYSIS = int(os.environ.get("CAPTURES_BEFORE_ANALYSIS", "3"))
# GOOD_JOB_INTERVAL_MINUTES = float(os.environ.get("GOOD_JOB_INTERVAL_MINUTES", "0.5"))
CAPTURE_INTERVAL_SECONDS = float(os.environ.get("CAPTURE_INTERVAL_SECONDS", "60"))
CAPTURES_BEFORE_ANALYSIS = int(os.environ.get("CAPTURES_BEFORE_ANALYSIS", "5"))
GOOD_JOB_INTERVAL_MINUTES = float(os.environ.get("GOOD_JOB_INTERVAL_MINUTES", "30"))

PRODUCTIVITY_PROMPT_TEMPLATE = """The user said they want to be doing: {task}

Is the user productive on that task? Did anything change on his coding or learning part of the screen? Is he looking at screen and not on phone?

Important:
- If the coding IDE is exactly the same (same open files, same code visible, same responses from AI agents, no changes) in all screenshots, or if the learning lecture/video is paused, the user is NOT productive.
- If the user is looking down in the webcam, he's likely looking at his phone and is NOT productive.
- If the user has a lecture stopped (paused video, not playing), he's not learning and is NOT productive.

Respond with json with "yes" or "no" and reason.

Example response:
{{"productive": "yes", "reason": "User is actively coding, screen shows IDE with code changes, user is focused on screen"}}
{{"productive": "no", "reason": "IDE shows identical code in all screenshots with no changes, user appears distracted"}}
{{"productive": "no", "reason": "User is looking down at phone instead of at the screen"}}"""

# TTS engine initialized per-call to avoid threading issues
def speak(text: str):
    """Speak text using TTS engine."""
    try:
        engine = pyttsx3.init()
        engine.say(text)
        engine.runAndWait()
        engine.stop()
    except Exception as e:
        print(f"TTS error: {e}")


def parse_productivity_response(analysis: str) -> tuple[bool, str]:
    """Parse the LLM's JSON response to extract productivity status and reason."""
    try:
        # Try to find JSON in the response
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
    # Fallback: check if "no" appears in a productivity context
    return "productive\": \"yes" in analysis.lower(), ""


def capture_all_stitched() -> bytes:
    """Capture all monitors and webcam, return as single stitched image."""
    images = []
    labels = []
    scale_factors = []

    # Capture all monitors
    monitor_count = get_monitor_count()
    for i in range(1, monitor_count + 1):
        images.append(capture_screenshot(i))
        labels.append(f"Monitor {i}")
        scale_factors.append(1.0)

    # Capture webcam
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


def run_productivity_monitor(save_results: bool = True):
    """
    Main loop that captures images periodically and analyzes productivity.

    Args:
        save_results: Whether to save captured images and analysis to disk
    """
    # Ask user what they want to be doing
    print("What do you want to be doing? (e.g., 'coding a web app', 'studying Python')")
    task = input("> ").strip()
    if not task:
        task = "coding or learning"

    productivity_prompt = PRODUCTIVITY_PROMPT_TEMPLATE.format(task=task)

    print(f"\nProductivity Monitor started")
    print(f"Task: {task}")
    print(f"Capture interval: {CAPTURE_INTERVAL_SECONDS} seconds")
    print(f"Captures before analysis: {CAPTURES_BEFORE_ANALYSIS}")
    print(f"Model: {SCREENSHOT_MODEL}")
    print("=" * 50)

    captured_images = []
    last_good_job_time = time.time()

    while True:
        try:
            # Capture stitched image
            timestamp = get_timestamp()
            print(f"\n[{timestamp}] Capturing...")

            stitched_image = capture_all_stitched()
            captured_images.append(stitched_image)

            if save_results:
                image_path = save_image(stitched_image, f"productivity_{timestamp}")
                print(f"Saved to {image_path}")

            print(f"Captured {len(captured_images)}/{CAPTURES_BEFORE_ANALYSIS}")

            # Check if we have enough captures for analysis
            if len(captured_images) >= CAPTURES_BEFORE_ANALYSIS:
                print(f"\nAnalyzing {len(captured_images)} captures...")

                backend = "local Ollama" if is_local_model(SCREENSHOT_MODEL) else "OpenAI"
                print(f"Sending to {backend} ({SCREENSHOT_MODEL})...")

                analysis = complete_vision(
                    captured_images,
                    prompt=productivity_prompt,
                    model=SCREENSHOT_MODEL
                )

                print("\n" + "=" * 50)
                print("PRODUCTIVITY ANALYSIS:")
                print("=" * 50)
                print(analysis)
                print("=" * 50)

                # Parse response and speak if not productive
                is_productive, reason = parse_productivity_response(analysis)
                if not is_productive:
                    message = f"You are probably not being productive. {reason}"
                    print(f"\n[TTS] {message}")
                    speak(message)
                else:
                    # Check if it's time to say "good job"
                    elapsed = time.time() - last_good_job_time
                    if elapsed >= GOOD_JOB_INTERVAL_MINUTES * 60:
                        message = "Good job! Keep up the great work."
                        print(f"\n[TTS] {message}")
                        speak(message)
                        last_good_job_time = time.time()

                if save_results:
                    text_path = save_text(analysis, f"productivity_analysis_{timestamp}")
                    print(f"Analysis saved to {text_path}")

                # Reset for next batch
                captured_images = []

            # Wait for next capture
            print(f"Next capture in {CAPTURE_INTERVAL_SECONDS} seconds...")
            time.sleep(CAPTURE_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            print("\nProductivity Monitor stopped.")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(CAPTURE_INTERVAL_SECONDS)


if __name__ == "__main__":
    if not is_local_model(SCREENSHOT_MODEL) and not os.environ.get("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY environment variable not set.")
        print("Set it with: export OPENAI_API_KEY='your-api-key'")
        print("Or use local model: set SCREENSHOT_MODEL=gemma3:4b")
        exit(1)

    run_productivity_monitor(save_results=True)
