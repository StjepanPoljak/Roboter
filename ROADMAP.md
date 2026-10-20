# Roadmap

Each stage should be usable on its own before the next one starts. Hardware stays cheap:
a Raspberry Pi 3B+, a USB webcam, a speaker, and later a small chassis.

## Stage 1: Eyes, ears and voice (laptop) ← we are here

- [x] Docker environment that builds on x86_64 and aarch64
- [x] Motion detects movement and saves one snapshot per event
- [x] OpenCV DNN (SSD MobileNet v2, COCO) labels objects in the snapshot
- [x] YuNet + SFace recognize enrolled faces, only when a person is detected
- [x] Text-only scene description goes to Claude, which decides what to say
- [x] Piper (or espeak-ng) speaks the reply offline
- [x] Cooldown and history so the robot doesn't repeat itself or burn API calls
- [ ] Tune Motion (`threshold`, masks for windows/TV) on the real camera placement
- [ ] Measure cost per day at real event rates; tune `ROBOT_COOLDOWN_S` / model choice
- [x] Wake word (openWakeWord, pretrained "hey jarvis") + Whisper speech-to-text, English and Croatian
- [x] Voice events: transcript + current camera scene go to Claude, which answers in your language
- [x] Croatian speech output through the Serbian Piper voice (espeak-ng `hr` as an alternative)
- [ ] Train the custom wake word (docs/WAKEWORD.md) and switch `WAKEWORD` to it
- [ ] Follow-up mode: after answering, listen for a few seconds without needing the wake word

## Stage 2: Move to the Raspberry Pi 3B+

- [ ] 64-bit Raspberry Pi OS Lite + Docker; build the same image on the Pi
- [ ] Benchmark: detection + faces per event (target under 2 s on a 3B+)
- [ ] If too slow: smaller input size, faces on demand only, or YOLO-nano ONNX
- [ ] ALSA audio (`make AUDIO=alsa run`), USB speaker or 3.5 mm jack
- [ ] Run as a systemd service / `docker run --restart unless-stopped`
- [ ] Offline behavior: canned local phrases when the API is unreachable

## Stage 3: Ears on the Pi

- [ ] USB microphone on the Pi (`arecord`); check wake word CPU load next to Motion
- [ ] Measure Whisper `tiny`/`base` speed on the 3B+; if too slow, try Vosk or offload
      speech-to-text to a machine on the LAN (audio still stays in the house)
- [ ] Keep the "text only" rule: audio stays local, only the transcript is sent

## Stage 4: Better senses

- [ ] ArUco markers on doors, the dock, rooms: exact landmarks and distances
- [ ] `look_closely` tool: Claude may ask for one real image, behind a config switch
      (off by default) and/or a spoken "may I look?" confirmation
- [ ] Event sources beyond Motion: MQTT, Home Assistant, a doorbell button
- [ ] Persistent memory (who visited when, preferences) in a local SQLite file

## Stage 5: A body

Option A, Pi robot car kit (PiCar-X style, about €50–90), or option B, DIY chassis +
TB6612FNG driver + separate motor battery. Option C is the Viomi V2 vacuum rooted with
Valetudo (model V-RVCLM21B is on Valetudo's supported list; ours reports itself as
`viomi-vacuum-v6`, the supported variant). Procedure: [VIOMI_ROOT.md](VIOMI_ROOT.md).

- [ ] `Body` interface: `drive(cm)`, `turn(deg)`, `stop()`, `dock()`; fake backend first
- [ ] Local safety reflexes that Claude can't override: ultrasonic stop distance,
      speed cap, e-stop, allowed zones
- [ ] Claude gets movement tools; runs a short tool loop per event (look → move → look)
- [ ] Map/position as text (Valetudo map or marker-based)

## Open questions

- Default model: `claude-opus-5-5` at low effort. Compare it with `claude-haiku-5-5` on
  real events and pick based on reply quality vs. cost.
- Should the robot announce that it recognizes faces to visitors? (See docs/FACES.md.)
