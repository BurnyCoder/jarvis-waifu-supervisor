"""Prompt templates for LLM analysis."""

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

Keep your reason to 2 short sentences maximum.

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
