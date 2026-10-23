"""Ears: wake word -> record until silence -> local speech-to-text -> voice event in the spool.

Everything runs on-device. Until the wake word is heard, audio goes through the wake word
model in 80 ms chunks and is thrown away. Only the transcript of what you said after the
wake word is passed on (to the brain, and from there as text to Claude).
"""

import logging
import shlex
import subprocess
import time
import wave
from pathlib import Path
from typing import Iterator

import numpy as np

from .config import Config
from .events import write_event

log = logging.getLogger(__name__)

RATE = 16000
CHUNK = 1280  # 80 ms, the frame size openWakeWord expects

# Croatian is often detected as one of its close neighbours; count them as Croatian.
LANGUAGE_ALIASES = {"sr": "hr", "bs": "hr"}


def mic_chunks(command: str) -> Iterator[np.ndarray]:
    """16 kHz mono int16 chunks from a recorder command (parec on a desktop, arecord on a Pi)."""
    proc = subprocess.Popen(shlex.split(command), stdout=subprocess.PIPE)
    try:
        while True:
            data = proc.stdout.read(CHUNK * 2)
            if len(data) < CHUNK * 2:
                try:
                    code = proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    code = None
                raise RuntimeError(
                    f"recorder {command.split()[0]!r} stopped (exit code {code}); "
                    "is a microphone connected? Set listen.enabled = false in robot.toml to run without one"
                )
            yield np.frombuffer(data, dtype=np.int16)
    finally:
        proc.kill()


def wav_chunks(path: Path, trailing_silence_s: float = 2.0) -> Iterator[np.ndarray]:
    """The same chunks from a 16 kHz mono WAV file, for testing without a microphone."""
    with wave.open(str(path), "rb") as wav:
        if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (RATE, 1, 2):
            raise ValueError(f"{path} must be 16 kHz, mono, 16-bit")
        audio = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
    audio = np.concatenate([audio, np.zeros(int(trailing_silence_s * RATE), dtype=np.int16)])
    for start in range(0, len(audio) - CHUNK + 1, CHUNK):
        yield audio[start : start + CHUNK]


def chime(path: Path) -> Path:
    """A short two-tone 'I'm listening' sound, generated once."""
    if not path.exists():
        t = np.arange(int(0.09 * RATE)) / RATE
        tone = np.concatenate([np.sin(2 * np.pi * 660 * t), np.sin(2 * np.pi * 880 * t)])
        fade = np.minimum(1, np.minimum(np.arange(len(tone)), np.arange(len(tone))[::-1]) / 200)
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(RATE)
            wav.writeframes((tone * fade * 0.3 * 32767).astype(np.int16).tobytes())
    return path


class WakeWord:
    def __init__(self, config: Config):
        from openwakeword.model import Model

        oww = config.models_dir / "openwakeword"
        model = self.resolve(config)
        self.model = Model(
            wakeword_models=[str(model)],
            inference_framework="onnx",
            melspec_model_path=str(oww / "melspectrogram.onnx"),
            embedding_model_path=str(oww / "embedding_model.onnx"),
        )
        self.threshold = config.wakeword_threshold
        log.info("wake word model: %s (threshold %.2f)", model.name, self.threshold)

    @staticmethod
    def resolve(config: Config) -> Path:
        """A trained model in data/wakeword/<name>.onnx wins over a pretrained one."""
        candidates = [
            config.data_dir / "wakeword" / f"{config.wakeword}.onnx",
            *sorted((config.models_dir / "openwakeword").glob(f"{config.wakeword}_v*.onnx")),
            Path(config.wakeword),
        ]
        for path in candidates:
            if path.is_file():
                return path
        raise FileNotFoundError(f"no wake word model for {config.wakeword!r}; see docs/WAKEWORD.md")

    def score(self, chunk: np.ndarray) -> float:
        return max(self.model.predict(chunk).values())

    def reset(self) -> None:
        self.model.reset()


class Recorder:
    """Collects audio after the wake word until the speaker stops talking."""

    def __init__(self, config: Config, silence_s: float = 0.9, wait_s: float = 4.0, max_s: float = 15.0):
        from openwakeword.vad import VAD

        self.vad = VAD(str(config.models_dir / "openwakeword" / "silero_vad.onnx"))
        self.silence_chunks = int(silence_s * RATE / CHUNK)
        self.wait_chunks = int(wait_s * RATE / CHUNK)
        self.max_chunks = int(max_s * RATE / CHUNK)

    def record(self, chunks: Iterator[np.ndarray]) -> np.ndarray | None:
        """Returns the utterance, or None if nobody spoke within wait_s."""
        self.vad.reset_states()
        audio, started, quiet = [], False, 0
        for i, chunk in enumerate(chunks):
            audio.append(chunk)
            speech = self.vad.predict(chunk, frame_size=640) > 0.5
            if speech:
                started, quiet = True, 0
            elif started:
                quiet += 1
            if (started and quiet >= self.silence_chunks) or i >= self.max_chunks:
                break
            if not started and i >= self.wait_chunks:
                return None
        return np.concatenate(audio) if started else None


class Transcriber:
    def __init__(self, config: Config):
        from faster_whisper import WhisperModel

        baked = config.models_dir / "whisper"
        local = any(baked.glob(f"models--Systran--faster-whisper-{config.whisper_model}"))
        # Models not baked into the image are downloaded once into data/whisper.
        root = baked if local else config.data_dir / "whisper"
        self.model = WhisperModel(
            config.whisper_model, device="cpu", compute_type="int8",
            download_root=str(root), local_files_only=local,
        )
        self.languages = config.stt_languages
        log.info("speech-to-text: whisper %s, languages %s", config.whisper_model, ",".join(self.languages))

    def pick_language(self, probabilities: list[tuple[str, float]]) -> str:
        scores: dict[str, float] = {}
        for language, p in probabilities:
            language = LANGUAGE_ALIASES.get(language, language)
            scores[language] = scores.get(language, 0.0) + p
        return max(self.languages, key=lambda language: scores.get(language, 0.0))

    def transcribe(self, audio: np.ndarray) -> tuple[str, str]:
        samples = audio.astype(np.float32) / 32768
        language = self.languages[0]
        if len(self.languages) > 1:
            _, _, probabilities = self.model.detect_language(samples)
            language = self.pick_language(probabilities)
        segments, _ = self.model.transcribe(samples, language=language, beam_size=1, vad_filter=True)
        return " ".join(s.text.strip() for s in segments).strip(), language


class Listener:
    def __init__(self, config: Config):
        self.config = config
        self.wakeword = WakeWord(config)
        self.recorder = Recorder(config)
        self.transcriber = Transcriber(config)
        self.chime = chime(config.audio_dir / "chime.wav")

    def _play_chime(self) -> None:
        cmd = shlex.split(self.config.audio_player) + [str(self.chime)]
        try:
            subprocess.run(cmd, check=True, timeout=5)
        except (OSError, subprocess.SubprocessError) as e:
            log.warning("couldn't play chime: %s", e)

    def listen(self, chunks: Iterator[np.ndarray], once: bool = False, emit: bool = True) -> list[str]:
        """Wait for the wake word, then transcribe. Returns transcripts (useful for tests)."""
        log.info("listening for %r", self.config.wakeword)
        transcripts = []
        muted = False
        for chunk in chunks:
            # Don't listen to ourselves: skip audio while the robot is speaking.
            if self.config.speaking_flag.exists():
                muted = True
                continue
            if muted:
                self.wakeword.reset()
                muted = False

            score = self.wakeword.score(chunk)
            if score < self.wakeword.threshold:
                continue

            log.info("wake word (score %.2f)", score)
            if emit:
                self._play_chime()
            audio = self.recorder.record(chunks)
            self.wakeword.reset()
            if audio is None:
                log.info("nobody spoke after the wake word")
                continue
            start = time.perf_counter()
            text, language = self.transcriber.transcribe(audio)
            log.info("heard [%s] in %.1fs: %s", language, time.perf_counter() - start, text or "(nothing)")
            transcripts.append(text)
            if emit:
                write_event(self.config.spool_dir, source="voice", transcript=text, language=language)
            if once:
                break
        return transcripts
