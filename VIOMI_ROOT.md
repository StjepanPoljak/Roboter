# Rooting the Viomi V2 vacuum (Valetudo)

Our robot: **Viomi V2, model V-RVCLM21B**. After a Wi-Fi reset it creates the access point
`viomi-vacuum-v6_miap0791`, so it's a **viomi.vacuum.v6** (3irobotix CRL-200S hardware).

Sources, checked 2026-10-20:
- Valetudo supported robots: https://valetudo.cloud/pages/general/supported-robots/
  ("Viomi V6", also sold as Viomi V2 / V2 Pro / V-RVCLM21B)
- Rooting tools and instructions: https://github.com/Hypfer/valetudo-crl200s-root

Re-check both pages before starting; they change over time.

## Warnings

- "In general, rooting vacuum robots is a dangerous procedure that can lead to unfixable
  bricks." "Make sure to not attempt to root anything that you can't afford to lose."
- **Never root a `viomi.vacuum.v8`.** Many units brick unrecoverably. Ours is a **v6**
  (checked from the SSID above), which is the supported variant.
- Cecotec Conga 3090: will brick. Not our robot, but don't reuse this guide for one.
- If anything doesn't match this guide, stop and ask in the Valetudo community first.

## What you need

- Linux laptop with `adb`: `sudo apt install adb`
- A micro-USB cable that carries **data** (many cheap cables are charge-only)
- The robot, charged
- No need to connect the robot to Wi-Fi or the Viomi app; everything happens over USB

## 1. Find the USB port

- Some units have a micro-USB port on the **back**. Use it if present.
- Otherwise, use the micro-USB port in the **battery compartment**. Opening it doesn't break
  warranty seals.

## 2. Check ADB

Boot the robot, plug it in, then:

```sh
adb devices
adb shell
```

- **Root shell straight away:** go to step 4.
- **`TinaLinux login:` prompt:** do step 3b.
- **Device appears only briefly at boot, then `no devices found`:** do step 3a.

## 3a. Enable ADB (only if it vanishes after boot)

Download `enable-adb.sh` from the root repo and run it, following its instructions.
You should end up with a password-less root shell via `adb shell`.

## 3b. Get past the login prompt (only if you see `TinaLinux login:`)

```sh
cat > adb_shell <<'EOF'
#!/bin/sh
export ENV='/etc/adb_profile'
exec /bin/sh "$@"
EOF
chmod +x adb_shell
adb push ./adb_shell /bin/adb_shell
adb shell        # should now be a root shell without a password
```

## 4. Back up everything. Don't skip this.

```sh
mkdir -p ~/Develop/Robot/viomi-backup && cd ~/Develop/Robot/viomi-backup
adb pull /proc/partitions
for p in nanda nandb nandc nandd nande nandf nandg nandh nandi; do adb pull /dev/$p; done
cat partitions        # pull any extra nand* partitions listed here too
ls -la                # every file should have a sensible, non-zero size
```

Keep this folder safe (copy it somewhere else too). It's the only way back to stock.
`viomi-backup/` is not in git; don't commit it, since it contains device-specific keys.

## 5. Build the firmware

At https://builder.dontvacuum.me, build a firmware package for **manual installation**
for this robot. The download link (`.tar.gz`) arrives by email.

Valetudo's docs recommend running the robot on Viomi V6 firmware, "as that has more features".

## 6. Install

Download the latest Valetudo binary:
https://github.com/Hypfer/Valetudo/releases/latest/download/valetudo-armv7.upx

Get `convert-robot.sh` from the root repo. Then:

```sh
adb push ./<rooted_firmware_filename>.tar.gz /tmp/
adb push ./valetudo-armv7.upx /mnt/UDISK/valetudo     # exactly this path
adb push ./convert-robot.sh /tmp/
adb shell
```

In the robot's shell:

```sh
cd /tmp/
sh ./convert-robot.sh
tar xzvf ./<rooted_firmware_filename>.tar.gz
sh ./install.sh
```

Skip the repo's RTL8821CS step (`/opt/8821cs/enable_8821cs.sh`). It's only for Conga
3690/3790 and Commodore CVR 200.

## 7. Join Wi-Fi

1. Press and hold **both buttons** until the robot announces that Wi-Fi has been reset.
2. Follow https://valetudo.cloud/pages/general/getting-started.html#joining_wifi
3. Open the Valetudo web UI at the robot's IP. Give it a fixed IP in your router.

## Troubleshooting

- **`adb devices` is empty:** try another cable first (data cable!), then a USB port
  directly on the laptop (no hub), then another computer.
- **Last resort from the repo:** a community method of powering off, holding Home while
  connecting USB, then pressing power about 10 times. The repo author says it didn't work
  for them, so treat it with caution.

## After rooting: next steps for the robot project

- [ ] Check Valetudo's API (`http://<robot-ip>/swagger/`) for **manual control** /
      remote-control capabilities. That decides whether the vacuum can be driven
      step by step ("forward 30 cm") or only sent to map points.
- [ ] Add a `ValetudoBody` backend in `robot/` (see ROADMAP.md, stage 5).
- [ ] Mount the camera, speaker (and later the Pi) on top of the vacuum.
