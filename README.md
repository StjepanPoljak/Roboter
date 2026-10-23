# Robot

A cheap home robot, built in small steps. Stage 1 is a camera with ears and a voice:

```
webcam ─► Motion ─► snapshot ─► OpenCV DNN: what is it? ─► text ─┐
                                └─ person? ─► YuNet + SFace: who? ┤
mic ─► wake word ("hey jarvis") ─► Whisper speech-to-text ─► text ┴─► Claude ─► Piper ─► speaker
```

**Images and audio never leave the machine.** Motion, object detection, face recognition,
wake word, speech-to-text and speech synthesis all run locally. Claude only gets a few lines of text, for example:

```
Event: motion event 14 at Tuesday 18:02:31

What the local detectors see now:
- person (conf 0.91), center, close
- cup (conf 0.62), right, far
- face: recognized as Stjepan (similarity 0.71), center, close

Recent history (oldest first):
- 17:58:10 saw: laptop (conf 0.80), center, medium distance -> stayed silent
```

Claude answers by calling a `speak` tool, or by staying silent.

## Quick start (laptop)

```sh
cp .env.example .env
make claude-token           # paste the token into .env (CLAUDE_CODE_OAUTH_TOKEN); see docs/CLAUDE_ACCESS.md
make build                  # first build downloads ~70 MB of models into the image
make test

# Try the pipeline on a photo, without the camera:
cp ~/Pictures/some-photo.jpg data/test.jpg
make analyze IMG=data/test.jpg     # what the detectors see (free, offline)
make say TEXT="hello, I am alive"  # check the speaker
make react IMG=data/test.jpg       # detectors + Claude + speech

# Teach it your face (stop `make run` first, since it holds the camera):
make enroll-cam NAME=Stjepan

# Talk to it: by typing first, then for real
make ask TEXT="what do you see?"
make listen-test            # say "hey jarvis", then a sentence; prints the transcript

# Run the full robot (camera + microphone):
make run                    # live camera view: http://localhost:8081
```

No token yet? Set `ROBOT_DRY_RUN=1` in `.env`. Everything else still runs, and the
log shows the prompt Claude would have received.

## Commands

All commands run inside the container (`make <target>`) or as `python -m robot <command>`.

| make | What it does |
|---|---|
| `run` | Camera + brain. Reacts to movement (Motion), or looks every second with `ROBOT_CAMERA=sample` in `.env`. |
| `run-nocam` | Brain only. Feed it pictures with `make simulate IMG=data/x.jpg`. |
| `analyze IMG=…` | Prints the scene description. No Claude, no speech. |
| `react IMG=…` | One full pass on one picture. |
| `enroll NAME=… IMGS="data/a.jpg data/b.jpg"` | Learns a face from photos. |
| `enroll-cam NAME=…` | Learns a face from 8 webcam samples. |
| `faces` | Lists known people. Remove one with `docker run … robot:dev faces --forget NAME`. |
| `say TEXT=… [IN=hr] [OUT=viomi]` | Tests speech output, locally or on the vacuum's speaker ([docs/TTS.md](docs/TTS.md)). |
| `ask TEXT=… [IN=hr]` | Talks to the robot by typing, as if you'd said the wake word. |
| `listen-test` | Wake word + speech-to-text only; prints what it heard. |
| `transcribe WAV=…` | Speech-to-text on a 16 kHz mono WAV. |
| `claude-token` | Creates the Claude Code token for `.env` (runs on the host). |
| `shell` | Bash inside the container. |

Pictures you pass to `make` targets must be inside `data/`, which is mounted at `/data`.

## Layout

```
robot/          Python package: app (main loop), vision, faces, listener, brain (Claude), tts, events
config/         motion.conf
scripts/        entrypoint, Motion hook, model download
tests/          unit tests (python -m unittest)
docs/           architecture, faces & privacy, wake word, hardware notes
data/           runtime state: spool, snapshots, faces.npz, audio (git-ignored)
```

## Docs

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): how the pieces fit, and how to extend them
- [docs/CLAUDE_ACCESS.md](docs/CLAUDE_ACCESS.md): subscription (`claude -p`) vs. API key
- [docs/FACES.md](docs/FACES.md): face enrollment, accuracy, privacy
- [docs/WAKEWORD.md](docs/WAKEWORD.md): wake word, custom name, speech-to-text
- [docs/TTS.md](docs/TTS.md): speech output, voices, playing on the vacuum's speaker
- [docs/HARDWARE.md](docs/HARDWARE.md): moving to the Raspberry Pi, cheap parts list
- [ROADMAP.md](ROADMAP.md): where this is going
- [VIOMI_ROOT.md](VIOMI_ROOT.md): rooting the Viomi vacuum (future body)
- [docs/VIOMI_ROBOT.md](docs/VIOMI_ROBOT.md): what's inside the rooted vacuum: hardware, software, API, lidar
