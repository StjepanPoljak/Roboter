"""Local perception: turns a camera frame into a short text description.

Everything here runs on-device. Images never leave the machine; only the text
produced by Scene.to_text() is sent to Claude.
"""

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from .faces import FaceDB

# COCO ids used by the TensorFlow SSD models (1-based, with gaps).
COCO_LABELS = {
    1: "person", 2: "bicycle", 3: "car", 4: "motorcycle", 5: "airplane", 6: "bus", 7: "train",
    8: "truck", 9: "boat", 10: "traffic light", 11: "fire hydrant", 13: "stop sign",
    14: "parking meter", 15: "bench", 16: "bird", 17: "cat", 18: "dog", 19: "horse", 20: "sheep",
    21: "cow", 22: "elephant", 23: "bear", 24: "zebra", 25: "giraffe", 27: "backpack",
    28: "umbrella", 31: "handbag", 32: "tie", 33: "suitcase", 34: "frisbee", 35: "skis",
    36: "snowboard", 37: "sports ball", 38: "kite", 39: "baseball bat", 40: "baseball glove",
    41: "skateboard", 42: "surfboard", 43: "tennis racket", 44: "bottle", 46: "wine glass",
    47: "cup", 48: "fork", 49: "knife", 50: "spoon", 51: "bowl", 52: "banana", 53: "apple",
    54: "sandwich", 55: "orange", 56: "broccoli", 57: "carrot", 58: "hot dog", 59: "pizza",
    60: "donut", 61: "cake", 62: "chair", 63: "couch", 64: "potted plant", 65: "bed",
    67: "dining table", 70: "toilet", 72: "tv", 73: "laptop", 74: "mouse", 75: "remote",
    76: "keyboard", 77: "cell phone", 78: "microwave", 79: "oven", 80: "toaster", 81: "sink",
    82: "refrigerator", 84: "book", 85: "clock", 86: "vase", 87: "scissors", 88: "teddy bear",
    89: "hair drier", 90: "toothbrush",
}

Box = tuple[int, int, int, int]  # x, y, w, h in pixels


def horizontal_zone(box: Box, frame_width: int) -> str:
    """Where the box's center sits, from the camera's point of view."""
    x, _, w, _ = box
    center = (x + w / 2) / frame_width
    zones = ["left", "center-left", "center", "center-right", "right"]
    return zones[min(int(center * len(zones)), len(zones) - 1)]


def size_hint(box: Box, frame_shape: tuple[int, ...]) -> str:
    """A rough distance guess from how much of the frame the box covers."""
    _, _, w, h = box
    fraction = (w * h) / (frame_shape[0] * frame_shape[1])
    if fraction > 0.25:
        return "very close"
    if fraction > 0.08:
        return "close"
    if fraction > 0.02:
        return "medium distance"
    return "far"


@dataclass
class Detection:
    label: str
    confidence: float
    box: Box


@dataclass
class Face:
    box: Box
    name: str | None  # None = not recognized
    similarity: float


@dataclass
class Scene:
    width: int
    height: int
    objects: list[Detection] = field(default_factory=list)
    faces: list[Face] = field(default_factory=list)

    @property
    def people(self) -> list[str]:
        return sorted({f.name for f in self.faces if f.name})

    def signature(self) -> frozenset[str]:
        """What is in view, ignoring position. Used to skip repeated reactions."""
        return frozenset([d.label for d in self.objects] + [f"face:{f.name}" for f in self.faces])

    def to_text(self) -> str:
        shape = (self.height, self.width)
        lines = []
        for d in sorted(self.objects, key=lambda d: -d.confidence):
            lines.append(
                f"- {d.label} (conf {d.confidence:.2f}), "
                f"{horizontal_zone(d.box, self.width)}, {size_hint(d.box, shape)}"
            )
        for f in self.faces:
            who = f"recognized as {f.name} (similarity {f.similarity:.2f})" if f.name else "unknown person"
            lines.append(f"- face: {who}, {horizontal_zone(f.box, self.width)}, {size_hint(f.box, shape)}")
        return "\n".join(lines) if lines else "- nothing recognized"


class ObjectDetector:
    """SSD MobileNet v2 (COCO) through OpenCV's DNN module. Roughly 1-3 fps on a Pi 3B+."""

    def __init__(self, models_dir: Path, min_confidence: float):
        net = cv2.dnn.readNetFromTensorflow(
            str(models_dir / "ssd_mobilenet_v2.pb"), str(models_dir / "ssd_mobilenet_v2.pbtxt")
        )
        self.model = cv2.dnn_DetectionModel(net)
        self.model.setInputParams(size=(300, 300), swapRB=True)
        self.min_confidence = min_confidence

    def detect(self, frame: np.ndarray) -> list[Detection]:
        class_ids, confidences, boxes = self.model.detect(
            frame, confThreshold=self.min_confidence, nmsThreshold=0.4
        )
        return [
            Detection(COCO_LABELS.get(int(c), f"class {int(c)}"), float(conf), tuple(int(v) for v in box))
            for c, conf, box in zip(np.ravel(class_ids), np.ravel(confidences), boxes)
        ]


class FaceRecognizer:
    """YuNet finds faces, SFace turns each into a 128-number embedding, FaceDB names it."""

    def __init__(self, models_dir: Path, db: FaceDB, threshold: float):
        self.detector = cv2.FaceDetectorYN.create(
            str(models_dir / "face_detection_yunet.onnx"), "", (320, 320), score_threshold=0.8
        )
        self.recognizer = cv2.FaceRecognizerSF.create(str(models_dir / "face_recognition_sface.onnx"), "")
        self.db = db
        self.threshold = threshold

    def find_faces(self, frame: np.ndarray) -> np.ndarray:
        """Raw YuNet rows (x, y, w, h, 5 landmarks, score), largest face first."""
        self.detector.setInputSize((frame.shape[1], frame.shape[0]))
        _, faces = self.detector.detect(frame)
        if faces is None:
            return np.empty((0, 15), dtype=np.float32)
        return faces[np.argsort(-(faces[:, 2] * faces[:, 3]))]

    def embed(self, frame: np.ndarray, face_row: np.ndarray) -> np.ndarray:
        aligned = self.recognizer.alignCrop(frame, face_row)
        return self.recognizer.feature(aligned).flatten()

    def recognize(self, frame: np.ndarray) -> list[Face]:
        result = []
        for row in self.find_faces(frame):
            name, similarity = self.db.match(self.embed(frame, row), self.threshold)
            result.append(Face(tuple(int(v) for v in row[:4]), name, similarity))
        return result


class Vision:
    def __init__(self, models_dir: Path, faces_db: FaceDB, min_confidence: float, face_threshold: float):
        self.objects = ObjectDetector(models_dir, min_confidence)
        self.faces = FaceRecognizer(models_dir, faces_db, face_threshold)

    def describe(self, frame: np.ndarray) -> Scene:
        scene = Scene(width=frame.shape[1], height=frame.shape[0], objects=self.objects.detect(frame))
        # Face recognition only runs when the detector saw a person; it's the slower step.
        if any(d.label == "person" for d in scene.objects):
            scene.faces = self.faces.recognize(frame)
        return scene
