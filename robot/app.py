"""Main loop: events (motion snapshots, voice transcripts) or camera samples -> local vision
-> Claude -> speech."""

import logging
import time
from datetime import datetime
from pathlib import Path

import cv2

from .brain import Brain
from .camera import Camera
from .config import Config
from .events import Event, pending, watch
from .faces import FaceDB
from .tts import Speaker
from .vision import Vision

log = logging.getLogger(__name__)


class Robot:
    def __init__(self, config: Config):
        self.config = config
        self.vision = Vision(config.models_dir, FaceDB(config.faces_db), config.min_confidence, config.face_threshold)
        self.brain = Brain(config)
        self.speaker = Speaker(config)
        # Scene signature -> when Claude last reacted to it.
        self._reactions: dict[frozenset[str], float] = {}
        self.camera: Camera | None = None  # sample mode only

    def handle_frame(self, frame, when: datetime, source: str, chatty: bool = True) -> None:
        """chatty=False (camera samples, one per second): log the scene only if Claude sees it."""
        level = logging.INFO if chatty else logging.DEBUG
        scene = self.vision.describe(frame)
        scene_text = scene.to_text()
        log.log(level, "%s at %s:\n%s", source, f"{when:%H:%M:%S}", scene_text)

        if not scene.objects and not scene.faces:
            log.log(level, "nothing recognized, not waking Claude")
            return

        # Already reacted to these same things recently: don't spend an API call on it.
        # Every recent scene counts, not just the last one, so a detection that flickers
        # between samples (your name / "unknown person") doesn't call Claude on each flip.
        now = time.monotonic()
        self._reactions = {s: t for s, t in self._reactions.items() if now - t < self.config.cooldown_s}
        signature = scene.signature()
        if signature in self._reactions:
            log.log(level, "same scene as %.0fs ago, skipping", now - self._reactions[signature])
            return
        self._reactions[signature] = now

        if not chatty:
            log.info("%s at %s:\n%s", source, f"{when:%H:%M:%S}", scene_text)
        self._respond(self.brain.react(scene_text, when, source))

    def handle_voice(self, event: Event, frame=None) -> None:
        """frame: what the camera sees; default is a current frame from the camera."""
        log.info('voice at %s [%s]: "%s"', f"{event.time:%H:%M:%S}", event.language, event.transcript)
        if frame is None:
            frame = self.camera_frame()
        scene_text = self.vision.describe(frame).to_text() if frame is not None else "- (camera not available)"
        self._respond(self.brain.react(scene_text, event.time, "voice", event.transcript, event.language, frame=frame))

    def camera_frame(self):
        """One current frame (sampled camera, or Motion's live stream), or None without a camera."""
        if self.camera is not None:
            return self.camera.frame()
        if not self.config.camera_stream:
            return None
        cap = cv2.VideoCapture(
            self.config.camera_stream,
            cv2.CAP_FFMPEG,
            [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 2000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 2000],
        )
        try:
            ok, frame = cap.read()
            return frame if ok else None
        finally:
            cap.release()

    def _respond(self, reaction) -> None:
        if reaction.speech:
            log.info("saying [%s]: %s", reaction.language, reaction.speech)
            self.speaker.say(reaction.speech, reaction.language)
        else:
            log.info("silent (%s)", reaction.note)

    def handle_event(self, event: Event) -> None:
        if event.transcript is not None:
            self.handle_voice(event)
            return
        frame = cv2.imread(str(event.picture))
        if frame is None:
            log.warning("can't read picture %s", event.picture)
            return
        self.handle_frame(frame, event.time, f"{event.source} event {event.event_id}")

    def run(self, once: bool = False) -> None:
        log.info("waiting for events in %s", self.config.spool_dir)
        if once:
            for event in pending(self.config.spool_dir):
                self._process(event)
        elif self.config.camera_mode == "sample":
            self._run_sampling()
        else:
            for event in watch(self.config.spool_dir):
                self._process(event)

    def _run_sampling(self) -> None:
        """Look at the camera every camera.sample_interval_s, and handle queued events (voice)
        in between. If looking takes longer than the interval, samples just run back to back."""
        self.camera = Camera(self.config.camera_device)
        log.info("sampling %s every %.1fs", self.config.camera_device, self.config.sample_interval_s)
        next_sample = time.monotonic()
        try:
            while True:
                for event in pending(self.config.spool_dir):
                    self._process(event)
                now = time.monotonic()
                if now < next_sample:
                    time.sleep(min(0.1, next_sample - now))
                    continue
                next_sample = now + self.config.sample_interval_s
                frame = self.camera.frame()
                if frame is None:
                    continue
                try:
                    self.handle_frame(frame, datetime.now().astimezone(), "camera sample", chatty=False)
                except Exception:
                    log.exception("failed to handle a camera sample")
        finally:
            self.camera.close()

    def _process(self, event: Event) -> None:
        try:
            self.handle_event(event)
        except Exception:
            log.exception("failed to handle %s", event.spool_file.name)
        finally:
            event.spool_file.unlink(missing_ok=True)
            if event.picture is not None:
                self._cleanup_snapshot(event.picture)

    def _cleanup_snapshot(self, picture: Path) -> None:
        # Only delete Motion's own snapshots, never a picture you pointed the robot at.
        snapshots = (self.config.data_dir / "snapshots").resolve()
        if not self.config.keep_snapshots and picture.resolve().parent == snapshots:
            picture.unlink(missing_ok=True)
