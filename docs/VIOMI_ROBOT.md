# The Viomi robot: system survey

What's inside our rooted Viomi V2 (`viomi.vacuum.v6`, 3irobotix CRL-200S platform), as
found by logging in and looking around on **2026-10-21**. Robot was docked and charged.
The survey itself was read-only. Hands-on tests followed the same day: the microphone
(none, confirmed by a loopback test), the speaker (works, stereo only), manual-control moves (they work) and
reading raw lidar and MCU serial traffic (decoded). All are described below.

How it got rooted: [VIOMI_ROOT.md](../VIOMI_ROOT.md). Raw command output from the survey
isn't kept; re-run the commands in [Re-checking](#re-checking) to refresh any of this.

## Quick reference

| What | Value |
|---|---|
| IP / MAC | `192.168.0.159` (reserved in the router) / `scripts/viomi_mac.sh` |
| Shell | `ssh root@192.168.0.159` (key auth with `~/.ssh/id_ed25519`, dropbear on :22) |
| Web UI / API | `http://192.168.0.159/` and `/api/v2/...`, Swagger at `/swagger/`; **no auth** |
| mDNS name | `valetudo-sympatheticlargepelican.local` |
| Valetudo | 2026.10.0 (commit `78267517`), `ViomiV6ValetudoRobot` |
| Robot firmware | DustBuilder Viomi V6 build `0046`; stock app `V1.2.46.03.28R` |
| OS | Tina Linux 2.0.0 (Allwinner's OpenWrt fork), kernel 3.4.39, BusyBox 1.24.1 |
| SoC | Allwinner R16-class `sun8i`: 4× Cortex-A7 @ 1.2 GHz, 512 MB RAM |
| Free headroom | ~330 MB RAM, CPUs ~90% idle when docked, ~78 MB on `/mnt/UDISK` |

## Hardware

### Main board

- **SoC:** Allwinner `sun8i`, 4× ARM Cortex-A7 (`CPU part 0xc07`), NEON + VFPv4, fixed at
  1.2 GHz (`performance` governor). Tina target `astar-parrot` = Allwinner R16/A33
  family. Chip ID `aad846e7…`.
- **RAM:** 512 MB, ~372 MB available to Linux (the rest is reserved for ION/CMA). No swap
  (a `zram0` device exists but isn't enabled).
- **Storage:** raw NAND (Macronix, chip ID `0xc2 0xda`, 256 MB) through Allwinner's
  `nand` block driver (`/dev/nand[a-i]`), not MTD. Partitions below.
- **PMIC:** X-Powers **AXP223** (`axp22`), feeds the Wi-Fi (`dldo1/dldo2/aldo1` at 3.3 V)
  and the NAND.
- **Wi-Fi:** Realtek **RTL8189ES** on SDIO (`mmc0`, kernel module `8189es`), 2.4 GHz only.
  `wlan0` is the client; `wlan1` (MAC `66:90:…`) is for the setup access point. No
  Bluetooth radio, even though the kernel has the BT stack.
- **RTC:** a `pcf8563` driver probes I²C bus 1 at `0x51` but every read fails, so the chip
  isn't fitted (`hardwareRtc=0` in config agrees). The SoC's own RTC (`rtc1`) has no
  battery backup. **The clock is wrong after every boot until NTP syncs.**
- **Temperature:** one SoC sensor, `/sys/class/thermal/thermal_zone0/temp` (38 °C docked).
  Trip points 75 / 90 / 110 °C.
- **Buttons:** the two top buttons come in through `sunxi-keyboard` (`/dev/input/event1`),
  read by `sayeye`. The power key is on the AXP (`event0`).

### Motor controller (MCU) and sensors

The Linux board doesn't drive motors or read sensors itself. An **STM32 co-processor**
(firmware `2.0.1_19082728`) does, and talks to Linux over a UART:

| UART | Device | Used by | Notes |
|---|---|---|---|
| uart0 | `/dev/ttyS0` | nobody | 265 bytes TX since boot |
| uart1 | `/dev/ttyS1` | `AuxCtrl` | **Lidar**, receive only. Silent until the lidar spins |
| uart2 | – | kernel console | `console=ttyS2,115200`, not exposed as a device node; a debug header on the board |
| uart3 | `/dev/ttyS3` | `AuxCtrl` | **STM32 MCU**, RTS/CTS flow control, always busy |

The lidar is wired straight to `ttyS1`. The MCU only switches its motor on when the robot
navigates (returning to the dock, cleaning). It stays off on the dock and in manual
control, even though Linux keeps sending what looks like a lidar power request. Both
protocols are decoded in [Serial protocols](#serial-protocols). Baud rates weren't read
(no `stty` on the robot).

Sensors the firmware knows about, from `/mnt/UDISK/config/hwdrivers.ini`:

- **Lidar:** 3irobotix LDS3 (`LDS3_NOR_1805041536`), 6 m max range, on top of the robot
- **Bumper**, front left and right (`enable_bumper=15`)
- **Cliff IR** ×4: left, left-front, right-front, right (2–15 cm)
- **Wall-follow IR** and **"sonar"** (0.5 m range, 60° sector), both enabled
- **Wheel drop** (wheel-up) switches: present, but masked in `specail_hwdrivers.ini`
- **IMU** fused with wheel odometry (`enable_fuse_pose_with_imu=1`), pitch/roll/slip detection
- **Dock IR** receiver, charge state, magnetic strip sensor ("geomagnetism", for no-go tape)
- **Carpet** detection, and presence switches for dustbin / water tank / mop
- **Motor stall** detection on wheels and brushes; blower speed feedback

Actuators: two drive wheels, main roller brush, one side brush (right), blower
(11 200–21 000 rpm across modes), water pump, button LEDs.

Motion limits from `motion_params.ini` (m/s, rad/s):

| Mode | Max linear | Max angular |
|---|---|---|
| `MOTION_MANUAL` (what Valetudo's manual control uses) | 0.25 | 1.73 |
| Point-to-point moves | 0.25–0.30 | 0.7–1.0 |
| Docking | 0.25 | 0.7 |

### Battery

The MCU manages the battery. Linux's `/sys/class/power_supply/battery` is a stub (says
LiFe, capacity 0, voltage 0), so **use Valetudo** for the real level: 100%, `charged`.

### Audio

- **Speaker:** yes, on the SoC's built-in codec (ALSA card 0 `audiocodec`).
- **How RobotApp plays a prompt** (seen with `strace`): it runs
  `tinyplayer /usr/share/audio/english/<n>sound_<name>.mp3`, and around the playback it
  switches the speaker amplifier with **`gpio233`, active-low**: `echo 0 >
  /sys/class/gpio/gpio233/value` (amp on) before, `echo 1` (amp off) after. At idle it's `1`.
- **The mixer has to be in the right state, and nothing resets it.** `tinyplayer` doesn't
  set the volume, so prompts rely on the mixer as it is. Working state:
  `Speaker Function = spk`, `Audio speaker out = on`, `Lineout volume control = 56`. On
  2026-10-21 a mixer save/restore during the mic test left speaker out off and line-out
  at 0, and **every prompt was silent** (even Valetudo's speaker test) until those three
  were set by hand. Don't run `alsactl restore` on this robot.
- **Only stereo is audible.** With the working mixer state and `gpio233=0`, `aplay`
  played (checked by ear, 2026-10-21):

  | Format | Heard |
  |---|---|
  | 44.1 kHz stereo | yes, clean |
  | 16 kHz stereo | yes, a bit distorted |
  | 44.1 kHz mono, 22.05 kHz mono, 16 kHz mono | **silent** |

  `aplay` opens `hw:0,0` directly (no conversion), so a mono file stays mono all the
  way to the codec, which apparently only feeds the speaker from a stereo stream.
  tinyplayer decodes the prompts to stereo, which is why they always worked.
- **Working recipe for speech** (tested with the project's Piper voice, which outputs
  16 kHz mono, so it has to be converted first):

  ```sh
  ffmpeg -i speech.wav -ar 44100 -ac 2 speech_44s.wav          # on the laptop / Pi
  ssh root@192.168.0.159 'cat > /tmp/s.wav' < speech_44s.wav
  ssh root@192.168.0.159 'echo 0 > /sys/class/gpio/gpio233/value; aplay -q /tmp/s.wav;
                          echo 1 > /sys/class/gpio/gpio233/value; rm /tmp/s.wav'
  ```

  Result: clear speech from the robot. Put `gpio233` back to `1` afterwards, the way
  RobotApp does, so the amplifier doesn't sit on (and hiss) between prompts.
- The stock voice prompts are MP3s in `/usr/share/audio/{english,mandarin}` (about 130
  each: cleaning, errors, factory tests). Valetudo's volume is 100.
- **Microphone: none.** Loopback test, 2026-10-21: recorded (`arecord -D hw:0,0`,
  44.1 kHz stereo) through every capture route while the speaker played an audible
  880 Hz stereo tone, and again in silence:

  | Route | With tone | Silent |
  |---|---|---|
  | none (baseline), main mic, headset mic, voice record | exact zero | exact zero |
  | line-in | tone at −86 dBFS | −97 dBFS noise |
  | line-in, **amplifier off** (`gpio233=1`, nothing audible) | **same tone, same level** | – |

  Line-in picks up the tone just as strongly with the amplifier off, so it's electrical
  crosstalk from the playback path inside the codec, not sound. A real mic this close
  to the speaker would record around −20 to −40 dBFS. All capture switches are off by
  default and were set back one by one (not with `alsactl`). Line-in recordings during
  playback sometimes end early with `pcm_read: I/O error`.

### USB

The micro-USB port (in the battery bay) is **device-only**: it shows up on a computer as
an ADB gadget (`android_usb`, `adbd`). There's no USB host port and `/sys/bus/usb/devices`
is empty, so **a USB webcam or mic can't be plugged into the robot**. They have to hang off
the Raspberry Pi riding on top instead. (The kernel has USB host drivers for serial, HID
and USB audio, but no webcam driver, and there's no port to use them anyway.)

### What's not there

No camera, no display, no GPS, no Bluetooth radio, no hardware clock, no USB host.

## Storage layout

NAND partitions (`/dev/by-name/*`):

| Dev | Name | Size | Mounted | Contents |
|---|---|---|---|---|
| nanda | boot-res | 1 MB | `/boot-res` (ro, vfat) | Boot logo |
| nandb | env | 1 MB | – | U-Boot environment |
| nandc | boot | 4 MB | `/boot` (ro, vfat) | Kernel `uImage` (Nov 2018) |
| nandd | rootfs | 48 MB | `/rom` (squashfs, ro) | Rooted firmware image |
| nande | rootfs_data | 10 MB | `/overlay` (ext4) | Overlay over `/` and `/usr`: **8 MB free** |
| nandf | private | 1 MB | `/mnt/SNN` (vfat) | Factory identity: MAC, serial, DID, **device key** |
| nandg | recovery | 32 MB | – | Recovery system |
| nandh | misc | 1 MB | – | Boot flags |
| nandi | UDISK | 111 MB | `/mnt/UDISK` (ext4) | Valetudo, configs, maps, logs: **78 MB free** |

- `/tmp` is a 250 MB tmpfs, wiped on reboot. Valetudo logs to `/tmp/valetudo.log`.
- Our stock dump of every partition is in `viomi-backup/` (gitignored) and on the USB
  stick; see the memory note in VIOMI_ROOT.md.

What's on `/mnt/UDISK`:

```
_root.sh              started from /etc/rc.local at boot; launches Valetudo
valetudo              Valetudo binary (13.8 MB, Node 22 bundled)
valetudo_config.json  Valetudo settings
config/               RobotApp/MCU tuning: *.ini, Cartographer *.lua
log/                  wifiDeamon.log, Monitor.temp, a map PNG
install.log           DustBuilder installer output from rooting
binary/, misc-upgrade/  empty
```

Anything we install ourselves should go in `/mnt/UDISK`, not the 8 MB overlay.

## Software

### Boot

`procd` runs `/etc/rc.d/S*` in order. The robot-specific parts:

| Order | Script | Starts |
|---|---|---|
| S10 | healthd | `/bin/healthd -D`: Allwinner battery/charge daemon |
| S20 | sayeye | `/bin/sayeye -D`: button handling, socket `/dev/socket/sayeye` |
| S50 | dropbear | SSH server (added by DustBuilder) |
| S80 | adbd | ADB over the USB gadget |
| S90 | robotManager | `/usr/sbin/Monitor -D`, which starts and watches RobotApp, AuxCtrl, everest-server, log-server |
| S90 | robotWifiManager | `wifiManager -D` → `wpa_supplicant` + `udhcpc` |
| S95 | robotUpgrade | `upgrade -D`: OTA client (harmless: its servers are blackholed) |
| S95 | done | runs `/etc/rc.local` |

`/etc/rc.local` copies default configs to `/mnt/UDISK/config`, checks the miio key files,
starts `/etc/wifi-deamon.sh` (restarts `miio_client`/`upgrade` if they die), and finally
runs **`/mnt/UDISK/_root.sh`**, which starts Valetudo with
`VALETUDO_CONFIG_PATH=/mnt/UDISK/valetudo_config.json`. That file is the hook for adding
our own services at boot.

### Processes (docked, idle)

| Process | RSS | Role |
|---|---|---|
| `valetudo` | 59 MB | Web UI + REST API on :80, and the fake cloud that RobotApp talks to |
| `everest-server` | 26 MB | SLAM and navigation (MRPT libraries, Cartographer configs) |
| `RobotApp` | 20 MB | Main application: cleaning logic, voice prompts, miio commands |
| `AuxCtrl` | 5 MB | Serial driver for the MCU and lidar (`ttyS1`, `ttyS3`) |
| `log-server` | 2 MB | Log collection (upload is blackholed) |
| `upgrade` | 2 MB | OTA client |
| `Monitor` | 1.4 MB | Watchdog for the four robot processes above |
| `miio_client` (+ helper) | <1 MB | Xiaomi cloud protocol client, talks to Valetudo's dummy cloud |
| `wifiManager`, `wpa_supplicant`, `udhcpc` | ~2 MB | Wi-Fi |
| `sayeye`, `healthd`, `dropbear`, `adbd`, `netifd`, `logd`, `ubusd`, `procd` | small | System |

### How the pieces talk

```
 phone/laptop ──HTTP :80──► valetudo ──miio over UDP (127.0.0.1:8053 dummy cloud)──┐
                               ▲                                                   │
                               └──────────────── miio_client :54321/udp ◄──────────┘
                                                      ▲  TCP 127.0.0.1:54322
                                                      ▼
                                                  RobotApp ──/tmp/everest_sock──► everest-server (SLAM)
                                                      │                                │
                              /tmp/UDP_*_PATH (unix datagrams: wifi, upgrade, auxctrl) │ /tmp/AuxEverest_Sock
                                                      ▼                                ▼
                                       wifiManager, upgrade                         AuxCtrl ──ttyS3──► STM32 MCU ──► motors,
                                                                                       ▲                          sensors, lidar power
                                                                                       └──ttyS1◄── LDS3 lidar
```

### Serial protocols

Decoded 2026-10-21 by attaching `strace -f -x -s 4096 -e trace=read,write -p $(pidof AuxCtrl)`
for a few seconds, which copies every byte AuxCtrl reads or writes without disturbing it.
**Don't open the ttys yourself:** a second reader steals bytes from AuxCtrl. AuxCtrl reads
the lidar one byte per `read()` from a separate thread, so the strace log is full of
`<unfinished ...>` / `<... read resumed>` pairs, and a parser has to join them per PID.

**Lidar, `ttyS1`** (3irobotix LDS3, checked byte for byte: every frame's checksum matched):

```
AA  len:u16be  01  61  cmd:u8  plen:u16be  payload[plen]  sum:u16be
                                                          sum = (sum of all bytes before it) & 0xFFFF
                                                          len = bytes before the checksum
cmd 0xAE  plen 1   motor speed while spinning up (0 → ~137 over ~1 s)
cmd 0xAD  plen 59/62  scan packet:
          [0]    speed, ~136–137 (matches the measured 1.37 rev/s, so probably 0.01 Hz)
          [1:3]  0x0010, constant
          [3:5]  start angle, u16be, 0.01°: 0, 2250, 4500 … 33750 → 16 packets per turn
          [5: ]  18 or 19 samples × 3 bytes: quality:u8, distance:u16be
```

- **Distance unit: 0.25 mm.** Calibrated by fitting four rotations onto Valetudo's
  wall layer. At 0.25 mm per unit the points sit on average 2.1 cm from the walls (less
  than one 5 cm pixel); at 1 mm the error is 39 cm. Range seen: 0.31–3.99 m.
- Distance `0` means no return. Values with bit `0x4000` set (about 2%) look like a
  flag and should be dropped.
- Sample angle = start + 22.5° × i / n. About 300 points per turn, ~1.2° apart, at
  **1.37 rev/s** (82 rpm), not the ~5 Hz usual for robot lidars.
- Decoder: [`robot/lidar.py`](../robot/lidar.py). `python3 -m robot.lidar --seconds 8`
  captures over SSH while the robot navigates and prints the nearest obstacle per 45°
  sector; `--file` decodes a saved strace log. Standard library only, so it runs on the
  host too.
- Lidar angle 0° was rotated about 336° from the map's +x axis at that moment. That's
  the robot's heading plus the lidar's mounting offset, not separated yet.

**MCU, `ttyS3`** (only partly understood):

```
FA FB  len:u8  type:u8  …            (no checksum check done yet)
MCU → Linux   type 0x15, len 99: status frame at ~22 Hz. Two u16le fields at
              offsets 18 and 26 behave like left/right wheel encoder counts.
Linux → MCU   type 0x66, len 11: drive command at ~50 Hz. All zeros when standing;
              first u16le = 0x035f during a `forward`, another field 0x0209 while
              turning
              type 0x06: poll, ~5 Hz.  type 0x8d 01: sent repeatedly while the lidar
              should run (probably lidar power).  0x9d, 0x0d: rare.
```

During each manual `forward`, both encoder-like fields rose by the same amount: +1287
in the first test, +1273 in the second. So one `forward` is a fixed-length move, and
the MCU status frame is a possible odometry source. Ticks per mm aren't known yet.

Valetudo doesn't touch the hardware. It pretends to be the Xiaomi cloud, and RobotApp
obeys it the way it would obey the Mi Home app. All Xiaomi/3irobotix/Roborock/Dreame
cloud hosts are pointed at `127.0.0.1` in `/etc/hosts`.

### Listening ports

| Port | Proto | Bind | Process | What |
|---|---|---|---|---|
| 22 | tcp | all | dropbear | SSH |
| 80 | tcp | all | valetudo | Web UI + REST API |
| 1900 | udp | all | valetudo | SSDP (UPnP discovery) |
| 5353 | udp | all | valetudo, miio_client | mDNS |
| 54321 | udp | all | miio_client | miio local protocol |
| 41109 | udp | all | valetudo | (ephemeral, outgoing) |
| 5037 | tcp | localhost | adbd | |
| 8079 | tcp | localhost | valetudo | Fake Xiaomi file server (map uploads) |
| 8053 | udp | localhost | valetudo | Fake Xiaomi cloud |
| 54322/54323 | tcp | localhost | miio_client | RobotApp link |

`valetudo_config.json` has `blockExternalAccess: true`, so the web server only answers
private-range addresses.

### Firmware and component versions

| Component | Version |
|---|---|
| Valetudo | 2026.10.0, Node `22.18.0-Valetudo`, heap capped at 42 MB |
| DustBuilder firmware | `0046` (Viomi V6) |
| System (`sysVersion.ini`) | V1.2.46, product `MIIOCRL20S` |
| RobotApp | `V1.2.46.03.28R` |
| Navigation algorithm | `2.0.1.190904_Alpha03` |
| STM32 MCU | `2.0.1_19082728` |
| Lidar | `LDS3_NOR_1805041536` |
| Kernel | Linux 3.4.39, built Nov 2018 with OpenWrt GCC 5.2.0 |

### Tools on the robot

Present: `aplay`, `arecord`, `amixer`, `wget` (+ `wget-ssl`), `iw`, `iwconfig`, `wpa_cli`,
`tcpdump`, `strace`, `lsof`, `htop`, `nano`, `screen`, `gdbserver`, `strings`, `hexdump`,
`hostapd`, `dnsmasq`, `stunnel`.

Missing: `curl`, Python, Lua interpreter, `stty`, `nohup`, `exec-out`. BusyBox `ps`
prints nothing ("Unknown HZ value"); use `htop` or read `/proc/*/cmdline`. To run something
in the background, use `start-stop-daemon -b -m -p <pidfile> -x <prog>`.

Binaries for the robot must be built for **armv7 hard-float**. The system libc is musl
(`rc.local` symlinks `ld-musl-arm.so.1`), so static binaries are the safe bet.

## Valetudo API

Base URL `http://192.168.0.159/api/v2`. Interactive docs at `/swagger/`. No login.

### State right now

| Attribute | Value |
|---|---|
| Status | `docked` |
| Battery | 100%, `charged` |
| Attachments | dustbin ✓, water tank ✗, mop ✗ |
| Operation mode | `vacuum` (also `vacuum_and_mop`, `mop`) |
| Fan speed | `low` (`low`/`medium`/`high`/`max`) |
| Water grade | `medium` (`low`/`medium`/`high`) |
| Do-not-disturb | **on, 23:00–09:00** |
| Carpet mode | off |
| Persistent map | on |
| Clean route | `deep` |
| Consumables left | main brush 17 940 min, side brush 7 140, filter 7 140, mop 10 740 |
| Wi-Fi | `A1_68D50C`, 2.4 GHz, −42 dBm |

### Capabilities (24)

`BasicControl` (start/stop/pause/home), `OperationModeControl`, `FanSpeedControl`,
`WaterUsageControl`, `WifiConfiguration`, `WifiScan`, `Locate` (plays "I'm here"),
`ConsumableMonitoring`, `CurrentStatistics`, `PersistentMapControl`,
`CombinedVirtualRestrictions` (no-go zones and virtual walls), `ZoneCleaning` (up to 10
zones, 1–2 passes), `MapSegmentation`, `MapSegmentEdit`, `MapSegmentRename`, `MapReset`,
`CarpetModeControl`, `SpeakerTest`, `SpeakerVolumeControl`, `DoNotDisturb`,
`VoicePackManagement`, `CleanRouteControl`, `Quirks` (button LEDs on/off, edge-only
cleaning), and **`ManualControl`**.

Not available: `GoToLocation`, `RawCommand`, `ObstacleImages`, any live lidar stream.

### Manual control (the part that matters for ROADMAP stage 5)

```
GET  /robot/capabilities/ManualControlCapability            → {"enabled": false}
GET  /robot/capabilities/ManualControlCapability/properties → forward, backward,
                                                              rotate_clockwise,
                                                              rotate_counterclockwise
PUT  /robot/capabilities/ManualControlCapability  {"action": "enable"}
PUT  /robot/capabilities/ManualControlCapability  {"action": "move", "movementCommand": "forward"}
PUT  /robot/capabilities/ManualControlCapability  {"action": "disable"}
```

A `move` takes a direction, not a distance or a speed, so a `drive(cm)` in the `Body`
interface has to be built from repeated moves.

**First test, 2026-10-21** (robot docked, fully charged):

1. `enable`: status changes from `docked` to `manual_control` straight away. The robot
   stays on the dock and keeps charging.
2. One `forward`: HTTP 200, and the robot **drove off the dock** (seen by eye; the
   distance wasn't measured). Battery changed to `discharging`.
3. `disable`: status `idle`. Then `BasicControlCapability {"action":"home"}`: status
   `returning`, then `docked`/`charging` after **~40 s**.

**The map doesn't show manual moves.** During and after the move,
`/robot/state/map` came back byte-identical (same `nonce`, same `robot_position`). On
this robot the map only refreshes during real runs, so it **can't** be used as
position feedback for manual control. Closed-loop driving will need another source:
the Pi's camera, ArUco markers (ROADMAP stage 4), or timing.

Still to measure: distance per `forward`/`backward`, angle per rotate, and whether the
bumpers and cliff sensors still stop the robot in manual mode.

### Map

`GET /robot/state/map` returns JSON: 5120 × 5120 cm canvas, 5 cm pixels, `floor` and
`wall` layers, `charger_location`, `robot_position`, `path`, plus segments and
restrictions when they exist. Right now there's only a rough first map (~31 m² of floor)
and no rooms; the robot hasn't done a full cleaning run since rooting. One full run will
give a proper map and room segments.

### Other interfaces

- **MQTT:** off. Enabling it (with Home Assistant autodiscovery) is the push alternative
  to polling the REST API.
- **Server-sent events:** `/robot/state/attributes/sse` and `/robot/state/map/sse` push
  changes without polling.
- **NTP:** `valetudo.pool.ntp.org` every 8 h. The first sync after this boot moved the
  clock forward by 14 h.
- **Updater:** GitHub provider, idle, on 2026.10.0.

## Quirks and gotchas

- **Clock.** No working RTC, so after a reboot the clock starts from the last saved
  timestamp until NTP syncs (a minute or so after Wi-Fi). Log timestamps before the
  `Successfully set the robot time via NTP` line are wrong.
- **Timezone.** The system runs in UTC; RobotApp's config says UTC+8 (`timezoneSec=28800`,
  a factory default). Check which one the DND window actually follows before relying on it.
- **Do-not-disturb** is on, 23:00–09:00. On Viomi it mutes voice prompts and blocks
  resuming a cleaning, so expect a quiet robot overnight.
- **Monitor restarts the robot processes.** Killing `RobotApp`, `AuxCtrl` or
  `everest-server` by hand just makes `Monitor` start them again.
- **Overlay is tiny** (8 MB free). Put files in `/mnt/UDISK`.
- **Valetudo memory.** It's capped at a 42 MB heap with `oom_score_adj=666`; anything else
  we run should stay lean so the OOM killer doesn't pick Valetudo.
- **Factory default "rockrobo"** in `/etc/hosts` and the `deviceType`/firm IDs are leftovers
  shared with other CRL-200S clones (Conga, Commodore), not misconfiguration.

## Secrets: where they are, and keep them out of git

Not copied into this doc: `/mnt/SNN/ULI/factory/device_key.txt`, `did_value.txt`,
`/etc/miio/device.token`, `/etc/miio/wifi.conf` and `/etc/wifi/wpa_supplicant.conf`
(Wi-Fi password), and the **CloudSecret/LocalSecret that Valetudo prints in its log at
startup** (`/api/v2/valetudo/log/content`). Don't paste that log into issues or chats.

## What this means for the project

1. **Driving works without new hardware** (tested: one `forward` drove it off the dock).
   `ManualControl` gives forward/back/rotate moves, but there's no position feedback
   during manual control, since the map doesn't update. The wheel-encoder fields on
   `ttyS3` could fill that gap. Whether the bumper and cliff sensors still stop the
   robot in manual mode needs testing; assume they don't until proven.
2. **The camera, mic and Pi must ride on top as a separate unit.** No USB host, no camera
   and no mic on the robot (loopback-tested). The Pi reaches the robot over Wi-Fi (REST API),
   and could run off its own power bank.
3. **The robot can speak with the project's own voice.** Convert Piper's WAV to
   44.1 kHz stereo, copy it over SSH, and `aplay` it with `gpio233` low (recipe in
   [Audio](#audio)). Built in: `speech.output = "viomi"` in `robot.toml`, or
   `make say TEXT=… OUT=viomi` ([docs/TTS.md](TTS.md)).
4. **Raw lidar scans are available** while the robot navigates (not while docked or in
   manual mode): ~300 points per turn at 1.37 rev/s, 0.25 mm units. Useful as a text
   summary for Claude ("wall 0.4 m ahead, open on the left").
5. **Small things could run on the robot itself.** 3 idle cores and ~300 MB free RAM are
   enough for a static armv7 helper (e.g. a tiny HTTP endpoint for speech or lidar),
   started from `_root.sh`. Not for the vision or speech models.
6. **Next experiments:** measure one manual-control move with a tape measure (gives mm
   per `forward` and ticks per mm), and do one full cleaning run for a real map and
   rooms.

## Re-checking

```sh
ssh root@192.168.0.159 'cat /proc/cpuinfo; free; df -h; cat /proc/partitions'
ssh root@192.168.0.159 'for p in /proc/[0-9]*; do echo "${p#/proc/} $(tr "\0" " " < $p/cmdline)"; done'
ssh root@192.168.0.159 'netstat -anp | grep -v ^unix; cat /proc/tty/driver/*'
ssh root@192.168.0.159 'cat /mnt/UDISK/config/{device_config,hwdrivers,motion_params}.ini'
curl -s http://192.168.0.159/api/v2/robot/capabilities
curl -s http://192.168.0.159/api/v2/robot/state/attributes
```
