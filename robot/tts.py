"""Offline speech synthesis: Piper (natural voices) or espeak-ng (robotic, tiny, many languages)."""

import logging
import shlex
import subprocess
import wave
from pathlib import Path

from .config import Config

log = logging.getLogger(__name__)


class Speaker:
    def __init__(self, config: Config):
        self.config = config
        self.out = config.audio_dir / "last.wav"
        self._piper = {}  # voice name -> loaded PiperVoice, loaded on first use

    def _piper_voice(self, name: str):
        if name not in self._piper:
            from piper import PiperVoice  # imported lazily: it's the slowest import here

            self._piper[name] = PiperVoice.load(str(self.config.models_dir / f"{name}.onnx"))
        return self._piper[name]

    def synthesize(self, text: str, language: str | None = None) -> Path:
        voices = self.config.voices
        engine, voice = voices.get(language) or next(iter(voices.values()))
        self.out.parent.mkdir(parents=True, exist_ok=True)
        if engine == "piper":
            with wave.open(str(self.out), "wb") as wav:
                self._piper_voice(voice).synthesize_wav(text, wav)
        else:
            subprocess.run(["espeak-ng", "-v", voice, "-w", str(self.out), text], check=True)
        return self.out

    def play(self, wav: Path) -> None:
        cmd = shlex.split(self.config.audio_player) + [str(wav)]
        flag = self.config.speaking_flag
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.touch()
        try:
            subprocess.run(cmd, check=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as e:
            # No speaker shouldn't stop the robot; the WAV file is still there to inspect.
            log.warning("couldn't play audio with %r (%s); file is %s", cmd[0], e, wav)
        finally:
            flag.unlink(missing_ok=True)

    def say(self, text: str, language: str | None = None) -> None:
        self.play(self.synthesize(text, language))
