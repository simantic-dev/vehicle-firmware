# UART absolute rotary encoder (steering / joint angle) as a scripted UART peer for `UART.ScriptedUartPeer`.
# Load it from a fixture-local peer.py that execs this file and overrides CONFIG (see
# tests/stm/nucleo-f411re/uart-abs-encoder/peer.py), or point the peer's `file:` at it for the defaults.
#
# Protocol source: RLS Orbis datasheet BRD01_16, "Asynchronous serial communication interface over RS422
# (UART)" (https://cdn.rls.si/documents/datasheets/BRD01.pdf). The BR10 datasheet itself was not retrievable;
# BR10 is the same Orbis family and this section is the family UART interface, so the defaults below follow
# BRD01_16. Re-check against the BR10 datasheet before treating a byte-level detail as BR10-exact.
#   - 8N1, LSB first; baud 115.2 / 128 / 230.4 / 256 / 500 / 1000 kbps by part-number variant A..F. The baud is
#     the peer entry's `baudRate:` in the board file, not CONFIG.
#   - Command "1" (0x31): reply = echo of "1", then position. Command "3" (0x33): position only. Command
#     "d" (0x64): echo "d", position, one detailed-status byte. Any other command byte: ignored here
#     (hardware answers position, status only; set COMMANDS to model that).
#   - Position: 14-bit natural binary, left aligned, MSB first, followed by two general-status bits, active low:
#     b1 = Error (low: position invalid), b0 = Warning. With a multiturn part number a 16-bit turn counter
#     precedes the position (b31:b16). 14 + 2 bits = two bytes, high byte first.
#   - The datasheet gives no CRC on the UART interface (the SPI variant appends an inverted CRC-8 0x97, BiSS
#     an inverted CRC-6 0x43). CRC is therefore off by default and available as a generic option for
#     AksIM-style or custom framing.
#   - "Automatic transmission of selected data packet at programmable frame rate" (datasheet, Encoder
#     programming) is the MODE = "stream" case.
#
# Generic framing beyond the datasheet (all in CONFIG): MODE "request" | "stream", RESOLUTION_BITS,
# MULTITURN_BITS, STATUS_BITS, HEADER bytes, CRC (poly, width, init, xorout, invert), stream period.
#
# Angle profile (CONFIG["PROFILE"], degrees against virtual seconds):
#   {"type": "constant", "deg": 90}
#   {"type": "ramp", "start_deg": 0, "rate_dps": 90}
#   {"type": "sine", "center_deg": 180, "amp_deg": 45, "freq_hz": 1, "phase_deg": 0}
#   {"type": "points", "points": [[0, 0], [0.1, 45], [0.3, 45]]}   # linear between, held after the last
# Position is the angle modulo 360 quantised to RESOLUTION_BITS (floor); the multiturn counter is
# floor(angle / 360) modulo 2**MULTITURN_BITS.
#
# Time: UART peers get no clock in ctx, so the peer counts virtual time itself from a periodic timer
# (the stream period, or TICK_US in request mode). A request sees the angle as of the last tick, so the angle
# resolution in time is TICK_US. If ctx has now_us it is used instead.
#
# Not modelled: encoder start-up time, the hardware's internal latency between request and reply, noise and
# INL, commands other than 1/3/d (add them to COMMANDS), RS422 electrical layer, programming commands.
import math

CONFIG = {
    "MODE": "request",
    "REQUEST_BYTE": None,        # None: respond to every byte in COMMANDS. Else only to this byte.
    "COMMANDS": {                # byte -> (echo the command byte, append the detailed-status byte)
        0x31: (True, False),
        0x33: (False, False),
        0x64: (True, True),
    },
    "RESOLUTION_BITS": 14,
    "MULTITURN_BITS": 0,         # 16 for a multiturn part number, 0 for single turn
    "STATUS_BITS": 2,            # b1 Error, b0 Warning (active low); extra low bits are all ones
    "ERROR": False,
    "WARNING": False,
    "DETAILED_STATUS": 0x00,
    "HEADER": [],                # bytes sent before each stream frame (not before a request reply)
    "CRC": None,                 # e.g. {"poly": 0x97, "width": 8, "init": 0, "xorout": 0, "invert": True}
    "STREAM_PERIOD_US": 1000,
    "TICK_US": 1000,
    "PROFILE": {"type": "constant", "deg": 0.0},
}


def angle_at(profile, t_s):
    kind = profile["type"]
    if kind == "constant":
        return float(profile["deg"])
    if kind == "ramp":
        return profile.get("start_deg", 0.0) + profile["rate_dps"] * t_s
    if kind == "sine":
        ph = math.radians(profile.get("phase_deg", 0.0))
        return profile["center_deg"] + profile["amp_deg"] * math.sin(2 * math.pi * profile["freq_hz"] * t_s + ph)
    if kind == "points":
        pts = sorted(profile["points"])
        if t_s <= pts[0][0]:
            return float(pts[0][1])
        for (t0, a0), (t1, a1) in zip(pts, pts[1:]):
            if t_s <= t1:
                return a0 + (a1 - a0) * (t_s - t0) / (t1 - t0)
        return float(pts[-1][1])
    raise ValueError("unknown profile type %r" % kind)


def crc(data, poly, width=8, init=0, xorout=0):
    """MSB-first CRC over `data`, as in the Orbis SPI/BiSS descriptions."""
    top, mask = 1 << (width - 1), (1 << width) - 1
    reg = init
    for byte in data:
        reg ^= byte << (width - 8) if width >= 8 else byte
        for _ in range(8):
            reg = ((reg << 1) ^ poly) & mask if reg & top else (reg << 1) & mask
    return (reg ^ xorout) & mask


def position_bytes(cfg, deg, status):
    """Multiturn counter, position and status bits packed left aligned, MSB first."""
    rbits, mbits, sbits = cfg["RESOLUTION_BITS"], cfg["MULTITURN_BITS"], cfg["STATUS_BITS"]
    turns, rem = divmod(deg, 360.0)
    code = min(int(rem / 360.0 * (1 << rbits)), (1 << rbits) - 1)
    word = ((int(turns) & ((1 << mbits) - 1)) << rbits | code) if mbits else code
    word = word << sbits | status
    total = mbits + rbits + sbits
    nbytes = (total + 7) // 8
    return (word << (8 * nbytes - total)).to_bytes(nbytes, "big")


class Peer:
    def __init__(self, ctx):
        self.ctx = ctx
        self.cfg = dict(CONFIG)
        self.t_us = 0
        mode = self.cfg["MODE"]
        if mode == "stream":
            self.tick_us = self.cfg["STREAM_PERIOD_US"]
        elif mode == "request":
            self.tick_us = self.cfg["TICK_US"]
        else:
            raise ValueError("MODE must be 'request' or 'stream'")
        if not hasattr(ctx, "now_us"):
            ctx.schedule_periodic(self.tick_us)

    def now_us(self):
        n = getattr(self.ctx, "now_us", None)
        return self.t_us if n is None else n

    def angle_deg(self):
        return angle_at(self.cfg["PROFILE"], self.now_us() / 1e6)

    def status_bits(self):
        n = self.cfg["STATUS_BITS"]
        s = (1 << n) - 1
        if n >= 1 and self.cfg["WARNING"]:
            s &= ~1
        if n >= 2 and self.cfg["ERROR"]:
            s &= ~2
        return s

    def frame(self, header=b"", detail=False):
        out = bytes(header) + position_bytes(self.cfg, self.angle_deg(), self.status_bits())
        if detail:
            out += bytes([self.cfg["DETAILED_STATUS"] & 0xFF])
        spec = self.cfg["CRC"]
        if spec:
            w = spec.get("width", 8)
            c = crc(out, spec["poly"], w, spec.get("init", 0), spec.get("xorout", 0))
            if spec.get("invert"):
                c ^= (1 << w) - 1
            out += c.to_bytes((w + 7) // 8, "big")
        return out

    def on_byte(self, b):
        if self.cfg["MODE"] != "request":
            return
        only = self.cfg["REQUEST_BYTE"]
        if only is not None and b != only:
            return
        cmd = self.cfg["COMMANDS"].get(b)
        if cmd is None:
            if only is None:
                return
            cmd = (False, False)
        echo, detail = cmd
        self.ctx.send(self.frame(bytes([b]) if echo else b"", detail))

    def on_timer(self):
        self.t_us += self.tick_us
        if self.cfg["MODE"] == "stream":
            self.ctx.send(self.frame(self.cfg["HEADER"]))
