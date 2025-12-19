"""
Productivity Monitor - Captures screens and webcam periodically and analyzes productivity.

Captures screenshots and webcam at regular intervals, stitches them together,
and after a set number of captures, sends all images to LLM for productivity analysis.
"""

import json
import os
import time
from capture_describer import (
    capture_screenshot, capture_webcam, stitch_images,
    get_monitor_count, get_webcam_count, SCREENSHOT_MODEL
)
from llm_api import complete_vision, is_local_model
from save_results import save_image, save_text, get_timestamp
from tts import speak

# Configuration via environment variables
CAPTURE_INTERVAL_SECONDS = float(os.environ.get("CAPTURE_INTERVAL_SECONDS", "5"))
CAPTURES_BEFORE_ANALYSIS = int(os.environ.get("CAPTURES_BEFORE_ANALYSIS", "3"))
# CAPTURE_INTERVAL_SECONDS = float(os.environ.get("CAPTURE_INTERVAL_SECONDS", "60"))
# CAPTURES_BEFORE_ANALYSIS = int(os.environ.get("CAPTURES_BEFORE_ANALYSIS", "5"))

# GOOD_JOB_INTERVAL_MINUTES = float(os.environ.get("GOOD_JOB_INTERVAL_MINUTES", "0.5"))
# GOOD_JOB_INTERVAL_MINUTES = float(os.environ.get("GOOD_JOB_INTERVAL_MINUTES", "30"))

PRODUCTIVITY_PROMPT_TEMPLATE = """The user said they want to be doing: {task}

Analyze if the user is productive on their stated task by comparing the screenshots over time.

## Task-Specific Indicators

**Coding / Building an app / Chatbot development:**
- Look for: Code changes between screenshots, new lines written, cursor position changes, different files opened, terminal output changes
- AI-assisted coding (Claude Code, Cursor, Copilot, etc.): User giving prompts, AI generating/modifying code, reviewing AI output, accepting/rejecting changes - this IS productive even if user isn't typing code themselves
- NOT productive if: IDE shows identical code/files in all screenshots, no visible typing or changes, AND no AI agent activity

**Training a model / ML work:**
- Look for: Training logs progressing, loss values changing, new epochs starting, Jupyter notebook cells being executed, TensorBoard graphs updating, GPU utilization visible
- NOT productive if: Training logs are static, notebook cells unchanged, no progress in metrics

**Debugging:**
- Look for: Breakpoints hit, variable inspector changes, stepping through code, console output changes, error messages being investigated, stack traces being examined
- AI-assisted debugging: Pasting errors to AI, AI analyzing code, discussing fixes with Claude/ChatGPT - this IS productive
- NOT productive if: Debugger paused on same line in all screenshots, no investigation happening, no AI conversation about the issue

**Learning / Studying (physics, math, courses, etc.):**
- Look for: Video playing (progress bar moving), page scrolling in textbook/PDF, notes being taken, slides advancing, practice problems being worked on
- AI-assisted learning: Asking Claude/ChatGPT to explain concepts, working through problems together, AI tutoring - this IS productive
- Physical notebook/exercise book: If user is looking DOWN at desk (not at phone) and appears to be writing, they may be doing math exercises on paper - this IS productive. Look for pen/pencil in hand, writing posture, textbook or problem set visible on screen
- NOT productive if: Video paused (same frame), same page/slide visible throughout, no note-taking activity, no AI conversation, AND user not engaged with physical materials

**Note-taking / Obsidian vault / Documentation:**
- Look for: New text being written, links being created, files being organized, markdown being edited, graph view changes, new notes created
- NOT productive if: Same note open with no changes, just browsing without editing

**Reading / Research:**
- Look for: Page scrolling, tab changes, highlighting or annotations, switching between sources, notes being taken alongside
- NOT productive if: Same page visible throughout, no scrolling or interaction

## Important Exception
- Background audio/podcasts on YouTube are OK if user is still working (code changing, notes being taken, etc.) - this helps some people focus
- Only flag YouTube as unproductive if user is WATCHING it (video in focus, no work progress visible)

## Universal Red Flags (Always NOT productive)
- User looking down in webcam (likely on phone)
- Screen unchanged across ALL screenshots AND user not engaged with AI tools
- Actively watching entertainment (social media feed scrolling, games, YouTube video in focus with no work happening)
- Browser showing distraction sites instead of work-related content with no work progress

## Response Format
Respond with JSON containing "productive" (yes/no) and "reason".

**When productive:** Start your reason with encouraging phrases like "Good job!", "Nice work!", "Great progress!", or "Keep it up!" followed by a specific observation about what you see them accomplishing on their task.

**When NOT productive:** Start your reason with gentle phrases like "Hey, I noticed...", "It looks like you might be...", or "I'm not seeing much progress..." followed by what you observed. Be uncertain and non-judgmental - they might just be thinking or taking a needed break.

Address the user directly with "you" and reference their stated task to make it personal.

Examples:
{{"productive": "yes", "reason": "Nice progress on your chatbot app! I see you added a new function and the tests are running in the terminal. Keep it up!"}}
{{"productive": "yes", "reason": "Good work on your quantum physics notes! You added a new section about wave functions in Obsidian. Stay focused!"}}
{{"productive": "yes", "reason": "Great learning session! The MIT lecture moved from 12:30 to 15:45 and you're looking at the screen taking it in."}}
{{"productive": "yes", "reason": "Solid progress on your AI agent! Claude Code generated a new API endpoint and you're reviewing the diff. Nice teamwork!"}}
{{"productive": "no", "reason": "Hey, I noticed your IDE looks the same in all screenshots. Maybe you got distracted or are stuck on something?"}}
{{"productive": "no", "reason": "It looks like you might be checking your phone? I can't see much progress on the screen."}}
{{"productive": "no", "reason": "The video seems paused - maybe you're taking a break or got sidetracked?"}}"""

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
    # last_good_job_time = time.time()

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

                # Parse response and speak result
                is_productive, reason = parse_productivity_response(analysis)
                if not is_productive:
                    message = f"You are probably not being productive. {reason}"
                    print(f"\n[TTS] {message}")
                    speak(message)
                else:
                    # Speak the productive reason
                    print(f"\n[TTS] {reason}")
                    speak(reason)
                    # Check if it's time to say "good job"
                    # elapsed = time.time() - last_good_job_time
                    # if elapsed >= GOOD_JOB_INTERVAL_MINUTES * 60:
                    #     message = "Good job! Keep up the great work."
                    #     print(f"\n[TTS] {message}")
                    #     speak(message)
                    #     last_good_job_time = time.time()

                if save_results:
                    # Save prompt and analysis together
                    full_text = f"PROMPT:\n{productivity_prompt}\n\n{'='*50}\n\nANALYSIS:\n{analysis}"
                    text_path = save_text(full_text, f"productivity_analysis_{timestamp}")
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
