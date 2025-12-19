"""
Text-to-Speech module with support for multiple backends.

Set TTS_BACKEND environment variable to choose:
- "pyttsx3" (default): Local offline TTS
- "elevenlabs": ElevenLabs cloud TTS (requires ELEVENLABS_API_KEY)

Set ELEVENLABS_RANDOM_VOICE to pick random voices:
- "off" (default): Use ELEVENLABS_VOICE_ID
- "female": Random from female voice pool
- "male": Random from male voice pool
- "all": Random from all voices
"""

import os
import random

# Configuration
TTS_BACKEND = os.environ.get("TTS_BACKEND", "elevenlabs").lower()
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")

# Random voice mode: "off", "female", "male", or "all"
ELEVENLABS_RANDOM_VOICE = os.environ.get("ELEVENLABS_RANDOM_VOICE", "off").lower()

# Voice pools for random selection
FEMALE_VOICES = [
    "EXAVITQu4vr4xnSDxMaL",  # Sarah (formerly Bella) - soft, young, American
    "XB0fDUnXU5powFXDhCwa",  # Charlotte - sweet, feminine
    "cgSgspJ2msm6clMCkdW9",  # Jessica - young, expressive
    "21m00Tcm4TlvDq8ikWAM",  # Rachel - calm, neutral
    "AZnzlk1XvdvUeBnXmlld",  # Domi - strong, confident
]

MALE_VOICES = [
    "pNInz6obpgDQGcFmaJgB",  # Adam - deep, smooth, warm
    "onwK4e9ZLuTAKqWW03F9",  # Daniel - authoritative, British
    "ErXwobaYiN019PkySvjV",  # Antoni - smooth, expressive
    "TxGEqnHWrfWFTfGW9XjX",  # Josh - young, dynamic
    "VR6AewLTigWG4xSOukaG",  # Arnold - deep, confident
]

ALL_VOICES = FEMALE_VOICES + MALE_VOICES

# Default voice (used when random mode is off)
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")  # Sarah (formerly Bella)


def get_voice_id() -> str:
    """Get voice ID based on random mode setting."""
    if ELEVENLABS_RANDOM_VOICE == "female":
        return random.choice(FEMALE_VOICES)
    elif ELEVENLABS_RANDOM_VOICE == "male":
        return random.choice(MALE_VOICES)
    elif ELEVENLABS_RANDOM_VOICE == "all":
        return random.choice(ALL_VOICES)
    else:
        return ELEVENLABS_VOICE_ID


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
        voice_id = get_voice_id()

        audio = client.text_to_speech.convert(
            text=text,
            voice_id=voice_id,
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
