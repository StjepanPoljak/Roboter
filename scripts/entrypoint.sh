#!/bin/sh
# "run" starts the event sources in the background (Motion for the camera, the listener
# for the microphone) and the brain in the foreground. Any other command is passed to
# the CLI, e.g. `analyze`, `enroll`, `say`.
set -eu

DATA="${ROBOT_DATA_DIR:-/data}"
mkdir -p "$DATA/spool" "$DATA/snapshots" "$DATA/audio"
rm -f "$DATA/audio/speaking"

[ $# -eq 0 ] && set -- run

if [ "$1" != "run" ]; then
    exec python -m robot "$@"
fi

PIDS=""
if [ "${ROBOT_MOTION:-1}" = "1" ]; then
    motion -n -c /app/config/motion.conf &
    PIDS="$PIDS $!"
    # Lets voice events grab a current frame from Motion's live stream.
    export ROBOT_CAMERA_STREAM="${ROBOT_CAMERA_STREAM:-http://localhost:8081}"
fi
if [ "${ROBOT_LISTEN:-1}" = "1" ]; then
    python -m robot listen &
    PIDS="$PIDS $!"
fi
trap 'kill $PIDS 2>/dev/null' EXIT INT TERM
python -m robot "$@"
