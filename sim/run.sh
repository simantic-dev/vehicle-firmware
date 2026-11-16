#!/bin/bash
# Runs one scenario with pyrite's `sim` binary and leaves the evidence in build/out/TAG.
# usage: run.sh SCENARIO [TAG] [TIMEOUT_S] [extra sim args]
#   SCENARIO: car | charge | vcf-enc | vcf-i2c | vcr-rtd | acu | ccu | dash
#   env: SIM (path to the sim binary, default: sim),
#        RTD_PLAN (vcr-rtd only: A, B, C or D, default A)
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
SC=${1:?scenario}; TAG=${2:-$SC}; TO=${3:-}
shift; shift || true; shift || true
SIM="${SIM:-sim}"
WORK="$HERE/build/work"; OUT="$HERE/build/out/$TAG"
mkdir -p "$WORK" "$OUT"
# scenario, board and peer files carry @SIMANTIC@ / @OUT@ placeholders; expand them into a work copy
(cd "$HERE" && rsync -a --delete scenarios peers standins "$WORK/")
ln -sfn "$HERE/build/elf" "$WORK/elf"
find "$WORK/scenarios" "$WORK/peers" "$WORK/standins" -type f \( -name '*.yaml' -o -name '*.board' -o -name '*.py' \) \
  -exec sed -i.bak -e "s#@SIMANTIC@#$WORK#g" -e "s#@OUT@#$OUT#g" {} \; -exec rm -f {}.bak \;
case $SC in
  car|charge|dash-replay) Y=$WORK/scenarios/car/$SC.yaml; ;;
  vcf-enc|vcf-i2c|vcr-rtd|acu|ccu|dash) Y=$WORK/scenarios/solo/$SC.yaml; ;;
  *) echo "unknown scenario $SC" >&2; exit 1 ;;
esac
export CARLOG=$OUT/can-main.log FULLCAR_OUT=$OUT RTD_OUT=$OUT RTD_PLAN=${RTD_PLAN:-A}
export SHARP_MEMLCD_WIDTH=320 SHARP_MEMLCD_HEIGHT=240 SHARP_MEMLCD_FB_OUT=$OUT/dash.fb SHARP_MEMLCD_PNG_OUT=$OUT/dash.png SHARP_MEMLCD_STATS_OUT=$OUT/dash.json
export ILI9341_FB_OUT=$OUT/ccu.fb ILI9341_STATS_OUT=$OUT/ccu.json
TOARG=(); [ -n "$TO" ] && TOARG=(--timeout "$TO")
USB="--usb-cdc-console usb1"; case $SC in dash|dash-replay) USB=;; esac   # the Dash has no USB console
cd "$WORK"
/usr/bin/time -p "$SIM" run --scenario "$Y" "${TOARG[@]}" $USB --output "$OUT/uart.txt" "$@" > "$OUT/stdout.txt" 2> "$OUT/stderr.txt"
echo "done: $OUT (uart.txt: USB consoles, stderr.txt: stand-in logs)"
