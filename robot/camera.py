"""The camera, opened by the brain itself (ROBOT_CAMERA=sample) instead of through Motion."""

import logging
import threading

import cv2

log = logging.getLogger(__name__)


class Camera:
    """Keeps the newest frame on hand. A thread reads every frame the camera delivers, so
    the driver's buffer never holds a stale one, and frame() returns the latest."""

    def __init__(self, device: str, width: int = 640, height: int = 480, fps: int = 10):
        self.device = device
        self._cap = cv2.VideoCapture(int(device) if device.isdigit() else device)
        if not self._cap.isOpened():
            raise RuntimeError(f"can't open camera {device}")
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self._cap.set(cv2.CAP_PROP_FPS, fps)  # same as Motion; more only costs CPU
        self._frame = None
        self._running = True
        self._thread = threading.Thread(target=self._read_forever, name="camera", daemon=True)
        self._thread.start()

    def _read_forever(self) -> None:
        while self._running:
            ok, frame = self._cap.read()
            if not ok:
                log.warning("camera %s stopped delivering frames", self.device)
                self._frame = None
                break
            self._frame = frame

    def frame(self):
        """The newest frame, or None before the first one or after the camera failed."""
        return self._frame

    def close(self) -> None:
        self._running = False
        self._thread.join(timeout=2)
        self._cap.release()
