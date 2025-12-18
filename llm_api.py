"""
LLM API - Wrapper for OpenAI API calls.

Provides functions for text and vision completions.
Supports both OpenAI API and local models via Ollama.
"""

import base64
import os
from dotenv import load_dotenv
from openai import OpenAI

# Load environment variables from .env file
load_dotenv()

# Default model configuration
DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "gpt-5-nano")
# DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "gemma3:4b")

# Ollama base URL for local models
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")


def is_local_model(model: str) -> bool:
    """Check if a model name refers to a local Ollama model."""
    # Ollama models typically have format "name:tag" or known local prefixes
    return ":" in model or model.startswith(("gemma", "llama", "mistral", "phi", "qwen"))


def get_client(model: str) -> OpenAI:
    """
    Get OpenAI client instance based on model.

    Args:
        model: Model name (local models use Ollama, others use OpenAI)

    Returns:
        OpenAI client configured for either OpenAI API or local Ollama.
    """
    if is_local_model(model):
        return OpenAI(
            base_url=OLLAMA_BASE_URL,
            api_key="ollama"  # Ollama doesn't require a real API key
        )
    return OpenAI()


def encode_image_to_base64(image_bytes: bytes) -> str:
    """Encode image bytes to base64 string."""
    return base64.b64encode(image_bytes).decode("utf-8")


def complete_text(
    prompt: str,
    model: str | None = None,
    max_completion_tokens: int = 4000,
    system_prompt: str | None = None
) -> str:
    """
    Send a text prompt to OpenAI/local LLM and get a completion.

    Args:
        prompt: The user prompt
        model: Model to use (defaults to DEFAULT_MODEL, auto-detects local vs OpenAI)
        max_completion_tokens: Maximum tokens in response
        system_prompt: Optional system prompt

    Returns:
        Completion text from the API
    """
    model = model or DEFAULT_MODEL
    client = get_client(model)

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        max_completion_tokens=max_completion_tokens
    )

    return response.choices[0].message.content


def complete_vision(
    image_bytes: bytes,
    prompt: str = "Briefly describe what you see in this image.",
    model: str | None = None,
    max_completion_tokens: int = 4000,
    detail: str = "auto"
) -> str:
    """
    Send an image to OpenAI Vision API or local LLM and get a description.

    Args:
        image_bytes: Image data as bytes (PNG, JPEG, etc.)
        prompt: The question/prompt to ask about the image
        model: Model to use (defaults to DEFAULT_MODEL, auto-detects local vs OpenAI)
        max_completion_tokens: Maximum tokens in response (includes reasoning tokens for GPT-5)
        detail: Image detail level - "low", "high", or "auto"
                - low: 512x512, faster, ~85 tokens
                - high: detailed crops, slower, more tokens
                - auto: let the model decide

    Returns:
        Description text from the API
    """
    model = model or DEFAULT_MODEL
    client = get_client(model)

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
        max_completion_tokens=max_completion_tokens
    )

    return response.choices[0].message.content


def complete_vision_multi(
    images: list[bytes],
    prompt: str = "Describe what you see in these images.",
    model: str | None = None,
    max_completion_tokens: int = 4000,
    detail: str = "auto"
) -> str:
    """
    Send multiple images to OpenAI Vision API or local LLM and get a description.

    Args:
        images: List of image data as bytes (PNG, JPEG, etc.)
        prompt: The question/prompt to ask about the images
        model: Model to use (defaults to DEFAULT_MODEL, auto-detects local vs OpenAI)
        max_completion_tokens: Maximum tokens in response
        detail: Image detail level - "low", "high", or "auto" (OpenAI only)

    Returns:
        Description text from the API
    """
    model = model or DEFAULT_MODEL
    client = get_client(model)

    if is_local_model(model):
        # Ollama API format: images array with base64 strings in the message
        # Using the native Ollama format via OpenAI-compatible endpoint
        base64_images = [encode_image_to_base64(img) for img in images]

        # For Ollama, we need to use the native API format
        # The OpenAI-compatible endpoint doesn't support multiple images well
        # So we construct the message with multiple image_url entries
        content = [{"type": "text", "text": prompt}]
        for b64_img in base64_images:
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64_img}"}
            })

        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": content}],
            max_completion_tokens=max_completion_tokens
        )
    else:
        # OpenAI API format: multiple image_url entries in content array
        content = [{"type": "text", "text": prompt}]
        for img in images:
            base64_image = encode_image_to_base64(img)
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{base64_image}",
                    "detail": detail
                }
            })

        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": content}],
            max_completion_tokens=max_completion_tokens
        )

    return response.choices[0].message.content


def test_multi_image():
    """Test function for multi-image vision API."""
    import mss

    print("Capturing two screenshots for multi-image test...")

    # Capture two screenshots
    with mss.mss() as sct:
        monitor = sct.monitors[1]  # Primary monitor
        screenshot1 = sct.grab(monitor)
        img1_bytes = mss.tools.to_png(screenshot1.rgb, screenshot1.size)

    print("First screenshot captured. Press Enter to capture second...")
    input()

    with mss.mss() as sct:
        monitor = sct.monitors[1]
        screenshot2 = sct.grab(monitor)
        img2_bytes = mss.tools.to_png(screenshot2.rgb, screenshot2.size)

    print("Second screenshot captured. Sending to vision API...\n")

    # Test with local model (Gemma 3)
    print("=" * 50)
    print("Testing with Gemma 3 (local):")
    print("=" * 50)
    try:
        response = complete_vision_multi(
            images=[img1_bytes, img2_bytes],
            prompt="Compare these two screenshots. What changed between them?",
            model="gemma3:4b"
        )
        print(response)
    except Exception as e:
        print(f"Gemma 3 error: {e}")

    # Test with OpenAI model
    print("\n" + "=" * 50)
    print("Testing with GPT-5-nano (OpenAI):")
    print("=" * 50)
    try:
        response = complete_vision_multi(
            images=[img1_bytes, img2_bytes],
            prompt="Compare these two screenshots. What changed between them?",
            model="gpt-5-nano"
        )
        print(response)
    except Exception as e:
        print(f"GPT-5-nano error: {e}")


if __name__ == "__main__":
    import sys

    #if len(sys.argv) > 1 and sys.argv[1] == "test_multi":
    test_multi_image()
    # else:
    #     response = complete_text("who are you?")
    #     print(response)
