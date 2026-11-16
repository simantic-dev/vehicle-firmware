# usage: declog.py can-main.log ID[,ID..] [t0 t1]  -> "t_s id data | decoded" using the decoder built by tools/build_decoder.sh
import os, sys, subprocess
f = sys.argv[1]; ids = {int(x, 16) for x in sys.argv[2].split(',')}
t0 = float(sys.argv[3]) if len(sys.argv) > 3 else 0; t1 = float(sys.argv[4]) if len(sys.argv) > 4 else 1e9
rows = []
for l in open(f):
    p = l.split()
    if len(p) < 2: continue
    t = int(p[0]) / 1e6; i = int(p[1], 16)
    if i in ids and t0 <= t <= t1: rows.append((t, i, p[2] if len(p) > 2 else ''))
inp = ''.join('%x %s\n' % (r[1], r[2] or '00') for r in rows)
out = subprocess.run([os.environ.get('HTCAN_DEC') or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'build', 'htcan_dec')], input=inp, capture_output=True, text=True).stdout.splitlines()
for r, o in zip(rows, out): print("%.4f 0x%X %s | %s" % (r[0], r[1], r[2], o))
