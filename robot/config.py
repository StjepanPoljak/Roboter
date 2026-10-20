"""All settings come from environment variables (see .env.example)."""

import os
from dataclasses import dataclass
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def parse_voices(spec: str) -> dict[str, tuple[str, str]]:
    """'en=piper:en_US-lessac-low,hr=espeak:hr' -> {'en': ('piper', 'en_US-lessac-low'), ...}"""
    voices = {}
    for item in filter(None, (part.strip() for part in spec.split(","))):
        language, _, engine_voice = item.partition("=")
        engine, _, voice = engine_voice.partition(":")
        voices[language.strip()] = (engine.strip(), voice.strip())
    return voices


@dataclass(frozen=True)
class Config:
    data_dir: Path
    models_dir: Path

    claude_backend: str  # api | cli | auto
    claude_model: str
    claude_effort: str
    dry_run: bool

    robot_name: str

    # language code -> (engine, voice); the first entry is the default
    voices: dict[str, tuple[str, str]]
    audio_player: str

    min_confidence: float
    face_threshold: float
    cooldown_s: float
    keep_snapshots: bool
    camera_stream: str

    wakeword: str
    wakeword_threshold: float
    whisper_model: str
    stt_languages: tuple[str, ...]
    recorder: str

    @property
    def spool_dir(self) -> Path:
        return self.data_dir / "spool"

    @property
    def faces_db(self) -> Path:
        return self.data_dir / "faces.npz"

    @property
    def audio_dir(self) -> Path:
        return self.data_dir / "audio"

    @property
    def speaking_flag(self) -> Path:
        """Exists while the robot talks, so the listener doesn't react to its own voice."""
        return self.audio_dir / "speaking"

    @classmethod
    def from_env(cls) -> "Config":
        pulse = bool(os.environ.get("PULSE_SERVER"))
        return cls(
            data_dir=Path(_env("ROBOT_DATA_DIR", "data")),
            models_dir=Path(_env("ROBOT_MODELS_DIR", "models")),
            claude_backend=_env("CLAUDE_BACKEND", "auto"),
            claude_model=_env("CLAUDE_MODEL", "claude-opus-5-5"),
            claude_effort=_env("CLAUDE_EFFORT", "low"),
            dry_run=_env("ROBOT_DRY_RUN", "0") == "1",
            robot_name=_env("ROBOT_NAME", "Robo"),
            voices=parse_voices(
                _env("TTS_VOICES", "en=piper:en_US-lessac-low,hr=piper:sr_RS-serbski_institut-medium")
            ),
            audio_player=_env("AUDIO_PLAYER", "paplay" if pulse else "aplay"),
            min_confidence=float(_env("ROBOT_MIN_CONFIDENCE", "0.5")),
            # SFace's recommended cosine-similarity threshold for "same person".
            face_threshold=float(_env("ROBOT_FACE_THRESHOLD", "0.363")),
            cooldown_s=float(_env("ROBOT_COOLDOWN_S", "60")),
            keep_snapshots=_env("ROBOT_KEEP_SNAPSHOTS", "0") == "1",
            camera_stream=_env("ROBOT_CAMERA_STREAM", ""),
            wakeword=_env("WAKEWORD", "hey_jarvis"),
            wakeword_threshold=float(_env("WAKEWORD_THRESHOLD", "0.5")),
            whisper_model=_env("WHISPER_MODEL", "base"),
            stt_languages=tuple(_env("STT_LANGUAGES", "en,hr").split(",")),
            recorder=_env(
                "AUDIO_RECORDER",
                "parec --raw --format=s16le --rate=16000 --channels=1"
                if pulse
                else "arecord -q -t raw -f S16_LE -r 16000 -c 1",
            ),
        )
