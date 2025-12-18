# Jarvis Waifu Supervisor

AI-powered productivity monitor that watches your screen and webcam to keep you focused on your tasks.

<img width="626" height="553" alt="image" src="https://github.com/user-attachments/assets/f15b511e-b4f6-4bb5-a164-2fc11e2252a8" />

## Features

- **Website/App Blocking**: Blocks distracting websites and kills specified applications during deep work sessions
- **AI Productivity Analysis**: Captures screenshots and webcam periodically, uses vision LLM to analyze if you're being productive
- **Text-to-Speech Notifications**: Speaks alerts when you're not productive, and encouragement when you're doing well
- **Web Frontend**: Simple browser UI to control modes (ON/OFF/BREAK) with confirmation phrases to prevent impulsive disabling
- **Break Timer**: Take timed breaks that automatically re-enable blocking when done

## Requirements

- Windows (for hosts file modification and process killing)
- Administrator privileges
- Python 3.10+
- OpenAI API key (or local Ollama for vision)

## Installation

```bash
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

### Standalone Productivity Monitor

```bash
python productivity_monitor.py
```

### Command Line Deep Work

```bash
python deepwork_monitor.py
```

## Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `SCREENSHOT_MODEL` | `gpt-4o` | Vision model for analysis |
| `CAPTURE_INTERVAL_SECONDS` | `5` | Seconds between captures |
| `CAPTURES_BEFORE_ANALYSIS` | `3` | Number of captures before sending to LLM |
| `GOOD_JOB_INTERVAL_MINUTES` | `1` | Minutes between "good job" encouragements |
| `OPENAI_API_KEY` | - | Required for OpenAI models |

## How It Works

1. **Capture**: Takes screenshots of all monitors and webcam image
2. **Stitch**: Combines images into a single labeled image
3. **Analyze**: Sends to vision LLM with your task description
4. **Notify**: Speaks TTS message if you're not productive
5. **Encourage**: Says "good job" periodically when you're productive

## Files

- `frontend.py` - Web UI for controlling deep work mode
- `deepwork_monitor.py` - Combined blocking + monitoring backend
- `productivity_monitor.py` - Standalone productivity monitoring
- `blocking.py` - Website/app blocking logic
- `capture_describer.py` - Screenshot and webcam capture
- `llm_api.py` - LLM API wrapper (OpenAI/Ollama)
- `deepwork.bat` - Windows launcher with admin privileges

## License

MIT
