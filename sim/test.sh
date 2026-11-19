#!/bin/sh
# Runs the committed VCF (Teensy 4.1 front controller, HyTech vehicle firmware + sim patches) on the vcf-enc scenario
# for 3 s of virtual time: MCP3208 pedal ADCs, MCP23017, steering encoder on LPUART4. Pass = firmware boots, prints its
# pedal/ADC tables on the USB console, receives encoder frames, and no fault is reported. SIM = path to the sim binary.
cd "$(dirname "$0")/.." || exit 1
S=$PWD/sim
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
mkdir "$W/out"
cp -R "$S/scenarios" "$S/peers" "$S/standins" "$W/"
ln -s "$S/fw" "$W/elf"
find "$W/scenarios" "$W/peers" "$W/standins" -type f \( -name '*.yaml' -o -name '*.board' -o -name '*.py' \) \
  -exec sed -i.bak -e "s#@SIMANTIC@#$W#g" -e "s#@OUT@#$W/out#g" {} \; -exec rm -f {}.bak \;
export CARLOG=$W/out/can-main.log FULLCAR_OUT=$W/out
(cd "$W" && "${SIM:-sim}" run --scenario scenarios/solo/vcf-enc.yaml --timeout 3 --usb-cdc-console usb1 \
  --output out/uart.txt >out/stdout.txt 2>out/stderr.txt)
rc=$?
# uart.txt lines are "[t] (port) hex bytes"; decode the usb1 payload to text
python3 -I - "$W/out/uart.txt" > "$W/usb.txt" <<'PY'
import re,sys
b=bytearray()
for l in open(sys.argv[1]):
    m=re.match(r'\[[\d.]+s\] \(usb1\) ((?:[0-9A-F]{2} ?)+)',l)
    if m: b+=bytes.fromhex(m.group(1))
sys.stdout.write(b.decode('latin1'))
PY
fail=0
chk() { if grep -qF -- "$2" "$3"; then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }
[ $rc -eq 0 ] && echo "ok   sim exit 0" || { echo "FAIL sim exit $rc"; fail=1; }
chk "pedals banner on USB console" "Pedals Info:" "$W/usb.txt"
chk "accel ADC table printed" "Accel:" "$W/usb.txt"
chk "steering sensor data printed" "Steering Sensor Data:" "$W/usb.txt"
chk "encoder frames reach lpuart4" "(lpuart4" "$W/out/uart.txt"
if grep -qiE 'fault|panic|guru' "$W/out/stderr.txt" "$W/usb.txt" "$W/out/uart.txt"; then echo "FAIL fault/panic line"; fail=1; else echo "ok   no fault/panic"; fi
exit $fail
