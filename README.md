# Jarvis Waifu Supervisor

AI-powered productivity monitor that watches your screen and webcam to keep you focused on your tasks. Deep work loop with Vision LLM and TTS, blocking websites and apps.

<img width="626" height="553" alt="image" src="https://github.com/user-attachments/assets/f15b511e-b4f6-4bb5-a164-2fc11e2252a8" />

## Features

- **Website/App Blocking**: Blocks 70+ distracting websites (social media, news, forums) and kills applications (Discord, Telegram, Steam) during deep work sessions
- **AI Productivity Analysis**: Captures screenshots and webcam periodically, uses vision LLM to analyze if you're being productive with task-specific prompts (coding, ML training, debugging, learning, etc.)
- **Text-to-Speech Notifications**: Speaks alerts when you're not productive, and encouragement when you're doing well. Supports ElevenLabs (10 voices with random mode) or pyttsx3 (local/offline)
- **Web Frontend**: Simple browser UI to control modes (ON/OFF/BREAK) with confirmation phrases to prevent impulsive disabling. Shows live productivity analysis and countdown timers
- **Break Timer**: Take timed breaks that automatically re-enable blocking when done

## Requirements

- Windows (for hosts file modification and process killing)
- Administrator privileges
- Python 3.10+
- OpenAI API key (or local Ollama for vision)

## Installation

```bash
# Install ffmpeg (required for ElevenLabs audio playback)
winget install --id Gyan.FFmpeg -e

pip install -r requirements.txt
```

## Usage

### Web Frontend (Recommended)

Run with administrator privileges:

```bash
deepwork.bat
```

Or manually:

```bash
python frontend.py
```

Then open http://localhost:5000 in your browser.

### Command Line Deep Work

```bash
python deepwork_monitor.py
```

## Configuration

Environment variables:

### AI/LLM

| Variable | Default | Description |
|----------|---------|-------------|
| `SCREENSHOT_MODEL` | `gpt-5-nano` | Vision model for analysis |
| `OPENAI_API_KEY` | - | Required for OpenAI models |
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` | Local Ollama server URL |

### Capture/Analysis

| Variable | Default | Description |
|----------|---------|-------------|
| `CAPTURE_INTERVAL_SECONDS` | `60` | Seconds between captures |
| `CAPTURES_BEFORE_ANALYSIS` | `5` | Number of captures before sending to LLM |
| `SEND_IMAGES_SEPARATELY` | `false` | Send images individually instead of stitching |

### Text-to-Speech

| Variable | Default | Description |
|----------|---------|-------------|
| `TTS_BACKEND` | `pyttsx3` | TTS engine: `pyttsx3` (local) or `elevenlabs` (cloud) |
| `ELEVENLABS_API_KEY` | - | Required if using ElevenLabs |
| `ELEVENLABS_VOICE_ID` | `EXAVITQu4vr4xnSDxMaL` | Default voice (Sarah) |
| `ELEVENLABS_RANDOM_VOICE` | `all` | Random voice mode: `off`, `female`, `male`, or `all` |

## How It Works

1. **Capture**: Takes screenshots of all monitors and webcam image
2. **Stitch**: Combines images into a single labeled image
3. **Analyze**: Sends to vision LLM with your task description
4. **Speak**: TTS feedback - encouragement when productive, gentle nudges when not

## Files

### Main Scripts

- `frontend.py` - Flask web UI for controlling deep work mode
- `deepwork_monitor.py` - CLI interface for deep work with monitoring
- `deepwork.bat` - Windows launcher with admin privileges

### core/ Package

- `core/__init__.py` - Package exports for clean imports
- `core/config.py` - Blocked websites/apps list, confirmation phrase, intervals
- `core/hosts.py` - Windows hosts file manipulation
- `core/processes.py` - Application process killing
- `core/utils.py` - Admin privileges, DNS flushing utilities
- `core/workers.py` - Thread workers for process killing, monitoring, and break timer
- `core/monitoring.py` - Productivity monitoring helpers (capture, analysis, TTS)
- `core/capture_describer.py` - Screenshot and webcam capture, image stitching
- `core/llm_api.py` - LLM API wrapper (OpenAI Responses API / Ollama)
- `core/tts.py` - Text-to-speech with ElevenLabs and pyttsx3 backends
- `core/save_results.py` - Save captured images and analysis to disk
- `core/prompts.py` - Productivity analysis prompt templates
- `core/templates.py` - Frontend HTML template
- `core/deepwork.py` - DeepWorkWithMonitoring session manager class

## License

MIT
