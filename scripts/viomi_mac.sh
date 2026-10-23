#!/bin/sh
# Prints the vacuum's Wi-Fi MAC (wlan0), read over ssh. Kept out of the docs on purpose.
# Usage: viomi_mac.sh [host]   (default: 192.168.0.159)
set -eu

host="${1:-192.168.0.159}"
ssh root@"$host" cat /sys/class/net/wlan0/address
