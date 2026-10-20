# Hardware

## Stage 1: laptop

Any Linux laptop with a webcam and Docker. Audio goes through the desktop's
PulseAudio/PipeWire socket (the Makefile's default `AUDIO=pulse`).

## Stage 2: Raspberry Pi 3B+

**Use 64-bit Raspberry Pi OS (Lite is fine).** Piper and onnxruntime only ship aarch64
wheels; the 32-bit (armv7) OS won't build the image.

```sh
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker,video,audio $USER   # log out and back in
git clone <this repo> && cd Robot
cp .env.example .env && nano .env
make build                                  # slow on a 3B+ (tens of minutes); once
make AUDIO=alsa run
```

What to expect from a 3B+ (1 GB RAM, 4× Cortex-A53):

- Motion at 640×480 / 10 fps: light, about 10–20% of one core.
- SSD MobileNet v2 per snapshot: roughly 0.5–1 s. Faces add about 0.3–0.6 s per face.
- Piper `low` voice: about real-time or a bit slower. If speech lags, use
  espeak voices in `TTS_VOICES` (instant, robotic), e.g. `en=espeak:en,hr=espeak:hr`.
- RAM: the brain uses about 400–500 MB with all models loaded, and the listener (wake word
  + Whisper `tiny`/`base`) another 200–300 MB. That's tight in 1 GB: add 1 GB of swap,
  don't run a desktop, and see docs/WAKEWORD.md for the slow-Pi options.
- The wake word model runs continuously; expect it to take a good part of one core.
- Cooling: a heatsink, or it'll throttle under sustained load.

Those numbers are estimates; measuring them is on the roadmap (`make analyze` prints
the time per image).

## Cheap parts list

| Part | Notes | Rough price |
|---|---|---|
| Raspberry Pi 3B+ | you have it | – |
| 32 GB microSD, A1/A2 class | the OS and Docker images | €8 |
| 5V 2.5A PSU (official is best) | undervoltage causes random weirdness | €8 |
| USB webcam, 720p | Logitech C270 class; works with Motion out of the box | €15–20 |
| or Pi Camera v2 / v3 | needs `libcamerify` or a v4l2 bridge for Motion; USB is simpler | €15–25 |
| USB speaker, or small speaker on the 3.5 mm jack | jack audio is noisy on Pis; USB is cleaner | €5–10 |
| USB mic (stage 3) | a €5 "mini USB mic" works for a wake word | €5 |
| Heatsink + fan case | 3B+ throttles otherwise | €5 |

Stage 5 (moving): see ROADMAP.md. Kit (PiCar-X style) or DIY: 2WD chassis €10–15,
TB6612FNG driver €5, HC-SR04 ultrasonic €2 (needs a voltage divider on ECHO: the Pi's pins
are 3.3V), and a **separate** battery for the motors (2×18650 + holder €10). Sharing the
Pi's supply with the motors causes brownouts and reboots.
