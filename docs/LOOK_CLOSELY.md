# Look closely: one real image, when asked

Normally Claude only gets text from the local detectors: 80 object types, rough
position and distance, and the names of enrolled faces. That can't answer "what colour
is this?", "read this label" or "what am I holding?". With `look_closely` on, Claude can
ask for one camera image for such a question.

```toml
# robot.toml
[claude]
look_closely = true
```

## What happens

```
"hey jarvis, what colour is my shirt?"
   │
   ▼
local detectors describe the current frame ──► Claude (text, as always)
                                                  │
                         text is enough ◄─────────┤ needs a closer look
                         speak, done              ▼
                                       the same frame as JPEG (~30–60 KB) ──► Claude ──► speak
```

1. A voice question goes to Claude as text, as always, with the option to ask for a look.
2. If Claude asks, the robot sends **the frame the detectors just described**, once.
   Claude answers from it; it can't ask again for the same question.
3. The log says so every time: `look_closely: sending one camera image (33 KB) to Claude`,
   and the history shows `looked closely`.

## Limits, on purpose

- **Off by default.** Turning it on is your decision, for your household.
- **Voice questions only.** Motion events and camera samples never send an image, so the
  camera can't start streaming pictures on its own. Someone has to ask.
- **One image per question**, and Claude is told not to ask for greetings or small talk.
- **Nothing is stored** for it: the frame is encoded in memory and sent. What Claude does
  with it is covered by your Claude account's data settings.
- **Usage:** an image is roughly 1000+ input tokens against ~100 for the text, and a
  look means a second Claude call (a few seconds more). On the subscription it counts
  toward the usage limits; with the API it's billed per token.

## How it's sent

- `cli` backend: `claude -p` with `--input-format stream-json`, the image and the prompt
  as one user message on stdin. All Claude Code tools stay off, as for text.
- `api` backend: a `look_closely` tool next to `speak`; the follow-up request carries the
  image as an image content block.

Both are in `robot/brain.py` (`Brain.react`, `_ask_claude_code`, `_ask_claude`).

## Try it

```sh
make ask TEXT="what colour is his shirt?" IMG=data/messi.jpg   # a photo stands in for the camera
```

With `make run`, just ask out loud. Without a camera (`camera.mode = "off"`) there's
no frame, so Claude isn't offered a look.
