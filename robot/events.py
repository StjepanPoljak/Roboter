"""Event spool: event sources drop JSON files into a directory, the brain consumes them.

A directory is the simplest queue that survives restarts, needs no extra services,
and lets you inject test events with nothing more than `cp`.

Sources so far:
- motion: scripts/motion_hook.sh, with a "picture"
- voice:  robot/listener.py, with a "transcript" and "language"
"""

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Event:
    source: str
    event_id: str
    time: datetime
    spool_file: Path
    picture: Path | None = None
    transcript: str | None = None
    language: str | None = None


def write_event(
    spool_dir: Path,
    source: str = "manual",
    event_id: str = "0",
    picture: Path | None = None,
    transcript: str | None = None,
    language: str | None = None,
) -> Path:
    """Queue an event (same format as scripts/motion_hook.sh)."""
    spool_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now().astimezone()
    name = f"{now:%Y%m%d-%H%M%S-%f}-{source}-{event_id}"
    payload = {"source": source, "event": event_id, "time": now.isoformat()}
    if picture is not None:
        payload["picture"] = str(picture)
    if transcript is not None:
        payload["transcript"] = transcript
        payload["language"] = language
    tmp = spool_dir / f".{name}.tmp"
    tmp.write_text(json.dumps(payload, ensure_ascii=False) + "\n")
    final = spool_dir / f"{name}.json"
    tmp.rename(final)
    return final


def _parse(path: Path) -> Event | None:
    try:
        data = json.loads(path.read_text())
        if "picture" not in data and "transcript" not in data:
            raise ValueError("event has neither picture nor transcript")
        return Event(
            source=data.get("source", "unknown"),
            event_id=str(data.get("event", "")),
            time=datetime.fromisoformat(data["time"]),
            spool_file=path,
            picture=Path(data["picture"]) if "picture" in data else None,
            transcript=data.get("transcript"),
            language=data.get("language"),
        )
    except (OSError, ValueError, KeyError) as e:
        log.warning("dropping malformed event %s: %s", path.name, e)
        path.unlink(missing_ok=True)
        return None


def _queued(spool_dir: Path) -> list[Path]:
    # Voice first: someone talking to the robot shouldn't wait behind motion snapshots.
    return sorted(spool_dir.glob("*.json"), key=lambda p: ("-voice-" not in p.name, p.name))


def watch(spool_dir: Path, poll_s: float = 0.3) -> Iterator[Event]:
    """Yield queued events, forever. The caller deletes each event's spool file."""
    spool_dir.mkdir(parents=True, exist_ok=True)
    while True:
        queued = _queued(spool_dir)
        for path in queued:
            event = _parse(path)
            if event is not None:
                yield event
        if not queued:
            time.sleep(poll_s)


def pending(spool_dir: Path) -> list[Event]:
    """Events queued right now (used by tests and `robot run --once`)."""
    return [e for p in _queued(spool_dir) if (e := _parse(p)) is not None]
