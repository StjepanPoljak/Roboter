"""Offline speech synthesis: Piper (natural voices) or espeak-ng (robotic, tiny, many languages).

Speech plays on the local speaker (speech.player), or with speech.output = "viomi" on the
rooted vacuum's own speaker over SSH. Usage: docs/TTS.md.
"""

import logging
import shlex
import subprocess
import wave
from math import gcd
from pathlib import Path

import numpy as np

from .config import Config

log = logging.getLogger(__name__)

# The vacuum's codec only feeds the speaker from a stereo stream; mono plays as silence
# (docs/VIOMI_ROBOT.md, "Audio"). 44.1 kHz sounds clean, 16 kHz slightly distorted.
VIOMI_RATE = 44100
# Speaker amplifier enable, active-low. RobotApp switches it on only around its prompts.
VIOMI_PLAY = (
    "cat > /tmp/robot_say.wav"
    " && echo 0 > /sys/class/gpio/gpio233/value"
    " && aplay -q /tmp/robot_say.wav;"
    " status=$?; echo 1 > /sys/class/gpio/gpio233/value; rm -f /tmp/robot_say.wav; exit $status"
)


def to_stereo_44k(src: Path, dst: Path) -> Path:
    """Rewrite a 16-bit WAV as 44.1 kHz stereo, the format the vacuum can play."""
    with wave.open(str(src), "rb") as wav:
        rate, channels = wav.getframerate(), wav.getnchannels()
        audio = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").reshape(-1, channels)
    mono = audio.astype(np.float32).mean(axis=1)
    if rate != VIOMI_RATE:
        from scipy.signal import resample_poly

        g = gcd(VIOMI_RATE, rate)
        mono = resample_poly(mono, VIOMI_RATE // g, rate // g)
    samples = np.clip(np.round(mono), -32768, 32767).astype("<i2")
    with wave.open(str(dst), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(VIOMI_RATE)
        wav.writeframes(np.repeat(samples, 2).tobytes())
    return dst


def viomi_ssh_command(config: Config) -> list[str]:
    key = config.viomi_dir / "id_ed25519"
    return [
        "ssh", "-F", "/dev/null", "-i", str(key),
        "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
        "-o", f"UserKnownHostsFile={config.viomi_dir / 'known_hosts'}",
        "-o", "StrictHostKeyChecking=accept-new", "-o", "LogLevel=ERROR",
        f"root@{config.viomi_host}", VIOMI_PLAY,
    ]


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

    def _play_local(self, wav: Path) -> None:
        cmd = shlex.split(self.config.audio_player) + [str(wav)]
        try:
            subprocess.run(cmd, check=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as e:
            # No speaker shouldn't stop the robot; the WAV file is still there to inspect.
            log.warning("couldn't play audio with %r (%s); file is %s", cmd[0], e, wav)

    def _play_viomi(self, wav: Path) -> None:
        if not self.config.viomi_host:
            log.warning("speech.output is viomi but speech.viomi_host isn't set; file is %s", wav)
            return
        converted = to_stereo_44k(wav, wav.with_name(wav.stem + "-viomi.wav"))
        try:
            with converted.open("rb") as audio:
                subprocess.run(viomi_ssh_command(self.config), stdin=audio, check=True, timeout=60,
                               capture_output=True)
        except subprocess.CalledProcessError as e:
            log.warning("couldn't play on the vacuum (ssh exit %s: %s); file is %s",
                        e.returncode, e.stderr.decode(errors="replace").strip(), converted)
        except (OSError, subprocess.SubprocessError) as e:
            log.warning("couldn't play on the vacuum (%s); file is %s", e, converted)

    def play(self, wav: Path) -> None:
        flag = self.config.speaking_flag
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.touch()
        try:
            if self.config.audio_output == "viomi":
                self._play_viomi(wav)
            else:
                self._play_local(wav)
        finally:
            flag.unlink(missing_ok=True)

    def say(self, text: str, language: str | None = None) -> None:
        self.play(self.synthesize(text, language))
