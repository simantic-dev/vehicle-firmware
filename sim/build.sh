#!/bin/bash
# Builds the firmware ELFs the scenarios use: copies the repo to build/src, applies patches/*.patch, runs PlatformIO,
# and copies build/elf/{vcf,vcr,acu,ccu,dash}.elf. The source tree itself is never modified.
# usage: build.sh [vcf vcr acu ccu dash ...]   (default: all five)
# env:   PIO (default: pio), PATCHES=0 to build the unpatched firmware
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
PIO="${PIO:-pio}"
SRC="$HERE/build/src"
mkdir -p "$SRC" "$HERE/build/elf"
rsync -a --delete --exclude .git --exclude /sim --exclude .pio "$ROOT/" "$SRC/"
if [ "${PATCHES:-1}" != 0 ]; then
  for p in "$HERE"/patches/*.patch; do patch -s -d "$SRC" -p1 < "$p"; done
fi
board_env() { case $1 in vcf) echo vcf-prod;; vcr) echo vcr-prod;; acu) echo acu-prod;; ccu) echo ccu-prod;; dash) echo dash-dfu-prod;; *) echo "unknown board $1" >&2; exit 1;; esac; }
for b in ${@:-vcf vcr acu ccu dash}; do
  e=$(board_env "$b")
  "$PIO" run -d "$SRC" -e "$e"
  cp "$SRC/.pio/build/$e/firmware.elf" "$HERE/build/elf/$b.elf"
done
