"""The Claude part: gets a text description of what the robot saw (and heard), decides what to say."""

import json
import logging
import os
import shutil
import subprocess
import tempfile
from collections import deque
from dataclasses import dataclass
from datetime import datetime

import anthropic

from .config import Config

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are {name}, a small home robot. Right now you are a stationary camera with a speaker \
and a microphone; wheels come later. You never see images or hear audio directly. Local \
models on the robot turn them into text for you:

- A motion detector wakes you up, and vision models describe what is in front of the \
camera: object labels, rough position (left/center/right), rough distance, and the names \
of people whose faces you were taught to recognize. Detections can be wrong, so treat \
low-confidence items with some doubt.
- When someone says your wake word, local speech-to-text transcribes what they said next. \
Transcripts can contain recognition errors; read them charitably.

How to react:
- {how_to_speak} Keep it short and natural: one or two sentences for motion events, a \
bit more only if someone asked a question that needs it.
- When someone speaks to you, always answer. Reply in the language they used, and set \
the language field accordingly. If the transcript is empty or makes no sense, briefly ask \
them to repeat.
- For motion events, greet recognized people by name and be polite to unknown people \
without being alarming. Use the recent history to avoid repeating yourself. Often the \
right reaction to motion is silence (a pet walking by, the same scene again). {how_to_stay_silent}
- You can't browse the internet, set timers or control devices yet. If asked, say so \
honestly instead of pretending."""


# How the two backends express "say this" vs. "stay silent".
API_REPLY = {
    "how_to_speak": "To say something, call the speak tool.",
    "how_to_stay_silent": "Then don't call any tool, just reply with the single word: silent.",
}
CLI_REPLY = {
    "how_to_speak": "To say something, answer with speak=true and the text.",
    "how_to_stay_silent": "Then answer with speak=false and an empty text.",
}


def reply_schema(languages: list[str]) -> dict:
    """Structured output for the CLI backend: the speak tool's arguments plus a speak flag."""
    return {
        "type": "object",
        "properties": {
            "speak": {"type": "boolean"},
            "text": {"type": "string"},
            "language": {"type": "string", "enum": languages},
        },
        "required": ["speak", "text", "language"],
        "additionalProperties": False,
    }


def speak_tool(languages: list[str]) -> dict:
    return {
        "name": "speak",
        "description": "Say something out loud through the robot's speaker.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "What to say."},
                "language": {
                    "type": "string",
                    "enum": languages,
                    "description": "Language of the text, so the right voice is used.",
                },
            },
            "required": ["text", "language"],
            "additionalProperties": False,
        },
    }


@dataclass
class Reaction:
    speech: str | None
    language: str | None
    note: str  # why there's no speech, or extra info for the log


def pick_backend(requested: str) -> str:
    """auto: the API when there's an API key, otherwise Claude Code if it's installed."""
    if requested != "auto":
        return requested
    if os.environ.get("ANTHROPIC_API_KEY") or not shutil.which("claude"):
        return "api"
    return "cli"


class Brain:
    def __init__(self, config: Config, history_size: int = 8):
        self.config = config
        self.backend = pick_backend(config.claude_backend)
        reply = CLI_REPLY if self.backend == "cli" else API_REPLY
        self.system = SYSTEM_PROMPT.format(name=config.robot_name, **reply)
        languages = list(config.voices)
        self.tools = [speak_tool(languages)]
        self.schema = json.dumps(reply_schema(languages))
        self.history: deque[str] = deque(maxlen=history_size)
        self.client = anthropic.Anthropic() if self.backend == "api" and not config.dry_run else None
        log.info("Claude backend: %s (%s)", self.backend, config.claude_model)

    def build_prompt(
        self, scene_text: str, when: datetime, source: str, heard: str | None, heard_language: str | None
    ) -> str:
        history = "\n".join(self.history) if self.history else "- (nothing yet)"
        parts = [f"Event: {source} at {when:%A %H:%M:%S}"]
        if heard is not None:
            parts.append(
                f"Someone called you and said (speech-to-text, language {heard_language}):\n"
                f'"{heard}"'
            )
        parts.append(f"What the local detectors see now:\n{scene_text}")
        parts.append(f"Recent history (oldest first):\n{history}")
        return "\n\n".join(parts)

    def react(
        self,
        scene_text: str,
        when: datetime,
        source: str = "motion",
        heard: str | None = None,
        heard_language: str | None = None,
    ) -> Reaction:
        prompt = self.build_prompt(scene_text, when, source, heard, heard_language)
        log.debug("prompt:\n%s", prompt)

        if self.config.dry_run:
            reaction = Reaction(None, None, "dry run, Claude not called")
            log.info("dry-run prompt:\n%s", prompt)
        elif self.backend == "cli":
            reaction = self._ask_claude_code(prompt)
        else:
            reaction = self._ask_claude(prompt)

        said = f'said "{reaction.speech}"' if reaction.speech else "stayed silent"
        if heard is not None:
            self.history.append(f'- {when:%H:%M:%S} heard: "{heard}" -> {said}')
        else:
            summary = "; ".join(line.lstrip("- ") for line in scene_text.splitlines())
            self.history.append(f"- {when:%H:%M:%S} saw: {summary} -> {said}")
        return reaction

    def _ask_claude(self, prompt: str) -> Reaction:
        try:
            response = self.client.beta.messages.create(
                model=self.config.claude_model,
                max_tokens=4000,
                system=self.system,
                tools=self.tools,
                output_config={"effort": self.config.claude_effort},
                # If a safety classifier declines, the API retries on a suitable fallback model.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.AuthenticationError:
            log.error("Claude rejected the credentials; set ANTHROPIC_API_KEY in .env")
            return Reaction(None, None, "authentication error")
        except anthropic.RateLimitError:
            log.warning("rate limited by the Claude API, skipping this event")
            return Reaction(None, None, "rate limited")
        except anthropic.APIStatusError as e:
            log.warning("Claude API error %s: %s", e.status_code, e.message)
            return Reaction(None, None, f"API error {e.status_code}")
        except anthropic.APIConnectionError:
            log.warning("can't reach the Claude API (offline?)")
            return Reaction(None, None, "offline")

        if response.stop_reason == "refusal":
            return Reaction(None, None, "refused")

        for block in response.content:
            if block.type == "tool_use" and block.name == "speak":
                text = str(block.input.get("text", "")).strip()
                if text:
                    return Reaction(text, block.input.get("language"), "")
        return Reaction(None, None, "chose silence")

    def _ask_claude_code(self, prompt: str) -> Reaction:
        """Headless Claude Code (`claude -p`) on your subscription, with every tool switched off."""
        cmd = [
            "claude", "-p",
            "--output-format", "json",
            "--no-session-persistence",
            "--tools", "",
            "--strict-mcp-config",
            "--setting-sources", "",
            "--model", self.config.claude_model,
            "--effort", self.config.claude_effort,
            "--system-prompt", self.system,
            "--json-schema", self.schema,
            prompt,
        ]
        try:
            # Without this, Claude Code would bill an API key instead of the subscription.
            env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
            # An empty working directory, so no project files or CLAUDE.md get pulled in.
            with tempfile.TemporaryDirectory() as cwd:
                proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=90)
        except FileNotFoundError:
            log.error("Claude Code isn't installed; set CLAUDE_BACKEND=api or rebuild the image")
            return Reaction(None, None, "claude not found")
        except subprocess.TimeoutExpired:
            log.warning("claude -p took longer than 90 s, skipping this event")
            return Reaction(None, None, "timeout")

        try:
            result = json.loads(proc.stdout)
        except json.JSONDecodeError:
            log.warning("claude -p failed (exit %s): %s", proc.returncode, (proc.stderr or proc.stdout).strip()[:300])
            return Reaction(None, None, "claude -p failed")
        if result.get("is_error"):
            # Login problems show up here, e.g. "Invalid API key · Please run /login".
            log.warning("claude -p error: %s (see `make claude-token`)", str(result.get("result"))[:300])
            return Reaction(None, None, "claude -p error")

        reply = result.get("structured_output") or {}
        text = str(reply.get("text", "")).strip()
        if reply.get("speak") and text:
            return Reaction(text, reply.get("language"), "")
        return Reaction(None, None, "chose silence")
