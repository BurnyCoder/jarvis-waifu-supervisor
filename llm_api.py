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
# DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "gpt-5-mini")
DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "gemma3:4b")

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


if __name__ == "__main__":
    response = complete_text("who are you?")
    print(response)
