"""
LLM API - Wrapper for OpenAI API calls.

Provides functions for text and vision completions.
"""

import base64
import os
from dotenv import load_dotenv
from openai import OpenAI

# Load environment variables from .env file
load_dotenv()

# Model configuration (can be overridden via OPENAI_MODEL env var)
DEFAULT_MODEL = "gpt-5-nano"
MODEL = os.environ.get("OPENAI_MODEL", DEFAULT_MODEL)


def get_client() -> OpenAI:
    """Get OpenAI client instance."""
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
    Send a text prompt to OpenAI and get a completion.

    Args:
        prompt: The user prompt
        model: OpenAI model to use (defaults to MODEL from env/config)
        max_completion_tokens: Maximum tokens in response
        system_prompt: Optional system prompt

    Returns:
        Completion text from the API
    """
    if model is None:
        model = MODEL

    client = get_client()

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
    Send an image to OpenAI Vision API and get a description.

    Args:
        image_bytes: Image data as bytes (PNG, JPEG, etc.)
        prompt: The question/prompt to ask about the image
        model: OpenAI model to use (defaults to MODEL from env/config)
        max_completion_tokens: Maximum tokens in response (includes reasoning tokens for GPT-5)
        detail: Image detail level - "low", "high", or "auto"
                - low: 512x512, faster, ~85 tokens
                - high: detailed crops, slower, more tokens
                - auto: let the model decide

    Returns:
        Description text from the API
    """
    if model is None:
        model = MODEL

    client = get_client()

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
