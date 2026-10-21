"""Raw lidar scans from the rooted Viomi vacuum, decoded locally into text.

The 3irobotix LDS3 lidar is wired to the robot's /dev/ttyS1, which AuxCtrl reads.
Opening the tty ourselves would steal bytes from AuxCtrl, so we attach strace to it
instead and rebuild the byte stream from the log. Protocol and calibration notes:
docs/VIOMI_ROBOT.md, "Serial protocols".

The lidar only spins while the robot navigates (returning to the dock, cleaning);
docked or in manual control there's nothing to read.

Standard library only, so it runs on the host as well as in the container:
    python3 -m robot.lidar --seconds 8          # capture from the robot and describe it
    python3 -m robot.lidar --file aux.strace    # decode a saved capture
"""

import argparse
import math
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

LIDAR_FD = "8"  # AuxCtrl's descriptor for /dev/ttyS1; checked with `ls -l /proc/$(pidof AuxCtrl)/fd`
CMD_SCAN = 0xAD
CMD_SPEED = 0xAE
UNITS_PER_METER = 4000  # 0.25 mm per unit, calibrated against the Valetudo map
FLAG_BIT = 0x4000  # set on ~2% of samples; treated as unreliable
PACKET_SPAN_DEG = 22.5  # 16 scan packets per rotation

_LINE = re.compile(r"(\d+)\s+(\S+) (.*)")
_UNFINISHED = re.compile(r"(read|write)\((\d+),\s*<unfinished")
_RESUMED = re.compile(r'<\.\.\. (read|write) resumed> "((?:[^"\\]|\\.)*)"')
_COMPLETE = re.compile(r'(read|write)\((\d+), "((?:[^"\\]|\\.)*)"')


def _unescape(text: str) -> bytes:
    return text.encode("latin1").decode("unicode_escape").encode("latin1")


def strace_streams(lines) -> dict[tuple[str, str], bytes]:
    """`strace -f -tt -x -e trace=read,write` output -> {("read", fd): bytes, ...}.

    With -f, a syscall interrupted by another thread is split into
    "read(8,  <unfinished ...>" and "<... read resumed> "data"" lines; those are
    joined per PID. Chunks are ordered by timestamp.
    """
    pending: dict[str, tuple[str, str]] = {}
    chunks: dict[tuple[str, str], list[tuple[str, bytes]]] = {}
    for line in lines:
        match = _LINE.match(line)
        if not match:
            continue
        pid, timestamp, rest = match.groups()
        if unfinished := _UNFINISHED.match(rest):
            pending[pid] = (unfinished.group(1), unfinished.group(2))
            continue
        resumed = _RESUMED.match(rest)
        if resumed and pid in pending:
            key, data = pending.pop(pid), resumed.group(2)
        elif complete := _COMPLETE.match(rest):
            key, data = (complete.group(1), complete.group(2)), complete.group(3)
        else:
            continue
        chunks.setdefault(key, []).append((timestamp, _unescape(data)))
    return {key: b"".join(data for _, data in sorted(parts)) for key, parts in chunks.items()}


def frames(data: bytes):
    """Yield (cmd, payload) for each valid frame: AA len16 01 61 cmd plen16 payload sum16.

    `len` counts the bytes before the checksum; the checksum is their sum, mod 2^16.
    Bytes that don't form a valid frame are skipped.
    """
    i = 0
    while i + 3 <= len(data):
        if data[i] != 0xAA:
            i += 1
            continue
        length = int.from_bytes(data[i + 1:i + 3], "big")
        end = i + length
        if length < 8 or end + 2 > len(data) or sum(data[i:end]) & 0xFFFF != int.from_bytes(data[end:end + 2], "big"):
            i += 1
            continue
        yield data[i + 5], data[i + 8:end]
        i = end + 2


@dataclass
class Sample:
    angle: float  # degrees in the lidar's own frame, 0..360
    distance: float  # meters
    quality: int


def scan_samples(payload: bytes) -> list[Sample]:
    """One 0xAD packet: speed, 0x0010, start angle (0.01°), then quality + distance triplets."""
    start = int.from_bytes(payload[3:5], "big") / 100
    count = (len(payload) - 5) // 3
    samples = []
    for k in range(count):
        quality = payload[5 + 3 * k]
        raw = int.from_bytes(payload[6 + 3 * k:8 + 3 * k], "big")
        if raw == 0 or raw & FLAG_BIT:
            continue
        samples.append(Sample(start + PACKET_SPAN_DEG * k / count, raw / UNITS_PER_METER, quality))
    return samples


def rotations(data: bytes) -> list[list[Sample]]:
    """Group scan packets into full turns (each starts at angle 0); partial turns are dropped."""
    turns: list[list[Sample]] = []
    current: list[Sample] | None = None
    for cmd, payload in frames(data):
        if cmd != CMD_SCAN or len(payload) < 8:
            continue
        if payload[3:5] == b"\x00\x00":
            if current is not None:
                turns.append(current)
            current = []
        if current is not None:
            current.extend(scan_samples(payload))
    return turns


SECTORS = [("ahead", 0), ("front-left", 45), ("left", 90), ("back-left", 135),
           ("behind", 180), ("back-right", 225), ("right", 270), ("front-right", 315)]


def describe(turn: list[Sample], forward_deg: float = 0.0) -> str:
    """Nearest obstacle per 45° sector, as text for Claude.

    `forward_deg` is the lidar angle that points along the robot's heading. The
    mounting offset hasn't been calibrated yet; until it is, "ahead" means the
    lidar's 0°, not necessarily the robot's front. Angles grow counter-clockwise.
    """
    nearest: dict[str, float] = {}
    for sample in turn:
        relative = (sample.angle - forward_deg) % 360
        name = SECTORS[int(((relative + 22.5) % 360) // 45)][0]
        nearest[name] = min(nearest.get(name, math.inf), sample.distance)
    lines = []
    for name, _ in SECTORS:
        distance = nearest.get(name)
        lines.append(f"- {name}: " + (f"nearest {distance:.2f} m" if distance else "nothing within range"))
    return "\n".join(lines)


def capture(host: str, seconds: float) -> str:
    """strace AuxCtrl on the robot for `seconds` and return the log text."""
    remote = (
        "strace -f -tt -x -s 4096 -e trace=read,write -p $(pidof AuxCtrl) -o /tmp/lidar.strace 2>/dev/null & "
        f"S=$!; sleep {seconds:g}; kill $S; sleep 1; cat /tmp/lidar.strace; rm -f /tmp/lidar.strace"
    )
    result = subprocess.run(
        ["ssh", "-o", "LogLevel=ERROR", "-o", "ConnectTimeout=10", f"root@{host}", remote],
        capture_output=True, text=True, encoding="latin1", timeout=seconds + 30, check=True,
    )
    return result.stdout


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m robot.lidar", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="192.168.0.159", help="the robot's address (default: %(default)s)")
    parser.add_argument("--seconds", type=float, default=8, help="capture length (default: %(default)s)")
    parser.add_argument("--file", type=Path, help="decode a saved strace log instead of capturing")
    parser.add_argument("--save", type=Path, help="also write the captured strace log here")
    parser.add_argument("--forward", type=float, default=0.0, help="lidar angle of the robot's heading, degrees")
    args = parser.parse_args()

    text = args.file.read_text(encoding="latin1") if args.file else capture(args.host, args.seconds)
    if args.save:
        args.save.write_text(text, encoding="latin1")
    data = strace_streams(text.splitlines()).get(("read", LIDAR_FD), b"")
    turns = rotations(data)
    print(f"{len(data)} lidar bytes, {len(turns)} full rotation(s)")
    if not turns:
        sys.exit("no scan data: the lidar only spins while the robot navigates (e.g. returning to the dock)")
    print(describe(turns[-1], args.forward))


if __name__ == "__main__":
    main()
