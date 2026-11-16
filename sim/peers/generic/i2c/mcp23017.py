# Microchip MCP23017 16-bit I2C I/O expander as a scripted I2C peer.
# Wiring: attach with I2C.ScriptedI2cSlave @ <bus> <address> (the part answers 0x20 | A2:A0 on its pins, the
# board file says which). INTA and INTB are ctx.gpio lines 0 and 1 (declare numberOfGpios: 2 and wire them
# to MCU pads if the firmware uses them); active low, push-pull, unless IOCON.INTPOL / ODR say otherwise.
# Access: a write is [register pointer, data...]; a read returns bytes from the pointer. With IOCON.SEQOP = 0
# (power-on default) the pointer increments after every byte, A then B in BANK = 0 (wrapping 0x15 -> 0x00)
# and within the port in BANK = 1; with SEQOP = 1 it stays put (section 3.2.1).
# Source: Microchip MCP23017/MCP23S17 datasheet DS20001952C, Tables 3-4 and 3-5 and sections 3.5.1 to 3.5.12.
#
# Not modelled: the RESET pin, the slew-rate control (DISSLW), the MCP23S17's SPI front end and HAEN,
# the 100 kOhm pull-up's finite value (a pulled-up pin with nothing driving it reads 1, a driven pin reads
# its level), pin capacitance and the I2C timing limits (any clock rate is answered), the interrupt pin's
# open-drain high-Z state (ODR = 1 releases the pin to its inactive level), and the per-byte interrupt-clear
# timing (an interrupt clears when GPIO or INTCAP of that port is read, at the moment of the read).

# External drive on each pin. Edit these to drive the model from the bench. Per pin: True / False (driven),
# None (floating: reads 1 when GPPU enables the pull-up, else 0), or a callable(t_us) returning one of those.
PINS_A = [None] * 8
PINS_B = [None] * 8
POLL_US = 50                   # interrupt-on-change sampling period while any GPINTEN bit is set

REGS = ("IODIR", "IPOL", "GPINTEN", "DEFVAL", "INTCON", "IOCON", "GPPU", "INTF", "INTCAP", "GPIO", "OLAT")   # Table 3-5 order
IOCON_BANK, IOCON_MIRROR, IOCON_SEQOP, IOCON_ODR, IOCON_INTPOL = 0x80, 0x40, 0x20, 0x04, 0x02              # section 3.5.6
READ_ONLY = ("INTF", "INTCAP")
POR = {"IODIR": 0xFF}          # Tables 3-4 and 3-5: everything else resets to 0


def _pin(v, t_us):
    return v(t_us) if callable(v) else v


class Slave:
    def __init__(self, ctx):
        self.ctx = ctx
        self.r = [{n: POR.get(n, 0x00) for n in REGS} for _ in range(2)]   # [port][name]
        self.ptr = 0
        self.last = [0, 0]             # previous pin values, for INTCON = 0 comparisons
        self.int_level = [None, None]
        self.polling = False
        self.last = [self._pins(p) for p in (0, 1)]
        self._update_int()

    # ---- addressing ---------------------------------------------------------------------------------------

    def _decode(self, addr):
        """(port, name) for a pointer value under the current IOCON.BANK, or None for an unmapped address."""
        if self.r[0]["IOCON"] & IOCON_BANK:
            port, i = addr >> 4, addr & 0x0F
            if port > 1 or i >= len(REGS):
                return None
            return port, REGS[i]
        if addr >= 2 * len(REGS):
            return None
        return addr & 1, REGS[addr >> 1]

    def _step(self):
        if self.r[0]["IOCON"] & IOCON_SEQOP:
            return
        if self.r[0]["IOCON"] & IOCON_BANK:
            self.ptr = (self.ptr + 1) & 0x1F
        else:
            self.ptr = (self.ptr + 1) % (2 * len(REGS))

    # ---- I2C callbacks ------------------------------------------------------------------------------------

    def on_write(self, data):
        if not data:
            return
        self.ptr = data[0]
        for b in data[1:]:
            self._write(self.ptr, b)
            self._step()

    def on_read(self, count):
        out = bytearray()
        for _ in range(count):
            out.append(self._read(self.ptr))
            self._step()
        return bytes(out)

    # ---- registers ----------------------------------------------------------------------------------------

    def _port_iocon(self, v):
        # IOCON is one register visible at both port addresses.
        self.r[0]["IOCON"] = self.r[1]["IOCON"] = v & 0xFE

    def _write(self, addr, v):
        d = self._decode(addr)
        if d is None:
            return
        port, name = d
        if name in READ_ONLY:
            return
        if name == "IOCON":
            self._port_iocon(v)
        elif name == "GPIO":
            self.r[port]["OLAT"] = v          # a GPIO write goes to OLAT (section 3.5.10)
        else:
            self.r[port][name] = v
        if name in ("IODIR", "IPOL", "GPINTEN", "DEFVAL", "INTCON", "GPPU", "IOCON", "GPIO", "OLAT"):
            self._scan()
        self._arm()

    def _read(self, addr):
        d = self._decode(addr)
        if d is None:
            return 0
        port, name = d
        self._scan()
        if name == "GPIO":
            v = self._gpio(port)
            self._clear_int(port)
            return v
        if name == "INTCAP":
            v = self.r[port]["INTCAP"]
            self._clear_int(port)
            return v
        return self.r[port][name]

    # ---- pins ---------------------------------------------------------------------------------------------

    def _pins(self, port):
        """Level on each pin: external drive, else our own output, else the pull-up."""
        regs = self.r[port]
        t = self.ctx.now_us
        ext = PINS_A if port == 0 else PINS_B
        v = 0
        for i in range(8):
            bit = 1 << i
            if not regs["IODIR"] & bit:                    # output: the latch drives the pin
                level = 1 if regs["OLAT"] & bit else 0
            else:
                x = _pin(ext[i], t)
                level = 1 if x else 0 if x is not None else (1 if regs["GPPU"] & bit else 0)
            v |= level << i
        return v

    def _gpio(self, port):
        return self._pins(port) ^ self.r[port]["IPOL"]

    # ---- interrupt on change (section 3.6) ------------------------------------------------------------------

    def _scan(self):
        for port in (0, 1):
            regs = self.r[port]
            cur = self._pins(port)
            en = regs["GPINTEN"] & regs["IODIR"]
            ref = (regs["DEFVAL"] & regs["INTCON"]) | (self.last[port] & ~regs["INTCON"] & 0xFF)
            diff = (cur ^ ref) & en
            if diff and not regs["INTF"]:
                regs["INTF"] = diff
                regs["INTCAP"] = cur
            elif diff:
                regs["INTF"] |= diff
            self.last[port] = cur
        self._update_int()

    def _clear_int(self, port):
        self.r[port]["INTF"] = 0
        self._update_int()

    def _update_int(self):
        iocon = self.r[0]["IOCON"]
        act = [bool(self.r[p]["INTF"]) for p in (0, 1)]
        if iocon & IOCON_MIRROR:
            act = [act[0] or act[1]] * 2
        for p in (0, 1):
            level = act[p] == bool(iocon & IOCON_INTPOL)
            if self.int_level[p] != level:
                self.int_level[p] = level
                self.ctx.gpio(p).set(level)

    def _arm(self):
        want = bool(self.r[0]["GPINTEN"] | self.r[1]["GPINTEN"])
        if want and not self.polling:
            self.polling = True
            self.ctx.schedule_periodic(POLL_US)
        elif not want and self.polling:
            self.polling = False
            self.ctx.cancel_timer()

    def on_timer(self):
        self._scan()
