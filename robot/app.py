"""Main loop: events (motion snapshots, voice transcripts) -> local vision -> Claude -> speech."""

import logging
import time
from datetime import datetime
from pathlib import Path

import cv2

from .brain import Brain
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
        self._last_signature: frozenset[str] | None = None
        self._last_reaction = 0.0

    def handle_frame(self, frame, when: datetime, source: str) -> None:
        scene = self.vision.describe(frame)
        scene_text = scene.to_text()
        log.info("%s at %s:\n%s", source, f"{when:%H:%M:%S}", scene_text)

        if not scene.objects and not scene.faces:
            log.info("nothing recognized, not waking Claude")
            return

        # Same things in view as last time, and recently: don't spend an API call on it.
        signature = scene.signature()
        if signature == self._last_signature and time.monotonic() - self._last_reaction < self.config.cooldown_s:
            log.info("same scene as %.0fs ago, skipping", time.monotonic() - self._last_reaction)
            return
        self._last_signature = signature
        self._last_reaction = time.monotonic()

        self._respond(self.brain.react(scene_text, when, source))

    def handle_voice(self, event: Event) -> None:
        log.info('voice at %s [%s]: "%s"', f"{event.time:%H:%M:%S}", event.language, event.transcript)
        frame = self.camera_frame()
        scene_text = self.vision.describe(frame).to_text() if frame is not None else "- (camera not available)"
        self._respond(self.brain.react(scene_text, event.time, "voice", event.transcript, event.language))

    def camera_frame(self):
        """One current frame from Motion's live stream, or None without a camera."""
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
        events = pending(self.config.spool_dir) if once else watch(self.config.spool_dir)
        for event in events:
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
