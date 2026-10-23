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

    def test_viomi_conversion_is_44k_stereo(self):
        import wave

        from robot.tts import to_stereo_44k

        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / "piper.wav", Path(tmp) / "viomi.wav"
            tone = (8000 * np.sin(2 * np.pi * 440 * np.arange(16000) / 16000)).astype("<i2")
            with wave.open(str(src), "wb") as wav:  # 1 s of 16 kHz mono, like Piper's low voices
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes(tone.tobytes())
            to_stereo_44k(src, dst)
            with wave.open(str(dst), "rb") as wav:
                self.assertEqual((wav.getnchannels(), wav.getframerate()), (2, 44100))
                self.assertEqual(wav.getnframes(), 44100)
                out = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").reshape(-1, 2)
            np.testing.assert_array_equal(out[:, 0], out[:, 1])
            self.assertAlmostEqual(np.abs(out).max() / 8000, 1.0, delta=0.05)

    def test_viomi_output_without_host_doesnt_crash(self):
        from dataclasses import replace

        from robot.config import Config
        from robot.tts import Speaker

        with tempfile.TemporaryDirectory() as tmp:
            config = replace(Config.from_env(), data_dir=Path(tmp), audio_output="viomi", viomi_host="")
            with self.assertLogs("robot.tts", "WARNING"):
                Speaker(config).play(Path(tmp) / "missing.wav")
            self.assertFalse(config.speaking_flag.exists())

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


def lidar_frame(cmd: int, payload: bytes) -> bytes:
    body = bytes([0xAA]) + (8 + len(payload)).to_bytes(2, "big") + bytes([0x01, 0x61, cmd])
    body += len(payload).to_bytes(2, "big") + payload
    return body + (sum(body) & 0xFFFF).to_bytes(2, "big")


def scan_packet(start_deg: float, distances_mm: list[float]) -> bytes:
    payload = bytes([137]) + b"\x00\x10" + round(start_deg * 100).to_bytes(2, "big")
    for mm in distances_mm:
        payload += bytes([0x99]) + round(mm * 4).to_bytes(2, "big")
    return lidar_frame(0xAD, payload)


class LidarTest(unittest.TestCase):
    def test_frames_skip_garbage_and_bad_checksums(self):
        from robot.lidar import frames

        good = lidar_frame(0xAE, b"\x42")
        bad = bytearray(good)
        bad[-1] ^= 1
        self.assertEqual(list(frames(b"\x00\xaa" + bytes(bad) + good)), [(0xAE, b"\x42")])

    def test_real_frame_checksum(self):
        from robot.lidar import frames

        # A spin-up frame as captured from the robot's ttyS1.
        self.assertEqual(list(frames(bytes.fromhex("aa 00 09 01 61 ae 00 01 00 01 c4"))), [(0xAE, b"\x00")])

    def test_rotations_units_and_flags(self):
        from robot.lidar import rotations

        data = scan_packet(337.5, [999])  # partial turn before the first 0°: dropped
        for turn in range(2):
            for k in range(16):
                data += scan_packet(k * 22.5, [500, 0, 1000 + k] if k else [0x4000 / 4 + 250, 1500, 2000])
        data += scan_packet(0, [700])  # unfinished third turn: dropped
        turns = rotations(data)
        self.assertEqual(len(turns), 2)
        first = turns[0]
        self.assertAlmostEqual(first[0].angle, 7.5)  # flagged sample at 0° skipped
        self.assertAlmostEqual(first[0].distance, 1.5)  # 0.25 mm units
        self.assertNotIn(0.0, [s.distance for s in first])
        self.assertEqual(len(first), 2 + 15 * 2)

    def test_describe_sectors(self):
        from robot.lidar import Sample, describe

        turn = [Sample(10, 0.8, 99), Sample(350, 0.5, 99), Sample(90, 2.0, 99), Sample(180, 1.2, 99)]
        text = describe(turn)
        self.assertIn("- ahead: nearest 0.50 m", text)
        self.assertIn("- left: nearest 2.00 m", text)
        self.assertIn("- right: nothing within range", text)
        self.assertIn("- left: nearest 1.20 m", describe(turn, forward_deg=90))

    def test_strace_joins_resumed_reads(self):
        from robot.lidar import strace_streams

        log = [
            '753   09:43:53.819005 read(8, "\\xaa", 1) = 1',
            '753   09:43:53.819200 read(8,  <unfinished ...>',
            '746   09:43:53.819300 read(4, "\\xfa\\xfb", 2) = 2',
            '753   09:43:53.819894 <... read resumed> "\\x00\\t", 2) = 2',
            '755   09:43:53.820000 write(4, "\\x03", 1) = 1',
        ]
        streams = strace_streams(log)
        self.assertEqual(streams[("read", "8")], b"\xaa\x00\x09")
        self.assertEqual(streams[("read", "4")], b"\xfa\xfb")
        self.assertEqual(streams[("write", "4")], b"\x03")


@unittest.skipUnless((MODELS / "ssd_mobilenet_v2.pb").exists(), "models not downloaded")
class ModelsLoadTest(unittest.TestCase):
    def test_blank_frame(self):
        from robot.vision import Vision

        with tempfile.TemporaryDirectory() as tmp:
            vision = Vision(MODELS, FaceDB(Path(tmp) / "faces.npz"), 0.5, 0.363)
            scene = vision.describe(np.zeros((480, 640, 3), dtype=np.uint8))
            self.assertEqual(scene.objects, [])


class CooldownTest(unittest.TestCase):
    def test_flickering_face_doesnt_call_claude_each_time(self):
        from dataclasses import replace
        from unittest import mock

        from robot.app import Robot
        from robot.brain import Reaction
        from robot.config import Config

        known = Scene(640, 480, [Detection("person", 0.9, (0, 0, 10, 10))], [Face((0, 0, 5, 5), "Ana", 0.6)])
        unknown = Scene(640, 480, [Detection("person", 0.9, (0, 0, 10, 10))], [Face((0, 0, 5, 5), None, 0.2)])
        robot = Robot.__new__(Robot)  # skip loading models
        robot.config = replace(Config.from_env(), cooldown_s=60)
        robot._reactions = {}
        robot.vision = mock.Mock()
        robot.vision.describe.side_effect = [known, unknown, known, unknown, Scene(640, 480)]
        robot.brain = mock.Mock()
        robot.brain.react.return_value = Reaction(None, None, "test")
        for _ in range(5):
            robot.handle_frame(None, datetime.now(), "camera sample", chatty=False)
        self.assertEqual(robot.brain.react.call_count, 2)  # once per distinct scene


if __name__ == "__main__":
    unittest.main()
