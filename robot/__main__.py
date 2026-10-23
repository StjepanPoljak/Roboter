"""Command line: `python -m robot <command>`. Run with no arguments for help."""

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2

from .config import Config, load_or_exit
from .events import write_event
from .faces import FaceDB
from .vision import FaceRecognizer, Vision

log = logging.getLogger("robot")


def cmd_run(config: Config, args) -> None:
    from .app import Robot

    Robot(config).run(once=args.once)


def cmd_analyze(config: Config, args) -> None:
    vision = Vision(config.models_dir, FaceDB(config.faces_db), config.min_confidence, config.face_threshold)
    for path in args.images:
        frame = cv2.imread(str(path))
        if frame is None:
            print(f"{path}: can't read image")
            continue
        start = time.perf_counter()
        scene = vision.describe(frame)
        print(f"{path} ({(time.perf_counter() - start) * 1000:.0f} ms):\n{scene.to_text()}\n")


def cmd_react(config: Config, args) -> None:
    from .app import Robot

    frame = cv2.imread(str(args.image))
    if frame is None:
        sys.exit(f"{args.image}: can't read image")
    Robot(config).handle_frame(frame, datetime.now(), "manual test")


def cmd_simulate(config: Config, args) -> None:
    path = write_event(config.spool_dir, picture=args.image.resolve())
    print(f"queued {path}")


def _enroll_frame(recognizer: FaceRecognizer, db: FaceDB, name: str, frame) -> bool:
    faces = recognizer.find_faces(frame)
    if len(faces) == 0:
        return False
    db.add(name, recognizer.embed(frame, faces[0]))  # largest face
    return True


def cmd_enroll(config: Config, args) -> None:
    db = FaceDB(config.faces_db)
    recognizer = FaceRecognizer(config.models_dir, db, config.face_threshold)
    added = 0
    for path in args.images:
        frame = cv2.imread(str(path))
        if frame is None or not _enroll_frame(recognizer, db, args.name, frame):
            print(f"{path}: no face found, skipped")
            continue
        added += 1
    db.save()
    print(f"added {added} sample(s) for {args.name}; known people: {', '.join(db.people())}")


def cmd_enroll_cam(config: Config, args) -> None:
    db = FaceDB(config.faces_db)
    recognizer = FaceRecognizer(config.models_dir, db, config.face_threshold)
    cap = cv2.VideoCapture(args.device)
    if not cap.isOpened():
        sys.exit(f"can't open camera {args.device} (is the robot running and holding it?)")
    print(f"Look at the camera, {args.name}. Turn your head a little between samples.")
    added = 0
    try:
        while added < args.count:
            ok, frame = cap.read()
            if ok and _enroll_frame(recognizer, db, args.name, frame):
                added += 1
                print(f"  sample {added}/{args.count}")
                time.sleep(0.7)
    finally:
        cap.release()
    db.save()
    print(f"saved; known people: {', '.join(db.people())}")


def cmd_faces(config: Config, args) -> None:
    db = FaceDB(config.faces_db)
    if args.forget:
        print(f"removed {db.remove(args.forget)} sample(s) for {args.forget}")
        db.save()
    for person in db.people():
        print(f"{person}: {db.names.count(person)} sample(s)")


def cmd_say(config: Config, args) -> None:
    from dataclasses import replace

    from .tts import Speaker

    if args.output:
        config = replace(config, audio_output=args.output)
    Speaker(config).say(" ".join(args.text), args.lang)


def cmd_ask(config: Config, args) -> None:
    """Pretend someone said the wake word and then TEXT: no microphone needed."""
    from .app import Robot
    from .events import Event

    frame = None
    if args.image:
        frame = cv2.imread(str(args.image))
        if frame is None:
            sys.exit(f"{args.image}: can't read image")
    text = " ".join(args.text)
    event = Event("voice", "0", datetime.now().astimezone(), Path("-"), transcript=text, language=args.lang)
    Robot(config).handle_voice(event, frame)


def cmd_listen(config: Config, args) -> None:
    from .listener import Listener, mic_chunks, wav_chunks

    listener = Listener(config)
    if args.file:
        transcripts = listener.listen(wav_chunks(args.file), emit=False)
        print("transcripts:", transcripts)
    else:
        listener.listen(mic_chunks(config.recorder), once=args.once, emit=not args.test)


def cmd_transcribe(config: Config, args) -> None:
    import wave

    import numpy as np

    from .listener import Transcriber

    transcriber = Transcriber(config)
    for path in args.wavs:
        with wave.open(str(path), "rb") as wav:
            audio = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
        start = time.perf_counter()
        text, language = transcriber.transcribe(audio)
        print(f"{path} [{language}, {time.perf_counter() - start:.1f}s]: {text}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="robot", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging (shows Claude prompts)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run", help="process events (motion, voice) forever")
    p.add_argument("--once", action="store_true", help="process queued events, then exit")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("analyze", help="print what the local detectors see (no Claude, no speech)")
    p.add_argument("images", nargs="+", type=Path)
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("react", help="full pipeline on one image: detect, ask Claude, speak")
    p.add_argument("image", type=Path)
    p.set_defaults(func=cmd_react)

    p = sub.add_parser("simulate", help="queue an image as if Motion had captured it")
    p.add_argument("image", type=Path)
    p.set_defaults(func=cmd_simulate)

    p = sub.add_parser("enroll", help="teach a face from photos")
    p.add_argument("name")
    p.add_argument("images", nargs="+", type=Path)
    p.set_defaults(func=cmd_enroll)

    p = sub.add_parser("enroll-cam", help="teach a face from the webcam (stop the robot first)")
    p.add_argument("name")
    p.add_argument("--count", type=int, default=8)
    p.add_argument("--device", type=int, default=0)
    p.set_defaults(func=cmd_enroll_cam)

    p = sub.add_parser("faces", help="list known people")
    p.add_argument("--forget", metavar="NAME", help="delete everything stored for NAME")
    p.set_defaults(func=cmd_faces)

    p = sub.add_parser("say", help="test speech output")
    p.add_argument("--lang", help="language code from speech.voices, e.g. en or hr")
    p.add_argument("--output", choices=["local", "viomi"], help="override speech.output for this one")
    p.add_argument("text", nargs="+")
    p.set_defaults(func=cmd_say)

    p = sub.add_parser("ask", help="talk to the robot by typing: as if you'd said the wake word and TEXT")
    p.add_argument("--lang", default="en")
    p.add_argument("--image", type=Path, help="use this picture as what the camera sees")
    p.add_argument("text", nargs="+")
    p.set_defaults(func=cmd_ask)

    p = sub.add_parser("listen", help="wake word + speech-to-text; queues voice events for `run`")
    p.add_argument("--file", type=Path, help="use a 16 kHz mono WAV instead of the microphone")
    p.add_argument("--once", action="store_true", help="stop after the first utterance")
    p.add_argument("--test", action="store_true", help="only print what was heard, don't queue events")
    p.set_defaults(func=cmd_listen)

    p = sub.add_parser("transcribe", help="speech-to-text on WAV files (16 kHz mono)")
    p.add_argument("wavs", nargs="+", type=Path)
    p.set_defaults(func=cmd_transcribe)

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # The HTTP client logs every request at INFO; keep the robot's own log readable.
    logging.getLogger("httpx2").setLevel(logging.WARNING)
    args.func(load_or_exit(), args)


if __name__ == "__main__":
    main()
