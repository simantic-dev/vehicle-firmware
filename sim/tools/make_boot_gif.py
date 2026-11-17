"""Build screenshots/vcf-boot-playback.gif from a captured run (captures/vcf-enc-uart.txt) only.
usage: make_boot_gif.py UART_TXT OUT_GIF "sim version string" "wall time"
Reveals usb1 console lines and lpuart4 encoder traffic at their recorded virtual timestamps."""
import re, sys, io
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image
src, out, ver, wall = sys.argv[1:5]
usb = bytearray(); usb_t = []; rx = []; tx = []
for l in open(src, errors="replace"):
    m = re.match(r"\[([\d.]+)s\] \((\S+)(?: (←|→) (\S+))?\) ([0-9A-F ]+)$", l.strip())
    if not m: continue
    t, port, arrow, _, hx = m.groups(); t = float(t); b = bytes.fromhex(hx.replace(" ", ""))
    if port == "usb1":
        usb += b; usb_t += [t] * len(b)
    elif arrow == "←": rx.append(t)
    else: tx.append(t)
lines = []; s = 0
for i, c in enumerate(usb):
    if c == 10:
        lines.append((usb_t[i], usb[s:i].decode("latin1").replace("\r", "").replace("\t", "  "))); s = i + 1
lines = [x for x in lines if x[1].strip()]
T = max(rx[-1], lines[-1][0]) if lines else rx[-1]; N = 60
frames = []
for k in range(N + 1):
    t = T * k / N
    fig = plt.figure(figsize=(8, 4.5), dpi=100)
    ax = fig.add_axes([0.2, 0.62, 0.75, 0.22]); ax.set_xlim(0, T)
    ax.set_ylim(0, 2); ax.set_yticks([0.5, 1.5]); ax.set_yticklabels(["enc tx (lpuart4 →)", "enc rx (lpuart4 ←)"], fontsize=7)
    ax.eventplot([[x for x in tx if x <= t], [x for x in rx if x <= t]], lineoffsets=[0.5, 1.5], linelengths=0.8, linewidths=0.4)
    ax.axvline(t, color="r", lw=1); ax.set_xlabel("virtual time (s)", fontsize=7); ax.tick_params(labelsize=7)
    vis = [x for x in lines if x[0] <= t][-12:]
    fig.text(0.05, 0.57, "VCF USB console (usb1), lines as they appeared", fontsize=7, va="top")
    fig.text(0.05, 0.53, "\n".join("%.3fs  %s" % (a, b[:90]) for a, b in vis), family="monospace", fontsize=6.5, va="top")
    fig.text(0.05, 0.94, "HyTech VCF (Teensy 4.1, i.MX RT1062) boot, t = %.2f s" % t, fontsize=11, weight="bold")
    fig.text(0.05, 0.895, "playback of a captured run (virtual time), not real time. %s, wall %s" % (ver, wall), fontsize=7)
    buf = io.BytesIO(); fig.savefig(buf, format="png"); plt.close(fig)
    frames.append(Image.open(io.BytesIO(buf.getvalue())).convert("RGB").quantize(48))
frames[0].save(out, save_all=True, append_images=frames[1:], duration=[200] * N + [2500], loop=0, optimize=True)
