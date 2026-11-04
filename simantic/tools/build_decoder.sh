#!/bin/bash
# Builds build/htcan_dec from the firmware's generated CAN library (needs build.sh to have run once): reads "id hexbytes" lines on stdin.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LIB=$(ls -d "$ROOT"/build/src/.pio/libdeps/*/can_lib/lib | head -1)
mkdir -p "$ROOT/build/dec" && cd "$ROOT/build/dec"
python3 -I "$ROOT/tools/gen_htcan.py" "$LIB"
cc -O1 -I"$LIB" -I"$LIB/../conf" -o "$ROOT/build/htcan_dec" htcan_dec.c "$LIB/ht_can.c"
