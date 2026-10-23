"""All settings, in one place: robot.toml (see robot.example.toml), then ROBOT_<SECTION>_<KEY>
environment variables for one-off overrides (`docker run -e ROBOT_CAMERA_MODE=off`).

Secrets (CLAUDE_CODE_OAUTH_TOKEN, ANTHROPIC_API_KEY) stay in .env and are never read here.
Where things live in the container (ROBOT_DATA_DIR, ROBOT_MODELS_DIR, ROBOT_CONFIG) stays
in the environment too: that's the Dockerfile's business, not a setting.

`python -m robot.config` prints the effective settings; `python -m robot.config camera.mode`
prints one value (scripts/entrypoint.sh uses that).
"""

import logging
import os
import sys
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_FILE = "robot.toml"


def parse_voices(spec: str) -> dict[str, tuple[str, str]]:
    """'en=piper:en_US-lessac-low,hr=espeak:hr' -> {'en': ('piper', 'en_US-lessac-low'), ...}"""
    return _voices(
        {language.strip(): voice for language, _, voice in (item.partition("=") for item in _items(spec))}
    )


def _voices(table: dict[str, str]) -> dict[str, tuple[str, str]]:
    voices = {}
    for language, engine_voice in table.items():
        engine, _, voice = engine_voice.partition(":")
        voices[language] = (engine.strip(), voice.strip())
    return voices


def _items(spec: str) -> list[str]:
    return [part.strip() for part in spec.split(",") if part.strip()]


@dataclass(frozen=True)
class Config:
    data_dir: Path = Path("data")
    models_dir: Path = Path("models")

    claude_backend: str = "auto"  # api | cli | auto
    claude_model: str = "claude-opus-5-5"
    claude_effort: str = "low"
    dry_run: bool = False
    look_closely: bool = False  # may Claude ask for one real image (voice questions only)

    robot_name: str = "Robo"

    # language code -> (engine, voice); the first entry is the default
    voices: dict[str, tuple[str, str]] = field(
        default_factory=lambda: _voices({"en": "piper:en_US-lessac-low", "hr": "piper:sr_RS-serbski_institut-medium"})
    )
    audio_player: str = ""  # empty: paplay with PulseAudio, else aplay
    audio_output: str = "local"  # local | viomi (the rooted vacuum's own speaker, over SSH)
    viomi_host: str = ""

    camera_mode: str = "motion"  # motion | sample | off
    camera_device: str = "/dev/video0"  # sample mode: V4L2 device, index or stream URL
    sample_interval_s: float = 1.0
    camera_stream: str = ""  # Motion's live stream, set by scripts/entrypoint.sh

    min_confidence: float = 0.5
    # SFace's recommended cosine-similarity threshold for "same person".
    face_threshold: float = 0.363
    cooldown_s: float = 60.0
    keep_snapshots: bool = False

    listen: bool = True
    wakeword: str = "hey_jarvis"
    wakeword_threshold: float = 0.5
    whisper_model: str = "base"
    stt_languages: tuple[str, ...] = ("en", "hr")
    recorder: str = ""  # empty: parec with PulseAudio, else arecord

    def __post_init__(self):
        pulse = bool(os.environ.get("PULSE_SERVER"))
        if not self.audio_player:
            object.__setattr__(self, "audio_player", "paplay" if pulse else "aplay")
        if not self.recorder:
            recorder = (
                "parec --raw --format=s16le --rate=16000 --channels=1"
                if pulse
                else "arecord -q -t raw -f S16_LE -r 16000 -c 1"
            )
            object.__setattr__(self, "recorder", recorder)

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
    def viomi_dir(self) -> Path:
        """SSH key and known_hosts for reaching the vacuum (docs/TTS.md)."""
        return self.data_dir / "viomi"

    @property
    def speaking_flag(self) -> Path:
        """Exists while the robot talks, so the listener doesn't react to its own voice."""
        return self.audio_dir / "speaking"

    @classmethod
    def load(cls, path: Path | None = None, environ: dict[str, str] | None = None) -> "Config":
        """Defaults, then robot.toml (or ROBOT_CONFIG), then ROBOT_<SECTION>_<KEY> variables."""
        environ = os.environ if environ is None else environ
        path = Path(path or environ.get("ROBOT_CONFIG", DEFAULT_FILE))
        values: dict[str, object] = {}
        if path.exists():
            with path.open("rb") as f:
                values.update(_from_file(tomllib.load(f), path))
        values.update(_from_environ(environ))
        _warn_about_old_names(environ)
        return cls(
            data_dir=Path(environ.get("ROBOT_DATA_DIR", "data")),
            models_dir=Path(environ.get("ROBOT_MODELS_DIR", "models")),
            **values,
        )


# The file layout: [section] key -> Config field.
LAYOUT: dict[str, dict[str, str]] = {
    "claude": {
        "backend": "claude_backend",
        "model": "claude_model",
        "effort": "claude_effort",
        "dry_run": "dry_run",
        "look_closely": "look_closely",
    },
    "robot": {"name": "robot_name"},
    "speech": {"voices": "voices", "player": "audio_player", "output": "audio_output", "viomi_host": "viomi_host"},
    "camera": {
        "mode": "camera_mode",
        "device": "camera_device",
        "sample_interval_s": "sample_interval_s",
        "stream": "camera_stream",
    },
    "vision": {
        "min_confidence": "min_confidence",
        "face_threshold": "face_threshold",
        "cooldown_s": "cooldown_s",
        "keep_snapshots": "keep_snapshots",
    },
    "listen": {
        "enabled": "listen",
        "wakeword": "wakeword",
        "threshold": "wakeword_threshold",
        "whisper_model": "whisper_model",
        "languages": "stt_languages",
        "recorder": "recorder",
    },
}
_FIELD_TYPES = {f.name: f.type for f in fields(Config)}
CHOICES = {
    "claude_backend": ("auto", "api", "cli"),
    "claude_effort": ("low", "medium", "high"),
    "audio_output": ("local", "viomi"),
    "camera_mode": ("motion", "sample", "off"),
}


def _check(field: str, value, where: str):
    """Coerce a value from the file or the environment to the field's type, or explain why not."""
    kind = _FIELD_TYPES[field]
    try:
        if field == "voices":
            value = parse_voices(value) if isinstance(value, str) else _voices(dict(value))
        elif kind is bool:
            if isinstance(value, str):
                if value.lower() not in ("1", "0", "true", "false", "yes", "no"):
                    raise ValueError
                value = value.lower() in ("1", "true", "yes")
            elif not isinstance(value, bool):
                raise ValueError
        elif kind is float:
            if isinstance(value, bool):
                raise ValueError
            value = float(value)
        elif field == "stt_languages":
            value = tuple(_items(value) if isinstance(value, str) else (str(v) for v in value))
        elif not isinstance(value, str):
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError(f"{where}: {value!r} isn't a valid value") from None
    if field in CHOICES and value not in CHOICES[field]:
        raise ValueError(f"{where}: {value!r} isn't one of {', '.join(CHOICES[field])}")
    return value


def _from_file(data: dict, path: Path) -> dict[str, object]:
    values = {}
    for section, table in data.items():
        if section not in LAYOUT or not isinstance(table, dict):
            raise ValueError(f"{path}: unknown section [{section}] (known: {', '.join(LAYOUT)})")
        for key, value in table.items():
            if key not in LAYOUT[section]:
                raise ValueError(f"{path}: unknown setting {section}.{key} (known: {', '.join(LAYOUT[section])})")
            field = LAYOUT[section][key]
            values[field] = _check(field, value, f"{path}: {section}.{key}")
    return values


def env_name(section: str, key: str) -> str:
    return f"ROBOT_{section}_{key}".upper()


def _from_environ(environ) -> dict[str, object]:
    values = {}
    for section, table in LAYOUT.items():
        for key, field in table.items():
            name = env_name(section, key)
            if name in environ:
                values[field] = _check(field, environ[name], name)
    return values


# Before robot.toml, settings were environment variables with these names.
OLD_NAMES = {
    "CLAUDE_BACKEND": "claude.backend",
    "CLAUDE_MODEL": "claude.model",
    "CLAUDE_EFFORT": "claude.effort",
    "ROBOT_DRY_RUN": "claude.dry_run",
    "ROBOT_NAME": "robot.name",
    "TTS_VOICES": "speech.voices",
    "AUDIO_PLAYER": "speech.player",
    "AUDIO_OUTPUT": "speech.output",
    "VIOMI_HOST": "speech.viomi_host",
    "ROBOT_CAMERA": "camera.mode",
    "ROBOT_MOTION": "camera.mode",
    "ROBOT_SAMPLE_INTERVAL_S": "camera.sample_interval_s",
    "ROBOT_MIN_CONFIDENCE": "vision.min_confidence",
    "ROBOT_FACE_THRESHOLD": "vision.face_threshold",
    "ROBOT_COOLDOWN_S": "vision.cooldown_s",
    "ROBOT_KEEP_SNAPSHOTS": "vision.keep_snapshots",
    "ROBOT_LISTEN": "listen.enabled",
    "WAKEWORD": "listen.wakeword",
    "WAKEWORD_THRESHOLD": "listen.threshold",
    "WHISPER_MODEL": "listen.whisper_model",
    "STT_LANGUAGES": "listen.languages",
    "AUDIO_RECORDER": "listen.recorder",
}


def _warn_about_old_names(environ) -> None:
    for name, setting in OLD_NAMES.items():
        if name in environ:
            log.warning("%s is ignored now; set %s in robot.toml (robot.example.toml)", name, setting)


def lookup(config: Config, setting: str):
    """'camera.mode' -> config.camera_mode"""
    section, _, key = setting.partition(".")
    try:
        return getattr(config, LAYOUT[section][key])
    except KeyError:
        raise KeyError(f"unknown setting {setting!r}") from None


def show(value) -> str:
    """A value the way robot.toml would spell it."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dict):
        return "{ " + ", ".join(f'{k} = "{e}:{v}"' for k, (e, v) in value.items()) + " }"
    if isinstance(value, tuple):
        return "[" + ", ".join(f'"{v}"' for v in value) + "]"
    if isinstance(value, str):
        return f'"{value}"'
    return str(value)


def load_or_exit() -> Config:
    """For command lines: a mistake in robot.toml is a message, not a traceback."""
    try:
        return Config.load()
    except (ValueError, tomllib.TOMLDecodeError) as e:
        sys.exit(f"config: {e}")


def main(argv: list[str]) -> None:
    # Looking up one value (scripts/entrypoint.sh): the brain warns about old names itself.
    logging.basicConfig(level=logging.ERROR if argv else logging.WARNING, format="%(levelname)s: %(message)s")
    config = load_or_exit()
    if argv:  # one raw value, for shell scripts: true/false, numbers, plain strings
        value = lookup(config, argv[0])
        print(show(value) if not isinstance(value, str) else value)
        return
    for section, table in LAYOUT.items():
        print(f"[{section}]")
        for key, field in table.items():
            print(f"{key} = {show(getattr(config, field))}")
        print()


if __name__ == "__main__":
    main(sys.argv[1:])
