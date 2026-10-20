#!/bin/sh
# Called by Motion's on_picture_save as: motion_hook.sh <event-number> <picture-path>
# Drops one JSON file per event into the spool directory, which the brain watches.
# Written to a temp file and renamed, so the brain never reads a half-written event.
set -eu

SPOOL="${ROBOT_DATA_DIR:-/data}/spool"
mkdir -p "$SPOOL"

stamp=$(date +%Y%m%d-%H%M%S)
tmp="$SPOOL/.$stamp-$1.tmp"
printf '{"source": "motion", "event": "%s", "picture": "%s", "time": "%s"}\n' \
    "$1" "$2" "$(date -Iseconds)" > "$tmp"
mv "$tmp" "$SPOOL/$stamp-$1.json"
