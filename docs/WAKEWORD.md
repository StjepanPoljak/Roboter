# Wake word and speech-to-text

## How listening works

```
mic (parec / arecord, 16 kHz)
  │  80 ms chunks, kept in memory and thrown away
  ▼
openWakeWord ── score ≥ WAKEWORD_THRESHOLD? ──no──► (forget the chunk)
  │ yes
  ▼
chime ("I'm listening")
  ▼
record until 0.9 s of silence (Silero VAD), max 15 s; give up if nobody speaks within 4 s
  ▼
Whisper (faster-whisper, int8): pick English or Croatian, transcribe
  ▼
voice event in data/spool/ ──► brain: transcript + current camera scene ──► Claude ──► speak
```

- **Nothing is recorded or sent while waiting for the wake word.** Audio only goes through
  the tiny wake word model.
- **Only the transcript leaves the device**, as text, same as the camera.
- **The robot doesn't hear itself.** While it speaks, `data/audio/speaking` exists and the
  listener ignores the microphone.
- Croatian is often detected as Serbian or Bosnian; those count as Croatian
  (`robot/listener.py: LANGUAGE_ALIASES`). Claude answers in the language you used, and
  `TTS_VOICES` picks the voice for that language.

## Trying it

```sh
make listen-test        # say "hey jarvis", then a sentence; prints what it heard
make run                # the full robot: camera + microphone + Claude + speech
make ask TEXT="what do you see?"          # skip the mic: type what you'd have said
make ask IN=hr TEXT="Što vidiš?"
```

## Your own wake word (custom name)

The pretrained model is **"hey jarvis"**. To use your own name:

1. Open the openWakeWord training notebook in Google Colab:
   https://colab.research.google.com/drive/1q1oe2zOyZp7UsB3jJiQ1IFn8z5YfjwEb?usp=sharing
   (more control: `notebooks/automatic_model_training.ipynb` in
   https://github.com/dscripka/openWakeWord)
2. Enter the phrase, run all cells. It generates thousands of synthetic examples with
   text-to-speech and trains a small model. This takes under an hour and needs no
   recordings of your voice.
3. Download the resulting **`.onnx`** file and put it in `data/wakeword/`, e.g.
   `data/wakeword/hey_robo.onnx`.
4. In `.env`: `WAKEWORD=hey_robo` (the file name without `.onnx`). Restart.

Tips for choosing the phrase:

- **2–4 syllables, unusual sounds.** "Hey Robo" works better than "Robo" alone; a short
  single word fires on everything.
- **Training is English-only.** The synthetic voices are English, so the phrase should be
  something an English speaker pronounces the way you will. Croatian names that read the
  same in English ("Hey Luka", "Hey Mara") are fine. Ones with č/ć/š/ž/đ or vowel-heavy
  Croatian sounds will match less reliably.
- Check the community collection first; someone may have trained it already:
  https://github.com/fwartner/home-assistant-wakewords-collection

## Tuning

| Symptom | Fix |
|---|---|
| Wakes up on TV / random speech | Raise `WAKEWORD_THRESHOLD` (0.6–0.7) |
| Has to be called several times | Lower it (0.3–0.4), or move the mic closer |
| Cuts you off mid-sentence | Raise `silence_s` in `Recorder` (`robot/listener.py`) |
| Croatian transcripts are poor | `WHISPER_MODEL=small` (downloads ~480 MB to `data/whisper` once; ~3× slower) |
| Too slow on the Pi | `WHISPER_MODEL=tiny`, `STT_LANGUAGES=hr` (skips language detection) |

## Speech-to-text models

| `WHISPER_MODEL` | Size | Laptop (int8, ~4 s sentence) | Pi 3B+ | Croatian |
|---|---|---|---|---|
| `tiny` | 75 MB | about 1 s | a few seconds | weak |
| `base` (default, in the image) | 145 MB | 2.6 s (measured) | 10+ s | small mistakes |
| `small` | 480 MB | 7.5 s (measured) | too slow | usually better |

The laptop numbers were measured on a 4-second sentence; the rest are rough expectations.
The Croatian test used a synthetic (Serbian) voice, which slurs some words itself, so try
`small` on your own voice before deciding. `make transcribe` and the listener's log
("heard [hr] in 2.6s") show the real numbers on your hardware. If the Pi is too slow for the
quality you want, the roadmap has two options: Vosk (fast, smaller models) or sending the
recorded audio to a machine on your LAN.
