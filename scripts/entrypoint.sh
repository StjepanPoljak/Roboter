#!/bin/sh
# "run" starts the event sources in the background (Motion for the camera, unless
# ROBOT_CAMERA is sample or off; the listener for the microphone) and the brain in the
# foreground. Any other command is passed to
# the CLI, e.g. `analyze`, `enroll`, `say`.
set -eu

DATA="${ROBOT_DATA_DIR:-/data}"
mkdir -p "$DATA/spool" "$DATA/snapshots" "$DATA/audio"
rm -f "$DATA/audio/speaking"

# `make` runs us as the host user's UID, which has no /etc/passwd entry here, and ssh
# (speech on the vacuum, docs/TTS.md) refuses to start without one. nss_wrapper adds
# the entry for our processes only; /etc/passwd stays read-only.
if ! id -un >/dev/null 2>&1; then
    PASSWD=/tmp/passwd
    { cat /etc/passwd; echo "robot:x:$(id -u):$(id -g):robot:${HOME:-/tmp}:/bin/sh"; } > "$PASSWD"
    export LD_PRELOAD=libnss_wrapper.so NSS_WRAPPER_PASSWD="$PASSWD" NSS_WRAPPER_GROUP=/etc/group
fi

[ $# -eq 0 ] && set -- run

if [ "$1" != "run" ]; then
    exec python -m robot "$@"
fi

PIDS=""
if [ "${ROBOT_CAMERA:-motion}" = "motion" ]; then
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
