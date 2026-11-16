# usage: usbtext.py uart.txt machine (single-machine runs have no machine prefix; any name matches)
# usage: usbtext.py uart.txt machine [t0 t1]: decode "(usb1) hex bytes" lines of one machine into text with the time of each line's first byte
import re, sys
m = sys.argv[2]; t0 = float(sys.argv[3]) if len(sys.argv) > 3 else 0; t1 = float(sys.argv[4]) if len(sys.argv) > 4 else 1e9
buf = ""; start = None
rx = re.compile(r'(?:\[(\w+)\] )?\[([\d.]+)s\] \(usb1\) ((?:[0-9A-F]{2} ?)+)')
for l in open(sys.argv[1], errors='replace'):
    g = rx.match(l)
    if not g or (g.group(1) or m) != m: continue
    t = float(g.group(2))
    if not (t0 <= t <= t1): continue
    s = bytes(int(x, 16) for x in g.group(3).split()).decode('latin1')
    if start is None: start = t
    buf += s
    while "\n" in buf:
        line, buf = buf.split("\n", 1)
        print("%.3f %s" % (start, line.rstrip("\r"))); start = t
