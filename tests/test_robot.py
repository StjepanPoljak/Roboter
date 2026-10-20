import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import numpy as np

from robot.events import pending, write_event
from robot.faces import FaceDB
from robot.vision import Detection, Face, Scene, horizontal_zone, size_hint

MODELS = Path(os.environ.get("ROBOT_MODELS_DIR", "models"))


class TextDescriptionTest(unittest.TestCase):
    def test_zones(self):
        self.assertEqual(horizontal_zone((0, 0, 10, 10), 500), "left")
        self.assertEqual(horizontal_zone((240, 0, 20, 10), 500), "center")
        self.assertEqual(horizontal_zone((490, 0, 10, 10), 500), "right")

    def test_size_hint(self):
        self.assertEqual(size_hint((0, 0, 400, 400), (480, 640)), "very close")
        self.assertEqual(size_hint((0, 0, 20, 20), (480, 640)), "far")

    def test_scene_text(self):
        scene = Scene(
            width=640,
            height=480,
            objects=[Detection("person", 0.9, (300, 100, 100, 300))],
            faces=[Face((320, 110, 60, 60), "Ana", 0.6), Face((10, 10, 20, 20), None, 0.1)],
        )
        text = scene.to_text()
        self.assertIn("person (conf 0.90), center, close", text)
        self.assertIn("recognized as Ana", text)
        self.assertIn("unknown person", text)
        self.assertEqual(Scene(640, 480).to_text(), "- nothing recognized")


class FaceDBTest(unittest.TestCase):
    def test_match_save_load_forget(self):
        rng = np.random.default_rng(0)
        ana, ivan = rng.normal(size=128), rng.normal(size=128)
        with tempfile.TemporaryDirectory() as tmp:
            db = FaceDB(Path(tmp) / "faces.npz")
            db.add("Ana", ana)
            db.add("Ivan", ivan)
            db.save()

            db = FaceDB(Path(tmp) / "faces.npz")
            self.assertEqual(db.people(), ["Ana", "Ivan"])
            name, score = db.match(ana + rng.normal(scale=0.1, size=128), threshold=0.363)
            self.assertEqual(name, "Ana")
            self.assertGreater(score, 0.9)
            self.assertIsNone(db.match(rng.normal(size=128), threshold=0.363)[0])

            self.assertEqual(db.remove("Ana"), 1)
            self.assertEqual(db.people(), ["Ivan"])


class SpoolTest(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            spool = Path(tmp)
            write_event(spool, source="motion", event_id="7", picture=Path("/data/snapshots/a.jpg"))
            write_event(spool, source="voice", transcript="što vidiš?", language="hr")
            (spool / "broken.json").write_text("{not json")
            events = pending(spool)
            self.assertEqual(len(events), 2)
            voice, motion = events  # voice events jump the queue
            self.assertEqual((voice.transcript, voice.language, voice.picture), ("što vidiš?", "hr", None))
            self.assertEqual(motion.event_id, "7")
            self.assertEqual(motion.picture, Path("/data/snapshots/a.jpg"))
            self.assertIsNone(motion.transcript)
            self.assertIsInstance(motion.time, datetime)
            self.assertFalse((spool / "broken.json").exists())


class VoiceTest(unittest.TestCase):
    def test_parse_voices(self):
        from robot.config import parse_voices

        self.assertEqual(
            parse_voices("en=piper:en_US-lessac-low, hr=espeak:hr"),
            {"en": ("piper", "en_US-lessac-low"), "hr": ("espeak", "hr")},
        )

    def test_croatian_neighbours_count_as_croatian(self):
        from robot.listener import Transcriber

        t = Transcriber.__new__(Transcriber)  # skip loading Whisper
        t.languages = ("en", "hr")
        self.assertEqual(t.pick_language([("sr", 0.3), ("bs", 0.25), ("en", 0.4)]), "hr")
        self.assertEqual(t.pick_language([("en", 0.9), ("de", 0.1)]), "en")
        self.assertEqual(t.pick_language([("de", 1.0)]), "en")  # unsupported -> first language

    def test_chime_and_wav_chunks(self):
        from robot.listener import CHUNK, chime, wav_chunks

        with tempfile.TemporaryDirectory() as tmp:
            path = chime(Path(tmp) / "chime.wav")
            chunks = list(wav_chunks(path, trailing_silence_s=1.0))
            self.assertTrue(all(len(c) == CHUNK for c in chunks))
            self.assertGreater(np.abs(chunks[0]).max(), 1000)
            self.assertEqual(np.abs(chunks[-1]).max(), 0)

    def test_prompt_includes_what_was_heard(self):
        from robot.brain import Brain
        from robot.config import Config

        os.environ["ROBOT_DRY_RUN"] = "1"
        brain = Brain(Config.from_env())
        reaction = brain.react("- person (conf 0.90), center, close", datetime(2026, 10, 20, 18, 0), "voice",
                               heard="what do you see?", heard_language="en")
        self.assertIsNone(reaction.speech)
        prompt = brain.build_prompt("- nothing recognized", datetime(2026, 10, 20, 18, 1), "voice", "hi", "en")
        self.assertIn('"hi"', prompt)
        self.assertIn('heard: "what do you see?"', prompt)


@unittest.skipUnless((MODELS / "ssd_mobilenet_v2.pb").exists(), "models not downloaded")
class ModelsLoadTest(unittest.TestCase):
    def test_blank_frame(self):
        from robot.vision import Vision

        with tempfile.TemporaryDirectory() as tmp:
            vision = Vision(MODELS, FaceDB(Path(tmp) / "faces.npz"), 0.5, 0.363)
            scene = vision.describe(np.zeros((480, 640, 3), dtype=np.uint8))
            self.assertEqual(scene.objects, [])


if __name__ == "__main__":
    unittest.main()
