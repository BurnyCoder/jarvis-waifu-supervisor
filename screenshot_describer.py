"""
Screenshot Describer - Captures screen and sends to OpenAI Vision API for description.

Requirements:
    pip install openai pillow mss python-dotenv

Usage:
    Create a .env file with OPENAI_API_KEY=your-api-key, then run:
    python screenshot_describer.py
"""

import base64
import io
import os
from dotenv import load_dotenv
from openai import OpenAI
import mss
from PIL import Image

# Load environment variables from .env file
load_dotenv()


def capture_screenshot(monitor_number: int = 1) -> bytes:
    """
    Capture a screenshot of the specified monitor.

    Args:
        monitor_number: Monitor index (1 = primary monitor, 0 = all monitors combined)

    Returns:
        PNG image bytes
    """
    with mss.mss() as sct:
        # Get the monitor (1 = primary, 2 = secondary, etc.)
        monitor = sct.monitors[monitor_number]
        screenshot = sct.grab(monitor)

        # Convert to PIL Image
        img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")

        # Convert to PNG bytes
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        return buffer.getvalue()


def encode_image_to_base64(image_bytes: bytes) -> str:
    """Encode image bytes to base64 string."""
    return base64.b64encode(image_bytes).decode("utf-8")


def describe_screenshot(
    image_bytes: bytes,
    prompt: str = "Describe what you see in this screenshot in detail.",
    model: str = "gpt-5-mini",
    max_tokens: int = 1000,
    detail: str = "auto"
) -> str:
    """
    Send a screenshot to OpenAI Vision API and get a description.

    Args:
        image_bytes: PNG image bytes
        prompt: The question/prompt to ask about the image
        model: OpenAI model to use (gpt-5-mini, gpt-5, gpt-5.2, gpt-4o)
        max_tokens: Maximum tokens in response
        detail: Image detail level - "low", "high", or "auto"
                - low: 512x512, faster, ~85 tokens
                - high: detailed crops, slower, more tokens
                - auto: let the model decide

    Returns:
        Description text from the API
    """
    client = OpenAI()  # Uses OPENAI_API_KEY environment variable

    base64_image = encode_image_to_base64(image_bytes)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{base64_image}",
                            "detail": detail
                        }
                    }
                ]
            }
        ],
        max_tokens=max_tokens
    )

    return response.choices[0].message.content


def capture_and_describe(
    prompt: str = "Describe what you see in this screenshot in detail.",
    monitor_number: int = 1,
    model: str = "gpt-5-mini",
    save_screenshot: bool = False,
    screenshot_path: str = "screenshot.png"
) -> str:
    """
    Convenience function to capture screenshot and get description in one call.

    Args:
        prompt: The question/prompt to ask about the image
        monitor_number: Monitor to capture (1 = primary)
        model: OpenAI model to use
        save_screenshot: Whether to save the screenshot to disk
        screenshot_path: Path to save screenshot if save_screenshot is True

    Returns:
        Description from OpenAI Vision API
    """
    print(f"Capturing screenshot from monitor {monitor_number}...")
    image_bytes = capture_screenshot(monitor_number)

    if save_screenshot:
        with open(screenshot_path, "wb") as f:
            f.write(image_bytes)
        print(f"Screenshot saved to {screenshot_path}")

    print(f"Sending to OpenAI {model} for analysis...")
    description = describe_screenshot(image_bytes, prompt=prompt, model=model)

    return description


if __name__ == "__main__":
    # Check for API key
    if not os.environ.get("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY environment variable not set.")
        print("Set it with: export OPENAI_API_KEY='your-api-key'")
        exit(1)

    # Capture and describe the screen
    description = capture_and_describe(
        prompt="Describe what you see in this screenshot. What applications are open? What is the user doing?",
        save_screenshot=True
    )

    print("\n" + "=" * 50)
    print("SCREENSHOT DESCRIPTION:")
    print("=" * 50)
    print(description)
