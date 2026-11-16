#!/bin/bash
# usage: replay.sh OUT_DIR T...: replay OUT_DIR/can-main.log (from a car run) into the Dashboard alone, one PNG per stop time T
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
O=$(cd "$1" && pwd); shift
WORK="$ROOT/build/work"
export REPLAY_LOG=$O/can-main.log SHARP_MEMLCD_WIDTH=320 SHARP_MEMLCD_HEIGHT=240
for T in "$@"; do
  export SHARP_MEMLCD_PNG_OUT=$O/dash-$T.png SHARP_MEMLCD_STATS_OUT=$O/dash-$T.json SHARP_MEMLCD_FB_OUT=$O/dash-$T.fb
  "${SIM:-sim}" run --scenario "$WORK/scenarios/car/dash-replay.yaml" --timeout "$T" > /dev/null 2> "$O/dash-$T.err"
done
