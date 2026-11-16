# Ilitek ILI9341 240x320 TFT controller as a scripted SPI peer (4-wire, 16 bpp), with a frame memory.
# Source: ILI9341 datasheet V1.11, section cited per behaviour.
#
# Wiring (ctx line numbers, as in ssd1677.py / lsm6dsr.py):
#   line 0  chip select (active low; the host mirrors the select edges, declare `<cs pad> -> tft@0`)
#   line 1  D/CX from the MCU: low = command byte, high = parameter / pixel / read byte
#   line 2  RESET from the MCU, active low (the low level is a hardware reset; bytes while it is low
#           are ignored, and the 5 ms / 120 ms settle times run from the rising edge)
# numberOfGpios: 3.
#
# Modelled: NOP 00, SWRESET 01, the read commands 09/0A/0B/0C/0D/0E/0F/D3 (defaults and the
# bits that follow the commands below, section 8.2.3-8.2.10, 8.3), SLPIN 10 / SLPOUT 11, PTLON 12 /
# NORON 13, INVOFF 20 / INVON 21, GAMSET 26, DISPOFF 28 / DISPON 29, CASET 2A, PASET 2B, RAMWR 2C,
# RAMRD 2E (returns 0), MADCTL 36, IDMOFF 38 / IDMON 39, COLMOD 3A, RAMWRC 3C, and the 0xD9 index
# register Adafruit_ILI9341::readcommand8 uses. The frame memory is 240 x 320 RGB565 words in
# panel memory order: a window pixel (c, r) lands at memory (col, row) after MADCTL MV exchanges the
# window axes, then MX / MY mirror column / row (8.2.29). The BGR bit changes the read-back
# only, not the stored words. Every other command (power, gamma, frame-rate, display-function
# control, ...) takes its parameters and is counted as `ignored`.
#
# Timing keys (ns; the overlay `script:` line may set them, defaults are the datasheet waits):
#   RESET_SETTLE_NS  5 ms before the next command after SWRESET or a hardware reset (8.2.2)
#   SLEEP_SETTLE_NS  120 ms before the next command after SLPOUT (8.2.12)
# Config (`config:` JSON in the overlay, ctx.config): reset_settle_ns, sleep_settle_ns (each defaults to the
#   constant of the same name above).
#
# Diagnostics (ctx.warning "DIAG <code>: ..."; all counted in the stats file): sleep_out_missing
# (DISPON or RAMWR while still in sleep-in since reset), cmd_in_reset_settle (a command inside the 5 ms
# after a reset, 8.2.2), slpout_in_reset_settle (SLPOUT inside the 120 ms after a reset),
# window_out_of_range (CASET / PASET end beyond the MV-dependent panel size, 8.2.20-21),
# pixel_format_unsupported (RAMWR while COLMOD is not 16 bpp), unknown_command.
#
# Outputs, when the env var is set: ILI9341_FB_OUT <- the frame memory (raw little-endian u16,
# 240*320), ILI9341_STREAM_OUT <- every byte as a u16 (D/CX << 8 | MOSI), ILI9341_STATS_OUT <- JSON.
# They are rewritten 2 ms (virtual) after the last chip-select release.
#
# Not modelled: 18 bpp and the 6-bit-3-times RGB modes, partial area, vertical scroll, tearing
# effect output, idle-mode colour reduction, gamma, NVM ID registers, RAM read-back, the
# 120 ms Sleep-In settle, display timing (the frame memory is the whole display).
import json
import os
from array import array

W, H = 240, 320
RESET_SETTLE_NS = globals().get("RESET_SETTLE_NS", 5_000_000)
SLEEP_SETTLE_NS = globals().get("SLEEP_SETTLE_NS", 120_000_000)
RESET_SETTLE_US = RESET_SETTLE_NS // 1000
SLEEP_SETTLE_US = SLEEP_SETTLE_NS // 1000
FLUSH_IDLE_US = 2_000

NOP, SWRESET, RDDST, RDDPM, RDDMADCTL, RDDCOLMOD, RDDIM, RDDSM, RDDSDR = (
    0x00, 0x01, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F)
SLPIN, SLPOUT, PTLON, NORON, INVOFF, INVON, GAMSET, DISPOFF, DISPON = (
    0x10, 0x11, 0x12, 0x13, 0x20, 0x21, 0x26, 0x28, 0x29)
CASET, PASET, RAMWR, RAMRD, MADCTL, IDMOFF, IDMON, COLMOD, RAMWRC = (
    0x2A, 0x2B, 0x2C, 0x2E, 0x36, 0x38, 0x39, 0x3A, 0x3C)
IDX, RDID4 = 0xD9, 0xD3
# Commands that only take parameters we don't model: count of parameter bytes (8.3, 8.4).
IGNORED = {0x30: 4, 0x33: 6, 0x34: 0, 0x35: 1, 0x37: 2, 0x44: 2, 0x51: 1, 0x53: 1, 0x55: 1, 0x5E: 1,
           0xB0: 1, 0xB1: 2, 0xB2: 2, 0xB3: 2, 0xB4: 1, 0xB5: 4, 0xB6: 4, 0xB7: 1, 0xC0: 1, 0xC1: 1,
           0xC5: 2, 0xC7: 1, 0xCB: 5, 0xCF: 3, 0xE0: 15, 0xE1: 15, 0xE8: 3, 0xE9: 1, 0xEA: 2, 0xED: 4,
           0xEF: 3, 0xF2: 1, 0xF6: 3, 0xF7: 1}


class Slave:
    def __init__(self, ctx):
        self.ctx = ctx
        cfg = getattr(ctx, "config", None) or {}
        self.reset_settle_us = int(cfg.get("reset_settle_ns", RESET_SETTLE_NS)) // 1000
        self.sleep_settle_us = int(cfg.get("sleep_settle_ns", SLEEP_SETTLE_NS)) // 1000
        self.ram = array("H", bytes(2 * W * H))
        self.dc = 0
        self.stream = array("H")
        self.diags = {}
        self.ignored = 0
        self.cmds = {}
        self.reset_t = -10**9
        self.in_reset = False
        self.slpout_t = -10**9
        self.hw_reset()
        self.stream_path = os.environ.get("ILI9341_STREAM_OUT")
        self.fb_path = os.environ.get("ILI9341_FB_OUT")
        self.stats_path = os.environ.get("ILI9341_STATS_OUT")

    # --- state -------------------------------------------------------------------------------
    def hw_reset(self):
        self.sleep = True
        self.display_on = False
        self.madctl = 0x00
        self.colmod = 0x66  # COLMOD hardware-reset value DPI=110 DBI=110 (8.2.33)
        self.colmod_set = False  # RDDCOLMOD reads 0x06 until COLMOD is written (8.2.7)
        self.inv = False
        self.idle = False
        self.partial = False
        self.normal = True
        self.sc, self.ec, self.sp, self.ep = 0, W - 1, 0, H - 1
        self.cmd = None
        self.params = []
        self.need = 0
        self.rd_pos = 0
        self.idx = 0
        self.c = self.r = 0
        self.hi = None
        self.woke = False  # RAMWR in sleep diagnosed once per sleep period
        self.fmt_diag = False

    def sw_reset(self):
        madctl = self.madctl  # MADCTL keeps its value across SWRESET (8.2.6)
        self.hw_reset()
        self.madctl = madctl

    def diag(self, code, msg):
        n = self.diags.get(code, 0)
        self.diags[code] = n + 1
        if n == 0:
            self.ctx.warning("DIAG %s: %s" % (code, msg))

    # --- host callbacks ----------------------------------------------------------------------
    def on_gpio(self, line, level):
        if line == 1:
            self.dc = 1 if level else 0
        elif line == 2:
            if not level:
                self.hw_reset()
                self.in_reset = True
            elif self.in_reset:
                self.in_reset = False
                self.reset_t = self.ctx.now_us  # the 5 ms / 120 ms waits run from RESX release (8.2.2)

    def on_select(self):
        pass

    def on_deselect(self):
        self.ctx.schedule_oneshot(FLUSH_IDLE_US, self.flush)

    def on_finish(self):
        pass

    def on_transmit(self, b):
        if self.in_reset:
            return 0
        self.stream.append((self.dc << 8) | b)
        if self.dc:
            return self.data(b)
        self.command(b)
        return 0

    # --- command phase -----------------------------------------------------------------------
    def command(self, c):
        now = self.ctx.now_us
        self.cmds[c] = self.cmds.get(c, 0) + 1
        if c != NOP and now - self.reset_t < self.reset_settle_us and c != SWRESET:
            self.diag("cmd_in_reset_settle", "command 0x%02X %d us after reset (needs 5 ms)" % (c, now - self.reset_t))
        self.cmd = c
        self.params = []
        self.rd_pos = 0
        self.need = 0
        if c == SWRESET:
            self.sw_reset()
            self.reset_t = now
        elif c == SLPOUT:
            if now - self.reset_t < self.sleep_settle_us:
                self.diag("slpout_in_reset_settle", "SLPOUT %d us after reset (needs 120 ms)" % (now - self.reset_t))
            self.sleep = False
            self.slpout_t = now
        elif c == SLPIN:
            self.sleep = True
        elif c == DISPON:
            self.display_on = True
            if self.sleep:
                self.diag("sleep_out_missing", "DISPON while the panel is still in sleep (no SLPOUT since reset)")
        elif c == DISPOFF:
            self.display_on = False
        elif c == PTLON:
            self.partial = True
        elif c == NORON:
            self.partial = False
        elif c == INVON:
            self.inv = True
        elif c == INVOFF:
            self.inv = False
        elif c == IDMON:
            self.idle = True
        elif c == IDMOFF:
            self.idle = False
        elif c == RAMWR:
            self.c, self.r = self.sc, self.sp
            self.hi = None
            if self.sleep and not self.woke:
                self.woke = True
                self.diag("sleep_out_missing", "RAMWR while the panel is in sleep (no SLPOUT since reset)")
        elif c == RAMWRC:
            self.hi = None
        elif c in (CASET, PASET):
            self.need = 4
        elif c in (MADCTL, COLMOD, IDX):
            self.need = 1
        elif c in IGNORED:
            self.need = IGNORED[c]
            self.ignored += 1
        elif c in (NOP, GAMSET, RAMRD, RDDST, RDDPM, RDDMADCTL, RDDCOLMOD, RDDIM, RDDSM, RDDSDR, RDID4):
            if c == GAMSET:
                self.need = 1
        else:
            self.diag("unknown_command", "command 0x%02X" % c)

    # --- data phase --------------------------------------------------------------------------
    def data(self, b):
        c = self.cmd
        if c == RAMWR or c == RAMWRC:
            return self.pixel_byte(b)
        if self.need:
            self.params.append(b)
            if len(self.params) == self.need:
                self.apply()
                self.need = 0
            return 0
        if c in READS:
            v = self.read_param(c, self.rd_pos)
            self.rd_pos += 1
            return v
        return 0

    def apply(self):
        c, p = self.cmd, self.params
        if c == CASET:
            self.sc, self.ec = (p[0] << 8) | p[1], (p[2] << 8) | p[3]
            lim = (H if self.madctl & 0x20 else W) - 1
            if self.ec > lim or self.sc > self.ec:
                self.diag("window_out_of_range", "CASET %d..%d (limit %d)" % (self.sc, self.ec, lim))
        elif c == PASET:
            self.sp, self.ep = (p[0] << 8) | p[1], (p[2] << 8) | p[3]
            lim = (W if self.madctl & 0x20 else H) - 1
            if self.ep > lim or self.sp > self.ep:
                self.diag("window_out_of_range", "PASET %d..%d (limit %d)" % (self.sp, self.ep, lim))
        elif c == MADCTL:
            self.madctl = p[0]
        elif c == COLMOD:
            self.colmod = p[0]
            self.colmod_set = True
        elif c == IDX:
            self.idx = p[0] & 0x0F if p[0] & 0x10 else 0

    def pixel_byte(self, b):
        if self.colmod & 0x07 != 5:
            if not self.fmt_diag:
                self.fmt_diag = True
                self.diag("pixel_format_unsupported", "COLMOD 0x%02X: only 16 bpp is modelled" % self.colmod)
            return 0
        if self.hi is None:
            self.hi = b
            return 0
        w = (self.hi << 8) | b
        self.hi = None
        c, r, m = self.c, self.r, self.madctl
        if m & 0x20:
            col, row = r, c
        else:
            col, row = c, r
        if m & 0x40:
            col = W - 1 - col
        if m & 0x80:
            row = H - 1 - row
        if 0 <= col < W and 0 <= row < H:
            self.ram[row * W + col] = w
        c += 1
        if c > self.ec:
            c = self.sc
            r += 1
            if r > self.ep:
                r = self.sp
        self.c, self.r = c, r
        return 0

    # --- reads -------------------------------------------------------------------------------
    def read_param(self, c, n):
        n += self.idx
        if c == RDID4:
            p = (0x00, 0x93, 0x41)
        elif c == RDDST:  # D[31:25], D[22:16], D[10:8], D[7:5] (8.2.4)
            p = ((0 if self.sleep else 0x80) | ((self.madctl & 0xFC) >> 1),
                 ((self.colmod & 7) << 4) | (0x08 if self.idle else 0) | (0x04 if self.partial else 0)
                 | (0 if self.sleep else 0x02) | (0x01 if self.normal else 0),
                 0x04 if self.display_on else 0x00,
                 0x00)
        elif c == RDDPM:
            p = ((0 if self.sleep else 0x80) | (0x40 if self.idle else 0) | (0x20 if self.partial else 0)
                 | (0 if self.sleep else 0x10) | (0x08 if self.normal else 0) | (0x04 if self.display_on else 0),)
        elif c == RDDMADCTL:
            p = (self.madctl & 0xFC,)
        elif c == RDDCOLMOD:
            p = (self.colmod if self.colmod_set else 0x06,)
        elif c == RDDIM:
            p = ((0x20 if self.inv else 0),)
        elif c == RDDSM:
            p = (0x00,)
        elif c == RDDSDR:
            p = (0xC0 if not self.sleep else 0x00,)  # register-loading and functionality OK after sleep-out
        else:
            p = ()
        return p[n] if n < len(p) else 0

    # --- outputs -----------------------------------------------------------------------------
    def flush(self):
        if self.fb_path:
            with open(self.fb_path, "wb") as f:
                f.write(self.ram.tobytes())
        if self.stream_path:
            with open(self.stream_path, "wb") as f:
                f.write(self.stream.tobytes())
        if self.stats_path:
            with open(self.stats_path, "w") as f:
                json.dump({"bytes": len(self.stream), "diags": self.diags, "ignored": self.ignored,
                           "cmds": {"%02X" % k: v for k, v in sorted(self.cmds.items())},
                           "sleep": self.sleep, "display_on": self.display_on, "madctl": self.madctl,
                           "colmod": self.colmod, "now_us": self.ctx.now_us}, f)


READS = {RDDST, RDDPM, RDDMADCTL, RDDCOLMOD, RDDIM, RDDSM, RDDSDR, RDID4}
