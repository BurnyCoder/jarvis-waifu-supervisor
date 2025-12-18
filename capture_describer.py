"""
Capture Describer - Captures screen/webcam and sends to OpenAI Vision API for description.

Requirements:
    pip install openai pillow mss opencv-python python-dotenv

Usage:
    Create a .env file with OPENAI_API_KEY=your-api-key, then run:
    python capture_describer.py

    For local Gemma 3 model, set SCREENSHOT_MODEL=gemma3:4b
"""

import io
import os
import mss
import cv2
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


def get_webcam_count() -> int:
    """Get the number of available webcams."""
    count = 0
    for i in range(10):  # Check up to 10 potential webcam indices
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            count += 1
            cap.release()
        else:
            break
    return count


def capture_webcam(camera_index: int = 0) -> bytes:
    """
    Capture a photo from the webcam.

    Args:
        camera_index: Camera index (0 = default/primary webcam)

    Returns:
        PNG image bytes

    Raises:
        RuntimeError: If webcam cannot be opened or frame cannot be captured
    """
    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open webcam at index {camera_index}")

    try:
        # Capture a frame
        ret, frame = cap.read()
        if not ret:
            raise RuntimeError("Failed to capture frame from webcam")

        # Convert BGR (OpenCV default) to RGB for PIL
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Convert to PIL Image
        img = Image.fromarray(frame_rgb)

        # Convert to PNG bytes
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        return buffer.getvalue()
    finally:
        cap.release()


def stitch_images(images: list[bytes], labels: list[str] | None = None, scale_factors: list[float] | None = None) -> bytes:
    """
    Stitch multiple images into a single image (vertically stacked).

    Args:
        images: List of PNG image bytes
        labels: Optional labels to add above each image
        scale_factors: Optional scale factor for each image (e.g., 3.0 to make 3x bigger)

    Returns:
        PNG image bytes of the combined image
    """
    from PIL import ImageDraw, ImageFont

    pil_images = [Image.open(io.BytesIO(img_bytes)) for img_bytes in images]

    # Apply scale factors if provided
    if scale_factors:
        scaled_images = []
        for i, img in enumerate(pil_images):
            if i < len(scale_factors) and scale_factors[i] != 1.0:
                new_width = int(img.width * scale_factors[i])
                new_height = int(img.height * scale_factors[i])
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            scaled_images.append(img)
        pil_images = scaled_images

    # Calculate total dimensions
    max_width = max(img.width for img in pil_images)
    label_height = 30 if labels else 0
    total_height = sum(img.height + label_height for img in pil_images)

    # Create combined image
    combined = Image.new("RGB", (max_width, total_height), color=(30, 30, 30))

    y_offset = 0
    for i, img in enumerate(pil_images):
        # Add label if provided
        if labels and i < len(labels):
            draw = ImageDraw.Draw(combined)
            try:
                font = ImageFont.truetype("arial.ttf", 20)
            except (OSError, IOError):
                font = ImageFont.load_default()
            draw.text((10, y_offset + 5), labels[i], fill=(255, 255, 255), font=font)
            y_offset += label_height

        # Paste image (centered if narrower than max width)
        x_offset = (max_width - img.width) // 2
        combined.paste(img, (x_offset, y_offset))
        y_offset += img.height

    # Convert to PNG bytes
    buffer = io.BytesIO()
    combined.save(buffer, format="PNG")
    return buffer.getvalue()


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
    prompt: str = "Briefly describe what you see in this image.",
    monitor_number: int = 0,
    webcam: bool = False,
    camera_index: int = 0,
    model: str | None = None,
    save_results: bool = False
) -> str:
    """
    Convenience function to capture screenshot or webcam photo and get description.

    Args:
        prompt: The question/prompt to ask about the image
        monitor_number: Monitor to capture (0 = all monitors, 1 = primary, etc.)
        webcam: If True, capture from webcam instead of monitor
        camera_index: Webcam index to use (0 = default webcam)
        model: Model to use (defaults to SCREENSHOT_MODEL)
        save_results: Whether to save capture and analysis to results folders

    Returns:
        Description from OpenAI Vision API or local LLM
    """
    model = model or SCREENSHOT_MODEL

    if webcam:
        print(f"Capturing photo from webcam {camera_index}...")
        image_bytes = capture_webcam(camera_index)
    elif monitor_number == 0:
        print("Capturing screenshot from all monitors...")
        image_bytes = capture_screenshot(monitor_number)
    else:
        print(f"Capturing screenshot from monitor {monitor_number}...")
        image_bytes = capture_screenshot(monitor_number)

    backend = "local Ollama" if is_local_model(model) else "OpenAI"
    print(f"Sending to {backend} ({model}) for analysis...")
    description = describe_screenshot(image_bytes, prompt=prompt, model=model)

    if save_results:
        image_path, text_path = save_screenshot_with_analysis(image_bytes, description)
        print(f"Capture saved to {image_path}")
        print(f"Analysis saved to {text_path}")

    return description


def capture_all_and_describe(
    prompt: str = "Describe what you see. The image contains screenshots from monitors and webcam captures.",
    include_monitors: bool = True,
    include_webcam: bool = True,
    webcam_scale: float = 3.0,
    model: str | None = None,
    save_results: bool = False
) -> str:
    """
    Capture all monitors and webcam, stitch into one image, and get description.

    Args:
        prompt: The question/prompt to ask about the combined image
        include_monitors: Whether to include monitor screenshots
        include_webcam: Whether to include webcam capture
        webcam_scale: Scale factor for webcam image (default 3.0 = 3x bigger)
        model: Model to use (defaults to SCREENSHOT_MODEL)
        save_results: Whether to save capture and analysis to results folders

    Returns:
        Description from OpenAI Vision API or local LLM
    """
    model = model or SCREENSHOT_MODEL
    images = []
    labels = []
    scale_factors = []

    # Capture all monitors
    if include_monitors:
        monitor_count = get_monitor_count()
        for i in range(1, monitor_count + 1):
            print(f"Capturing monitor {i}...")
            images.append(capture_screenshot(i))
            labels.append(f"Monitor {i}")
            scale_factors.append(1.0)

    # Capture webcam
    if include_webcam:
        webcam_count = get_webcam_count()
        if webcam_count > 0:
            print("Capturing webcam...")
            try:
                images.append(capture_webcam(0))
                labels.append("Webcam")
                scale_factors.append(webcam_scale)
            except RuntimeError as e:
                print(f"Webcam capture failed: {e}")

    if not images:
        raise RuntimeError("No images captured")

    # Stitch all images together
    print("Stitching images together...")
    combined_image = stitch_images(images, labels, scale_factors)

    backend = "local Ollama" if is_local_model(model) else "OpenAI"
    print(f"Sending combined image to {backend} ({model}) for analysis...")
    description = describe_screenshot(combined_image, prompt=prompt, model=model)

    if save_results:
        image_path, text_path = save_screenshot_with_analysis(combined_image, description)
        print(f"Combined capture saved to {image_path}")
        print(f"Analysis saved to {text_path}")

    return description


if __name__ == "__main__":
    if not is_local_model(SCREENSHOT_MODEL) and not os.environ.get("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY environment variable not set.")
        print("Set it with: export OPENAI_API_KEY='your-api-key'")
        print("Or use local model: set SCREENSHOT_MODEL=gemma3:4b")
        exit(1)

    monitor_count = get_monitor_count()
    webcam_count = get_webcam_count()
    print(f"Detected {monitor_count} monitor(s), {webcam_count} webcam(s)")

    # Capture all monitors and webcam in one combined image
    description = capture_all_and_describe(
        prompt="Describe what's on screen and what you see in the webcam. What apps are open and what is the user doing?",
        save_results=True
    )

    print("\n" + "=" * 50)
    print("COMBINED ANALYSIS:")
    print("=" * 50)
    print(description)
