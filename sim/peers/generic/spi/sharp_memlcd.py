# Sharp LS0xx memory LCD (1 bit per pixel, serial interface) as a scripted SPI peer, with a framebuffer.
# Sources: Sharp "LS013B7DH03", "LS027B7DH01(A)" and "LS032B7DD02" datasheets, section "Serial
# interface / data update mode, all clear mode, VCOM (frame inversion) mode" (command bits M0 = data
# update, M1 = VCOM, M2 = all clear; gate line address, line data, dummy trailers). The Sharp datasheets
# were not available to this repo's tooling, so the byte layout is cross-checked against two shipping
# drivers that run on real panels: Adafruit_SHARP_Memory_Display 1.1.4 (Adafruit_SharpMem.cpp, refresh /
# clearDisplay) and Zephyr drivers/display/ls0xx.c (ls0xx_update_display, ls0xx_clear, VCOM thread).
#
# Wire (SPI mode 0, LSB first, chip select ACTIVE HIGH, no MISO):
#   byte 0   mode: bit0 M0 (1 = data update), bit1 M1 (VCOM level), bit2 M2 (1 = all clear), bits 3-7 dummy 0
#   clear    mode, then 1 dummy byte
#   update   mode, then per line: [gate line address, 1-based] [WIDTH/8 data bytes] [1 dummy byte], then
#            1 more dummy byte for the whole transfer; any number of lines in one chip-select period
#   VCOM     mode with M0 = M2 = 0, then 1 dummy byte: only M1 matters
# The final dummy byte of an update may have any value (Zephyr sends the write command again); a byte
# after it reads as the next line's address, so extra bytes show up as line_address_out_of_range.
# Within a data byte the first pixel on the wire is bit 0, so pixel x of a line is bit (x % 8) of byte
# (x // 8); 1 is white, 0 is black.
#
# The panel shifts LSB first; a pyrite controller hands a scripted slave each byte as it is on the wire,
# MSB first, so this peer reverses every byte it is clocked with (on_transmit). A firmware that
# forgets LSB first (STM32 SPI_CFG2.LSBFRST / CR1.LSBFIRST, Zephyr SPI_TRANSFER_LSB, Arduino
# SPISettings LSBFIRST) therefore draws garbage or raises bad_command, as on a real panel. A
# controller that does not model the bit order (see its model's notes) hands over register bytes.
# Pre-reversing the bytes in software on an MSB-first controller is not modelled.
#
# Wiring (ctx line numbers; the host's own line 0 is the active-LOW chip select of the other peers and is
# NOT used here, since this panel's select is active high):
#   line 1  chip select, ACTIVE HIGH (the host does not frame the transfer: a rise starts it, a fall ends it)
#   line 2  EXTCOMIN (optional): every edge is a VCOM inversion, as the panel's EXTMODE-high mode
# numberOfGpios: 3. The panel size and line format come from env vars (a Slave() takes the same as keywords):
#   SHARP_MEMLCD_WIDTH x SHARP_MEMLCD_HEIGHT   default 400 x 240 (LS027B7DH01); LS013B7DH03 is 128 x 128,
#                                              LS032B7DD02 336 x 536; WIDTH must be a multiple of 8
#   SHARP_MEMLCD_ADDR_BYTES                    gate address width in bytes, 1 (default) or 2; with 2 the
#                                              low byte is first on the wire (the 536-line panel needs 10
#                                              bits). Not checked against a datasheet: use 1 unless known
#   SHARP_MEMLCD_VCOM_S                        longest VCOM interval before vcom_stalled, default 1.0 s
#
# Diagnostics (ctx.warning "DIAG <code>: ..." once per code; all counted in the stats file):
#   bad_command             mode bits 3-7 set, or M0 and M2 together (the transfer is ignored)
#   line_address_out_of_range  gate line 0 or beyond HEIGHT (the line's data is dropped)
#   truncated_line          chip select fell inside a line (data or dummy byte missing, or half an address)
#   missing_end_trailer     an update ended without its final dummy byte
#   trailing_bytes          bytes after a clear / VCOM command's dummy byte
#   byte_without_cs         a byte clocked while chip select is low (ignored)
#   vcom_stalled            no VCOM inversion (M1 change or EXTCOMIN edge) for VCOM_S seconds since the
#                           first command; re-armed by the next inversion
#
# Outputs, when the env var is set, rewritten 2 ms (virtual) after the last chip-select fall:
#   SHARP_MEMLCD_FB_OUT    <- the framebuffer, HEIGHT rows of WIDTH/8 bytes in the wire packing above
#   SHARP_MEMLCD_PNG_OUT   <- the same as an 8-bit grayscale PNG (white 255, black 0)
#   SHARP_MEMLCD_STATS_OUT <- JSON: fb_sha256 (of the FB file), counters, per-command counts, diags
#
# Not modelled: the panel's DISP pin, power-up memory contents (the model starts white), the VCOM
# polarity actually being balanced (only that it inverts), display timing, the 2/3-wire variants.
import hashlib
import json
import os
import struct
import zlib

MODE_WRITE, MODE_VCOM, MODE_CLEAR = 0x01, 0x02, 0x04
CS_LINE, EXTCOMIN_LINE = 1, 2
FLUSH_IDLE_US = 2_000
TICK_US = 2_000


def png_gray(width, height, rows):
    """8-bit grayscale PNG from `rows`, one bytes object per row."""
    raw = b"".join(b"\0" + r for r in rows)

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


class Slave:
    def __init__(self, ctx, width=None, height=None, addr_bytes=None, vcom_s=None):
        env = os.environ.get
        self.ctx = ctx
        self.w = int(width or env("SHARP_MEMLCD_WIDTH", 400))
        self.h = int(height or env("SHARP_MEMLCD_HEIGHT", 240))
        self.addr_bytes = int(addr_bytes or env("SHARP_MEMLCD_ADDR_BYTES", 1))
        self.vcom_us = int(float(vcom_s or env("SHARP_MEMLCD_VCOM_S", 1.0)) * 1e6)
        assert self.w % 8 == 0 and self.addr_bytes in (1, 2)
        self.stride = self.w // 8
        self.fb = bytearray(b"\xff" * (self.stride * self.h))
        self.cs = False
        self.diags = {}
        self.cmds = {"write": 0, "clear": 0, "vcom": 0, "bad": 0}
        self.lines = 0
        self.vcom = None  # last M1 level seen, or EXTCOMIN level
        self.toggles = 0
        self.vcom_t = None  # time of the first command, then of the latest inversion
        self.vcom_alarm = False
        self.dirty = False
        self.fb_dirty = True
        self.idle_t = None
        self.reset_frame()
        self.fb_path = env("SHARP_MEMLCD_FB_OUT")
        self.png_path = env("SHARP_MEMLCD_PNG_OUT")
        self.stats_path = env("SHARP_MEMLCD_STATS_OUT")
        ctx.schedule_periodic(TICK_US, self.tick)

    def reset_frame(self):
        self.kind = None  # None: next byte is the mode byte; then "write", "clear", "vcom" or "bad"
        self.phase = "addr"  # write: addr -> data -> dummy -> addr ...
        self.addr = []  # address bytes of the line being received
        self.row = None  # row the data bytes go to, None when its address was out of range
        self.pos = 0  # data bytes received on this line
        self.tail = 0  # dummy bytes owed after a clear / vcom command

    def diag(self, code, msg):
        n = self.diags.get(code, 0)
        self.diags[code] = n + 1
        self.dirty = True
        if n == 0:
            self.ctx.warning("DIAG %s: %s" % (code, msg))

    # --- host callbacks ----------------------------------------------------------------------
    def on_select(self):
        pass

    def on_deselect(self):
        pass

    def on_finish(self):
        pass

    def on_gpio(self, line, level):
        level = bool(level)
        if line == CS_LINE:
            if level and not self.cs:
                self.cs = True
                self.reset_frame()
            elif not level and self.cs:
                self.cs = False
                self.end_frame()
        elif line == EXTCOMIN_LINE and self.vcom != level:
            self.invert(level)

    def on_transmit(self, b):
        b = int("{:08b}".format(b)[::-1], 2)  # the panel shifts LSB first
        if not self.cs:
            self.diag("byte_without_cs", "byte 0x%02X while chip select is low" % b)
            return 0
        if self.kind is None:
            self.mode_byte(b)
        elif self.kind == "write":
            self.write_byte(b)
        elif self.kind in ("clear", "vcom"):
            self.tail -= 1
            if self.tail < 0:
                self.diag("trailing_bytes", "byte 0x%02X after the %s command's dummy byte" % (b, self.kind))
        return 0

    # --- protocol ----------------------------------------------------------------------------
    def invert(self, level):
        now = self.ctx.now_us
        if self.vcom is not None:
            self.toggles += 1
        self.vcom = level
        self.vcom_t = now
        self.vcom_alarm = False
        self.dirty = True

    def mode_byte(self, b):
        now = self.ctx.now_us
        if self.vcom_t is None:
            self.vcom_t = now
        if b & 0xF8 or (b & MODE_WRITE and b & MODE_CLEAR):
            self.kind = "bad"
            self.cmds["bad"] += 1
            self.diag("bad_command", "mode byte 0x%02X (M0/M1/M2 are bits 0-2, bits 3-7 are dummy)" % b)
            return
        if bool(b & MODE_VCOM) != self.vcom:
            self.invert(bool(b & MODE_VCOM))
        if b & MODE_WRITE:
            self.kind = "write"
            self.cmds["write"] += 1
        elif b & MODE_CLEAR:
            self.kind = "clear"
            self.cmds["clear"] += 1
            self.tail = 1
            self.fb[:] = b"\xff" * len(self.fb)
            self.fb_dirty = True
        else:
            self.kind = "vcom"
            self.cmds["vcom"] += 1
            self.tail = 1
        self.dirty = True

    def write_byte(self, b):
        if self.phase == "addr":
            if len(self.addr) < self.addr_bytes:
                self.addr.append(b)
                return
            # A full address is validated by the byte after it: the transfer's final dummy byte
            # looks like an address of 0 until chip select falls.
            self.start_line()
        if self.phase == "data":
            if self.row is not None:
                self.fb[self.row * self.stride + self.pos] = b
                self.fb_dirty = True
            self.pos += 1
            if self.pos == self.stride:
                self.phase = "dummy"
                self.lines += self.row is not None
                self.dirty = True
        else:
            self.phase = "addr"
            self.addr = []

    def start_line(self):
        a = self.addr[0] | (self.addr[1] << 8 if self.addr_bytes == 2 else 0)
        self.phase = "data"
        self.pos = 0
        if 1 <= a <= self.h:
            self.row = a - 1
        else:
            self.row = None
            self.diag("line_address_out_of_range", "gate line %d (panel has 1..%d)" % (a, self.h))

    def end_frame(self):
        self.idle_t = self.ctx.now_us
        self.dirty = True
        if self.kind in ("clear", "vcom") and self.tail > 0:
            self.diag("truncated_line", "%s command ended without its dummy byte" % self.kind)
        if self.kind != "write":
            return
        if self.phase == "data":
            self.diag("truncated_line", "chip select fell after %d of %d data bytes" % (self.pos, self.stride))
        elif self.phase == "dummy":
            self.diag("truncated_line", "chip select fell before the line's dummy byte")
        elif not self.addr:
            self.diag("missing_end_trailer", "update ended without its final dummy byte")
        elif len(self.addr) > 1:
            self.diag("truncated_line", "chip select fell inside the gate line address %s" % self.addr)

    # --- time --------------------------------------------------------------------------------
    def tick(self):
        now = self.ctx.now_us
        if self.vcom_t is not None and not self.vcom_alarm and now - self.vcom_t >= self.vcom_us:
            self.vcom_alarm = True
            self.diag("vcom_stalled", "no VCOM inversion for %.2f s" % ((now - self.vcom_t) / 1e6))
        if self.dirty and not self.cs and (self.idle_t is None or now - self.idle_t >= FLUSH_IDLE_US):
            self.flush()

    # --- outputs -----------------------------------------------------------------------------
    def rows_gray(self):
        for y in range(self.h):
            r = self.fb[y * self.stride:(y + 1) * self.stride]
            yield bytes(255 if r[x >> 3] >> (x & 7) & 1 else 0 for x in range(self.w))

    def flush(self):
        self.dirty = False
        fb = bytes(self.fb)
        if self.fb_dirty:
            self.fb_dirty = False
            if self.fb_path:
                with open(self.fb_path, "wb") as f:
                    f.write(fb)
            if self.png_path:
                with open(self.png_path, "wb") as f:
                    f.write(png_gray(self.w, self.h, self.rows_gray()))
        if self.stats_path:
            with open(self.stats_path, "w") as f:
                json.dump({"width": self.w, "height": self.h, "fb_sha256": hashlib.sha256(fb).hexdigest(),
                           "cmds": self.cmds, "lines": self.lines, "vcom_toggles": self.toggles,
                           "diags": self.diags, "now_us": self.ctx.now_us}, f)
