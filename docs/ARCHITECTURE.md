# Architecture

## Data flow

```
┌──────────── container ─────────────────────────────────────────────────────────────┐
│                                                                                     │
│  Motion ──(on_picture_save)──► scripts/motion_hook.sh ──► /data/spool/*.json         │
│    │ saves /data/snapshots/*.jpg                                │                    │
│                                                                 ▼                    │
│                                    robot/app.py  Robot.run(): watch spool            │
│                                        │                                             │
│                     robot/vision.py    ▼                                             │
│                     ObjectDetector (SSD MobileNet v2) ─► person? ─► FaceRecognizer   │
│                                        │                       (YuNet + SFace + DB)  │
│                                        ▼                                             │
│                     Scene.to_text()  "- person (conf 0.91), center, close …"         │
│                                        │                                             │
│                     cooldown check ────┤ (same scene recently? stop here)            │
│                                        ▼                                             │
│                     robot/brain.py ── HTTPS (text only) ──► Claude API               │
│                                        │  ◄── speak("Hi Stjepan!") or silence        │
│                                        ▼                                             │
│                     robot/tts.py   Piper → data/audio/last.wav → paplay/aplay        │
│                                                                                     │
│  robot/listener.py (python -m robot listen)                                         │
│    mic → openWakeWord → Silero VAD → Whisper → /data/spool/*-voice-*.json           │
│    voice events skip the queue and the cooldown; the brain grabs a fresh frame      │
│    from Motion's stream (ROBOT_CAMERA_STREAM) so Claude knows what's in view        │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

## Why it's built this way

**Motion decides when, the brain decides what.** Motion is a mature C program that's very
cheap at "did pixels change?". The neural networks only run on the one snapshot per event,
which is what makes a Pi 3B+ viable.

**A spool directory instead of a message queue.** The hook writes a JSON file; the brain
reads and deletes it. It survives restarts, needs no extra services, and you can test it
with `make simulate`. Files are written to a temp name and renamed, so the brain never sees
half a file.

**Text only to Claude.** Privacy, and cost: a scene description is about 100 tokens, an
image is about 1000+. The downside is that Claude knows only the 80 COCO classes plus the
names of enrolled faces. Stage 4 in the roadmap adds an opt-in `look_closely` tool.

**Claude's reply is a tool call.** `speak(text, language)` means "say this, with the
voice for that language"; no tool call means silence. Movement tools will be added the same way later.

**Stateless API calls with a local history.** Each event is one API request. The last 8
events and replies are included as text, so Claude doesn't greet you twice in a minute,
without keeping a growing conversation.

**Two cost brakes.** Events with nothing recognized never reach Claude. An unchanged
scene (same labels and same names) within `ROBOT_COOLDOWN_S` is skipped.

## Models

| Purpose | Model | Size | Source |
|---|---|---|---|
| Objects | SSD MobileNet v2 COCO (TensorFlow) | 67 MB | TF model zoo + OpenCV pbtxt |
| Face detection | YuNet (2023mar) | 0.2 MB | OpenCV zoo |
| Face recognition | SFace (2021dec) | 37 MB | OpenCV zoo |
| Speech (en) | Piper `en_US-lessac-low` | 60 MB | rhasspy/piper-voices |
| Speech (hr) | Piper `sr_RS-serbski_institut-medium` | 60 MB | rhasspy/piper-voices |
| Wake word | openWakeWord `hey_jarvis` + feature models | 5 MB | openWakeWord releases |
| Voice activity | Silero VAD | 2 MB | openWakeWord releases |
| Speech-to-text | Whisper `base` (CTranslate2, int8) | 145 MB | Systran/faster-whisper-base |

All of them are downloaded at image build time by `scripts/download_models.sh`.

## Claude call

`robot/brain.py`, two backends (docs/CLAUDE_ACCESS.md):

- `cli`: `claude -p` with all tools off, the robot's system prompt and a JSON schema
  `{speak, text, language}`; runs on your Claude subscription.
- `api`: the Anthropic SDK with one strict `speak(text, language)` tool and server-side
  refusal fallbacks (`fallbacks="default"`).

Both use `CLAUDE_MODEL` (default `claude-opus-5-5`) at `effort=low`, since it's a short
judgment call. Errors are logged and the event is skipped; the robot never crashes
because the network or the login is down.

## Extending

- **New sensor/event source:** write JSON into `data/spool/` with `source`, `event`,
  `time`, plus `picture` or `transcript` (see `robot/events.py: write_event`). Anything
  else needs a branch in `Robot.handle_event`.
- **New thing Claude can do:** add a tool next to `SPEAK_TOOL` in `brain.py` and handle
  it in `Brain._ask_claude`. For multi-step actions (move, then look again), turn that into
  a tool loop.
- **Different detector:** replace `ObjectDetector`; anything that returns `Detection`
  objects works with the rest.
