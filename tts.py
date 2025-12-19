"""
Text-to-Speech module with support for multiple backends.

Set TTS_BACKEND environment variable to choose:
- "pyttsx3" (default): Local offline TTS
- "elevenlabs": ElevenLabs cloud TTS (requires ELEVENLABS_API_KEY)
"""

import os

# Configuration
TTS_BACKEND = os.environ.get("TTS_BACKEND", "elevenlabs").lower()
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")

# ElevenLabs Voice Options:
# Female (waifu):
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")  # Sarah (formerly Bella) - soft, young, American
# ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "XB0fDUnXU5powFXDhCwa")  # Charlotte - sweet, feminine
# ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "cgSgspJ2msm6clMCkdW9")  # Jessica - young, expressive
# ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # Rachel - calm, neutral
# ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "AZnzlk1XvdvUeBnXmlld")  # Domi - strong, confident
# Male (husbando):
# ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "pNInz6obpgDQGcFmaJgB")  # Adam - deep, smooth, warm
# ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "onwK4e9ZLuTAKqWW03F9")  # Daniel - authoritative, British
# ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "ErXwobaYiN019PkySvjV")  # Antoni - smooth, expressive
# ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "TxGEqnHWrfWFTfGW9XjX")  # Josh - young, dynamic
# ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "VR6AewLTigWG4xSOukaG")  # Arnold - deep, confident


def speak_pyttsx3(text: str):
    """Speak text using local pyttsx3 engine."""
    try:
        import pyttsx3
        engine = pyttsx3.init()
        engine.say(text)
        engine.runAndWait()
        engine.stop()
    except Exception as e:
        print(f"pyttsx3 TTS error: {e}")


def speak_elevenlabs(text: str):
    """Speak text using ElevenLabs API."""
    try:
        from elevenlabs.client import ElevenLabs
        from elevenlabs import play

        client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

        audio = client.text_to_speech.convert(
            text=text,
            voice_id=ELEVENLABS_VOICE_ID,
            model_id="eleven_multilingual_v2",
            output_format="mp3_44100_128",
        )

        # Use built-in play function
        play(audio)

    except Exception as e:
        print(f"ElevenLabs TTS error: {e}")
        # Fallback to pyttsx3
        print("Falling back to pyttsx3...")
        speak_pyttsx3(text)


def speak(text: str):
    """
    Speak text using the configured TTS backend.

    Set TTS_BACKEND env var to "pyttsx3" or "elevenlabs".
    """
    if TTS_BACKEND == "elevenlabs":
        if not ELEVENLABS_API_KEY:
            print("Warning: ELEVENLABS_API_KEY not set, falling back to pyttsx3")
            speak_pyttsx3(text)
        else:
            speak_elevenlabs(text)
    else:
        speak_pyttsx3(text)
