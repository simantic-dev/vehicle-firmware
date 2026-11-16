# usage: fb2png.py ccu.fb out.png  -- ILI9341 frame memory (240x320 RGB565, panel order) to an upright 320x240 PNG (MADCTL 0xE8: transpose, then 180 deg)
import sys, struct, zlib
raw = open(sys.argv[1], "rb").read()
W, H = 240, 320
px = struct.unpack("<%dH" % (W * H), raw)
rows = []
for y in range(240):
    row = bytearray([0])
    for x in range(320):
        # upright (x, y) comes from memory (col=239-y, row=319-x)
        v = px[(319 - x) * W + (239 - y)]
        r, g, b = (v >> 11) & 31, (v >> 5) & 63, v & 31
        row += bytes((r * 255 // 31, g * 255 // 63, b * 255 // 31))
    rows.append(bytes(row))
def chunk(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 320, 240, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b"")
open(sys.argv[2], "wb").write(png)
