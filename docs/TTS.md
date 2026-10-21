# Speech output (`robot/tts.py`)

The robot speaks with offline voices: text in, WAV out, played on a speaker. Nothing
goes to the network, except the finished audio when it plays on the vacuum over your LAN.

```
text ──► Piper or espeak-ng ──► data/audio/last.wav ──┬─► AUDIO_PLAYER (paplay/aplay)          AUDIO_OUTPUT=local
                                                      └─► 44.1 kHz stereo ─ssh─► vacuum aplay  AUDIO_OUTPUT=viomi
```

## Trying it

```sh
make say TEXT="hello, I am alive"                  # default voice, local speaker
make say TEXT="dobar dan, kako si?" IN=hr          # the voice set for hr in TTS_VOICES
make say TEXT="I live in the vacuum now" OUT=viomi # the vacuum's speaker (setup below)
```

Inside the container (`make shell`) or with the package installed, it's the same command:

```sh
python -m robot say [--lang hr] [--output local|viomi] text to say
```

`--lang` picks a voice from `TTS_VOICES`; unknown or missing languages use the first one.
`--output` overrides `AUDIO_OUTPUT` for this one call.

## Settings (`.env`)

| Variable | Default | What it does |
|---|---|---|
| `TTS_VOICES` | `en=piper:en_US-lessac-low,hr=piper:sr_RS-serbski_institut-medium` | `language=engine:voice`, comma separated; the first is the default |
| `AUDIO_OUTPUT` | `local` | `local`: play with `AUDIO_PLAYER`. `viomi`: play on the vacuum |
| `AUDIO_PLAYER` | `paplay` if `PULSE_SERVER` is set, else `aplay` | Local player command; the WAV path is appended |
| `VIOMI_HOST` | (empty) | The vacuum's address, e.g. `192.168.0.159`. Needed for `viomi` |

Engines:

- **`piper`**: natural voices. The `.onnx` models are baked into the image
  (`scripts/download_models.sh`). There's no Croatian Piper voice; the Serbian one reads
  Croatian text well.
- **`espeak`**: espeak-ng, robotic but instant and about 100 languages. Good on a slow Pi:
  `TTS_VOICES=en=espeak:en,hr=espeak:hr`.

## Playing on the vacuum

The rooted Viomi has its own speaker (docs/VIOMI_ROBOT.md, "Audio"). Two quirks decide
how `tts.py` plays on it:

- **Its codec plays only stereo.** Mono audio is silently dropped, and Piper outputs mono
  (16 kHz for the `low` voices). So `tts.py` first converts the WAV to 44.1 kHz stereo
  (`data/audio/last-viomi.wav`).
- **The amplifier is off between sounds.** Its enable line is `gpio233`, active-low.

One SSH call then uploads the WAV, sets `gpio233` to 0, runs `aplay`, sets it back to 1
(even if `aplay` failed) and deletes the file.

### One-time setup

The container gets its own SSH key, in `data/viomi/` (git-ignored, mounted at `/data`,
and excluded from the image by `.dockerignore`). This keeps your personal key out of a
container that also runs Claude Code.

```sh
mkdir -p data/viomi && chmod 700 data/viomi
ssh-keygen -t ed25519 -N "" -C robot-brain-tts -f data/viomi/id_ed25519
# The vacuum's dropbear reads root's keys from /root/.ssh, not /etc/dropbear:
ssh root@192.168.0.159 'cat >> /root/.ssh/authorized_keys' < data/viomi/id_ed25519.pub
```

Then in `.env`: `AUDIO_OUTPUT=viomi` and `VIOMI_HOST=192.168.0.159`. The vacuum's host
key is saved to `data/viomi/known_hosts` on first use. The image needs `openssh-client`
and `libnss-wrapper`; both are in the Dockerfile, so `make build` once after pulling this.
(`make` runs the container as your UID, which has no `/etc/passwd` entry inside, and ssh
won't start without one. `scripts/entrypoint.sh` adds one through nss_wrapper. Commands
that bypass the entrypoint, like `docker run --entrypoint python`, can't play on the
vacuum.)

To revoke it later, delete the `robot-brain-tts` line from `/root/.ssh/authorized_keys`
on the vacuum.

### When it doesn't play

The robot keeps running: a failed playback is logged as a warning, with the WAV path for
checking by hand.

| Log says | Fix |
|---|---|
| `VIOMI_HOST isn't set` | Set it in `.env` |
| `ssh exit 255: Permission denied` | Key not in `/root/.ssh/authorized_keys` on the vacuum |
| `ssh exit 255: … timed out` | Vacuum off or not on Wi-Fi; `ping $VIOMI_HOST` |
| `ssh exit 255: Host key verification failed` | Vacuum re-flashed: delete `data/viomi/known_hosts` |
| no warning, but silence | Mixer state lost; see "Audio" in docs/VIOMI_ROBOT.md (`Audio speaker out` on, `Lineout volume control` 56) |

## From code

```python
from robot.config import Config
from robot.tts import Speaker

speaker = Speaker(Config.from_env())
speaker.say("Hi Stjepan!", "en")   # synthesize + play
wav = speaker.synthesize("Bok!", "hr")  # just the file: data/audio/last.wav
speaker.play(wav)
```

While anything plays (on either output), `data/audio/speaking` exists, so the listener
ignores the robot's own voice (docs/WAKEWORD.md).
