# usage: vcrtl.py uart.txt [step_ms]: VCR debug print (USB console) condensed to one row per step (default 250 ms)
import os, re, sys, subprocess
sys.path.insert(0, ".")
txt = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "usbtext.py"), sys.argv[1], "vcr"], capture_output=True, text=True).stdout.splitlines()
step = float(sys.argv[2]) / 1000 if len(sys.argv) > 2 else 0.25
rec = None; recs = []
for l in txt:
    t, _, s = l.partition(" ")
    t = float(t)
    if s.startswith("time"):
        rec = {"t": t}; recs.append(rec); continue
    if rec is None: continue
    m = re.match(r"(\d+)\t:\t([\d.]+)\t:\t([\d.]+)", s)
    if m: rec.update(accel=float(m.group(2)), brake=float(m.group(3)))
    for key, name in (("Drivetrain system state", "dt"), ("Vehicle state machine state", "vs"), ("Start button pressed", "start"), ("mc reset button pressed", "mc"), ("Current Controller Mode", "mode"), ("pedals heartbeat good", "ph"), ("steering heartbeat good", "sh")):
        if s.startswith(key): rec[name] = s.split(":")[-1].strip()
    if s.startswith("Speed (rpm)"): rec["rpm"] = s.split("\t")[1:]
    if s.startswith("Torque Lim"): rec["nm"] = s.split("\t")[1:]
nxt = 0
print("t_s   vs dt accel  brake start mc mode ph sh  rpm(FL..RR)           torque lim (FL..RR)")
for r in recs:
    if r["t"] >= nxt:
        nxt = r["t"] + step
        print("%.3f %2s %2s %5.2f %5.2f  %2s   %2s %3s  %2s %2s  %s  %s" % (r["t"], r.get("vs"), r.get("dt"), r.get("accel", 0), r.get("brake", 0), r.get("start"), r.get("mc"), r.get("mode"), r.get("ph"), r.get("sh"), " ".join(r.get("rpm", [])), " ".join(r.get("nm", []))))
