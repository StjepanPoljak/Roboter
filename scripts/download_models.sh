#!/bin/sh
# Downloads every model the robot uses into $1 (default ./models).
# All of them run locally; nothing here talks to the network at runtime.
set -eu

DEST="${1:-models}"
mkdir -p "$DEST"
cd "$DEST"

fetch() {  # fetch URL FILE
    [ -s "$2" ] && return 0
    echo "downloading $2"
    curl -fsSL --retry 3 -o "$2.part" "$1"
    mv "$2.part" "$2"
}

# Object detection: SSD MobileNet v2 trained on COCO (80 everyday classes), run by OpenCV DNN.
if [ ! -s ssd_mobilenet_v2.pb ]; then
    fetch http://download.tensorflow.org/models/object_detection/ssd_mobilenet_v2_coco_2018_03_29.tar.gz ssd.tar.gz
    tar -xzf ssd.tar.gz ssd_mobilenet_v2_coco_2018_03_29/frozen_inference_graph.pb
    mv ssd_mobilenet_v2_coco_2018_03_29/frozen_inference_graph.pb ssd_mobilenet_v2.pb
    rm -rf ssd.tar.gz ssd_mobilenet_v2_coco_2018_03_29
fi
fetch https://raw.githubusercontent.com/opencv/opencv_extra/4.x/testdata/dnn/ssd_mobilenet_v2_coco_2018_03_29.pbtxt \
      ssd_mobilenet_v2.pbtxt

# Faces: YuNet (detection) + SFace (recognition embeddings), both from the OpenCV model zoo.
fetch https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx \
      face_detection_yunet.onnx
fetch https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx \
      face_recognition_sface.onnx

# Speech: Piper voices. More at https://huggingface.co/rhasspy/piper-voices
VOICE_BASE=https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/low
fetch "$VOICE_BASE/en_US-lessac-low.onnx" en_US-lessac-low.onnx
fetch "$VOICE_BASE/en_US-lessac-low.onnx.json" en_US-lessac-low.onnx.json
# There is no Croatian Piper voice; the Serbian one reads Croatian (Latin) text naturally.
VOICE_BASE=https://huggingface.co/rhasspy/piper-voices/resolve/main/sr/sr_RS/serbski_institut/medium
fetch "$VOICE_BASE/sr_RS-serbski_institut-medium.onnx" sr_RS-serbski_institut-medium.onnx
fetch "$VOICE_BASE/sr_RS-serbski_institut-medium.onnx.json" sr_RS-serbski_institut-medium.onnx.json

# Wake word (openWakeWord: feature models, Silero VAD, pretrained "hey jarvis") and
# speech-to-text (Whisper "base"). These need the Python packages from requirements.txt.
python3 - <<'EOF'
import pathlib
from openwakeword import utils
from faster_whisper import WhisperModel

oww = pathlib.Path("openwakeword")
utils.download_models(model_names=["hey_jarvis"], target_directory=str(oww))
for tflite in oww.glob("*.tflite"):  # we only use the ONNX versions
    tflite.unlink()
WhisperModel("base", device="cpu", compute_type="int8", download_root="whisper")
EOF
