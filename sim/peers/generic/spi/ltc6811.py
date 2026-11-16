# Analog Devices LTC6811-1 12-cell battery monitor, daisy chain behind an LTC6820 SPI-to-isoSPI bridge,
# as a scripted SPI peer. One peer is one chain: every IC behind one chip select of the host.
# Wiring: chip select is GPIO line 0 of this peer, active low (declare numberOfGpios: 1 and wire the host
# CS pad to it, or put the peer behind an SPI.SPIMultiplexer slot, which does the same). SPI mode 3.
# Chain length is NUM_ICS; IC 0 is the one next to the bridge. Set NUM_ICS and the stimulus before the
# peer is instantiated (a fixture's wrapper script execs this file, then overrides the constants).
#
# Source: Analog Devices LTC6811-1/LTC6811-2 datasheet, document 68111fb (the Rev B file; docs/datasheets copy
# not committed). Citations are "p." physical page of that PDF, table numbers as printed.
#
# Framing (pp. 50-51 "Network Layer", "Data Link Layer"; broadcast addressing of the -1):
#   command: CMD0, CMD1, PEC0, PEC1 (11-bit command code, PEC15 over the two bytes, p. 50). A command with a bad
#     PEC is ignored by every IC.
#   read commands: after the command the host clocks 8 bytes per IC; IC 0 answers first. Each IC sends its
#     6-byte register group followed by the PEC15 of those 6 bytes.
#   write commands (WRCFG, WRSCTRL, WRPWM, WRCOMM): the host sends 8 bytes per IC, the data for the IC farthest
#     from the bridge first. Each 8 bytes are 6 data bytes and their PEC. A register is updated only from a
#     packet whose PEC is correct; the data is latched on the rising edge of CSB (p. 51), so the peer applies it at
#     CS rise, and only when the host clocked exactly 8 bytes per IC.
#   other commands (ADCV, ADAX, ADSTAT, ADCVAX, ADCVSC, CLR*, PLADC, DIAGN, STSCTRL, STCOMM) are 4 bytes and run
#     when CS rises. PLADC then reads back 0x00 bytes while a conversion runs and 0xFF once all are done.
# Command codes: Table 38 (p. 56-57). Register groups: Tables 40-51 (pp. 59-61). Bit meanings: Table 52 (p. 62-63).
# Power-up: cell and GPIO registers are 0xFFFF until the first conversion and after CLRCELL/CLRAUX (Table 52);
# CFGR0 defaults to GPIO5..1 = 1 and REFON = ADCOPT = 0 (Table 52), VUV = VOV = 0, DCC = 0.
# Wake-up (Figure 1, Figure 26, pp. 49-52): the isoSPI ports go IDLE after tIDLE without traffic. A wake pulse wakes
# IC 0 within tREADY (core in STANDBY) or tWAKE (core in SLEEP); a woken LTC6811-1 sends a pulse on its port B that
# wakes the next IC (Method 1), and each further CS pulse also wakes the next IC if the previous one is ready
# (Method 2, what a dummy RDCFGA per IC does). A command runs only when every IC in the chain is READY at its
# first byte; otherwise the chain stays silent (the real MISO level in that case is not modelled: 0x00).
# The cores fall back to SLEEP after tSLEEP without a valid command (watchdog).
# Conversions (Tables 5-10, Table 39): results appear in the registers when the conversion time since CS rose has
# elapsed, plus tREFUP first when the core is in STANDBY (REFON = 0); a read before then returns the previous
# contents. With REFON = 0 the core drops back to STANDBY after the conversion (Figure 1), so every conversion pays
# tREFUP; REFON = 1 keeps the reference up until the watchdog expires.
# Cell codes are round(volts / 100 uV), 16 bit, AUX likewise (Table 52).
#
# Not modelled: LTC6811-2 address mode, the second isoSPI port, the open-wire / self-test / overlap / redundancy
# conversions (ADOW, CVST, AXST, STATST, ADOL, ADAXD, ADSTATD: ignored), DIAGN is accepted and clears MUXFAIL
# after its time but tests nothing, cell discharge effects (DCC bits, the discharge timer and DTEN: stored, DCTO never
# expires), the PWM discharge duty, ADC noise, accuracy (Table 4) and filter settling, GPIO pull-down control
# beyond the read-back rule below, the WRCOMM/STCOMM I2C/SPI master (COMM registers store), thermal shutdown (THSD
# is only set by CLRSTAT), supply droop, and REV (reads 0; the datasheet says to ask the factory).
import struct

NUM_ICS = 6                       # ICs in this chain
CELLS_PER_IC = None               # None: every IC has 12 cells; or a list of 12/9/... per IC (unused inputs read 0 V)
CELL_V = None                     # None: 3.7 V. Else a list per IC of 12 volts; an entry may be callable(t_us) -> volts
GPIO_V = None                     # None: GPIO1..4 at 1.5 V, GPIO5 at 0.9 V. Else a list per IC of 5 volts (or callable(t_us))
VREF2_V = 3.0                     # REF in AUXB: 2.99 to 3.01 V (Table 52)
VA_V, VD_V = 5.0, 3.0             # VA 4.5 to 5.5 V and VD 2.7 to 3.6 V normal range (Table 52); typical VREGD is 3 V (p. 7)
DIE_TEMP_C = 25.0                 # ITMP, same for every IC
DTEN_PIN = False                  # level of the DTEN pin, read back as CFGR0.DTEN (read only, Table 52)
CORRUPT = None                    # None, or fn(ic, command) -> True flips one bit of that IC's data PEC in a read

LSB_V = 100e-6                    # Table 52: 100 uV per LSB
ITMP_V_PER_C, ITMP_OFFSET_C = 7.5e-3, 273.0   # T = ITMP * 100 uV / 7.5 mV/C - 273 C (Table 52)
GPIO_VIH_V, GPIO_VIL_V = 2.7, 1.2             # GPIO logic thresholds (p. 6, VIH(CFG), VIL(CFG))

# Timing, microseconds.
T_IDLE_US = 5500.0                # tIDLE 4.3 / 5.5 / 6.7 ms (p. 6) and "greater than tIDLE = 5.5 ms" (p. 49)
T_SLEEP_US = 2.0e6                # tSLEEP 1.8 / 2 / 2.2 s (p. 7)
T_WAKE_US = 400.0                 # tWAKE 200 .. 400 us, taken at the maximum (p. 7)
T_READY_US = 10.0                 # tREADY < 10 us (p. 6)
T_REFUP_US = 3500.0               # tREFUP 2.7 / 3.5 / 4.4 ms (p. 7)
T_DIAGN_REFUP_US, T_DIAGN_STANDBY_US = 400.0, 4500.0   # DIAGN duration, core in REFUP / STANDBY (p. 35)

# Conversion times by ADC mode, microseconds; modes in this order: 27 kHz, 14 kHz, 7 kHz, 3 kHz, 2 kHz, 1 kHz, 422 Hz, 26 Hz.
_MODE = {0: (6, 5), 1: (0, 1), 2: (2, 3), 3: (7, 4)}      # MD -> mode index for ADCOPT = 0, 1 (Table 39)
CONV_ADCV_ALL = (1113, 1288, 2335, 3033, 4430, 7222, 12807, 201317)   # Table 5, t6C
CONV_PAIR = (201, 230, 405, 501, 754, 1219, 2150, 33568)              # Table 6, t1C (2 cells, one GPIO, one status item)
CONV_ADCVAX = (1503, 1736, 3133, 4064, 5925, 9648, 17096, 268442)     # Table 9, t8C
CONV_ADCVSC = (1322, 1526, 2748, 3562, 5192, 8450, 14966, 234893)     # Table 10, t7C
CONV_ADSTAT_ALL = (748, 865, 1600, 2000, 3000, 4800, 8500, 134000)    # Table 39, CHST = 000

# Command codes, 11 bits (Table 38).
WRCFG, RDCFG = 0x001, 0x002
RDCVA, RDCVB, RDCVC, RDCVD = 0x004, 0x006, 0x008, 0x00A
RDAUXA, RDAUXB, RDSTATA, RDSTATB = 0x00C, 0x00E, 0x010, 0x012
WRSCTRL, WRPWM, STSCTRL, CLRSCTRL, RDSCTRL, RDPWM = 0x014, 0x020, 0x019, 0x018, 0x016, 0x022
ADCV, ADAX, ADSTAT, ADCVAX, ADCVSC = 0x260, 0x460, 0x468, 0x46F, 0x467
CLRCELL, CLRAUX, CLRSTAT, PLADC, DIAGN = 0x711, 0x712, 0x713, 0x714, 0x715
WRCOMM, RDCOMM, STCOMM = 0x721, 0x722, 0x723

PEC_SEED, PEC_POLY = 0x10, 0x4599   # p. 50: initial 000000000010000, x^15 + x^14 + x^10 + x^8 + x^7 + x^4 + x^3 + 1


def pec15(data):
    """CRC-15 over `data`, seed 0x10, result shifted left once (LSB 0), returned MSB byte first."""
    rem = PEC_SEED
    for byte in data:
        for bit in range(7, -1, -1):
            top = ((rem >> 14) & 1) ^ ((byte >> bit) & 1)
            rem = (rem << 1) & 0x7FFF
            if top:
                rem ^= PEC_POLY
    return bytes(((rem << 1) >> 8 & 0xFF, (rem << 1) & 0xFF))


def ntc_v(celsius, beta=3984.0, r25=10000.0, r_fixed=2740.0, v_top=5.0):
    """Volts on a GPIO fed by NTC (to v_top) over r_fixed to ground. Defaults are a common 10k NTC divider
    (beta 3984, 2.74k to ground, 5 V); set them to match the board's thermistor circuit."""
    r = r25 * pow(2.718281828459045, beta * (1.0 / (celsius + 273.15) - 1.0 / 298.15))
    return v_top * r_fixed / (r + r_fixed)


def mcp9701_v(celsius):
    """MCP9701 board temperature sensor: 400 mV at 0 C, 19.5 mV/C."""
    return 0.4 + 0.0195 * celsius


def _eval(v, t_us):
    return v(t_us) if callable(v) else float(v)


def _code(volts):
    return max(0, min(0xFFFF, int(round(volts / LSB_V))))


def _mode(md, adcopt):
    return _MODE[md][1 if adcopt else 0]


class _Ic:
    def __init__(self):
        self.cfg = bytearray([0xF8, 0, 0, 0, 0, 0])
        self.cv = [bytearray([0xFF] * 6) for _ in range(4)]
        self.aux = [bytearray([0xFF] * 6) for _ in range(2)]
        self.stat = [bytearray([0xFF] * 6) for _ in range(2)]
        self.sctrl, self.pwm, self.comm = bytearray(6), bytearray(6), bytearray(6)
        self.flags = [0xFF, 0xFF, 0xFF]       # STBR2..4: UV/OV pairs of cells 1..4, 5..8, 9..12; set at power-up
        self.muxfail = 1                      # set at power-up and by CLRSTAT, cleared by DIAGN (p. 35)
        self.thsd = 0
        self.ready_at = None                  # None: isoSPI port IDLE; else the time the port is READY
        self.core_us = -1e18                  # last wake-up or valid command: the core sleeps tSLEEP after it
        self._sync_stat_b()

    def _sync_stat_b(self):
        self.stat[1][2:5] = bytes(self.flags)
        self.stat[1][5] = (self.muxfail << 1) | self.thsd

    @property
    def dcc(self):
        """Discharge-enable mask, bit n = cell n+1."""
        return self.cfg[4] | (self.cfg[5] & 0x0F) << 8


class Slave:
    def __init__(self, ctx):
        self.ctx = ctx
        self.ics = [_Ic() for _ in range(NUM_ICS)]
        self.last_traffic_us = -1e18   # chain starts asleep
        self.pending = []              # (done_us, kind, arg), in start order
        self.busy_until_us = 0.0
        self.diagn_done_us = None
        self.stats = {"cmd_pec_errors": 0, "data_pec_errors": 0, "not_ready": 0, "commands": 0, "wakes": 0}
        self._reset_txn()

    # ---- host-visible callbacks -------------------------------------------------------------------

    def _reset_txn(self):
        self.beat = 0
        self.cmd = bytearray()
        self.code = None
        self.valid = False
        self.ready = False
        self.resp = b""
        self.wbuf = bytearray()
        self.txn_active = False

    def _wake(self, now):
        """One CS falling edge (a wake pulse, Figure 26) at `now`; returns True when every IC is READY."""
        self.stats["wakes"] += 1
        if now - self.last_traffic_us > T_IDLE_US:
            for ic in self.ics:
                ic.ready_at = None

        def wake_ic(ic, at):
            # tWAKE when this IC's core slept, tREADY when it was in STANDBY (p. 49); either way it is in STANDBY after.
            up = T_WAKE_US if at - ic.core_us > T_SLEEP_US else T_READY_US
            ic.ready_at = at + up
            ic.core_us = at

        prev = None
        for ic in self.ics:
            if ic.ready_at is None and (prev is None or prev <= now):
                wake_ic(ic, now)                          # woken by this pulse
            if ic.ready_at is None:
                break
            prev = ic.ready_at
        # Method 1: a READY IC pulses its port B and the next one wakes as soon as that arrives.
        for i in range(1, len(self.ics)):
            a, b = self.ics[i - 1], self.ics[i]
            if b.ready_at is None and a.ready_at is not None:
                wake_ic(b, a.ready_at)
        return all(ic.ready_at is not None and ic.ready_at <= now for ic in self.ics)

    def on_select(self):
        now = self.ctx.now_us
        self._reset_txn()
        self.txn_active = True
        self.ready = self._wake(now)
        self.last_traffic_us = now

    def on_transmit(self, b):
        if not self.txn_active:
            self.on_select()
        i = self.beat
        self.beat += 1
        self.last_traffic_us = self.ctx.now_us
        if i < 4:
            self.cmd.append(b)
            if i == 3:
                self._command_received()
            return 0
        if self.code is not None and self.valid and self.ready:
            if self.resp:
                j = i - 4
                return self.resp[j] if j < len(self.resp) else 0
            if self.code in (WRCFG, WRSCTRL, WRPWM, WRCOMM):
                self.wbuf.append(b)
            elif self.code == PLADC:
                return 0xFF if self._all_done(self.ctx.now_us) else 0x00
        return 0

    def on_deselect(self):
        if not self.txn_active:
            return
        now = self.ctx.now_us
        if self.code is not None and self.valid and self.ready:
            self._finish_command(now)
        self.last_traffic_us = now
        self._reset_txn()

    on_finish = on_deselect

    # ---- command handling ---------------------------------------------------------------------------

    def _command_received(self):
        if pec15(self.cmd[:2]) != bytes(self.cmd[2:4]):
            self.stats["cmd_pec_errors"] += 1
            return
        self.valid = True
        self.code = (self.cmd[0] & 0x07) << 8 | self.cmd[1]
        now = self.ctx.now_us
        if not self.ready:
            self.stats["not_ready"] += 1
            return
        for ic in self.ics:
            ic.core_us = now                                  # a valid command restarts the watchdog
        self._settle(now)
        self.stats["commands"] += 1
        self.resp = self._read_response(self.code)

    def _group(self, code):
        return {RDCFG: ("cfg", None), RDCVA: ("cv", 0), RDCVB: ("cv", 1), RDCVC: ("cv", 2), RDCVD: ("cv", 3),
                RDAUXA: ("aux", 0), RDAUXB: ("aux", 1), RDSTATA: ("stat", 0), RDSTATB: ("stat", 1),
                RDSCTRL: ("sctrl", None), RDPWM: ("pwm", None), RDCOMM: ("comm", None)}.get(code)

    def _read_response(self, code):
        g = self._group(code)
        if g is None:
            return b""
        name, idx = g
        out = bytearray()
        for n, ic in enumerate(self.ics):
            if name == "cfg":
                data = self._cfg_readback(n, ic)
            else:
                reg = getattr(ic, name)
                data = bytes(reg if idx is None else reg[idx])
            pec = bytearray(pec15(data))
            if CORRUPT is not None and CORRUPT(n, code):
                pec[1] ^= 0x01
            out += data + pec
            if code == RDSTATB:
                ic.thsd = 0                                # cleared by a read of group B (Table 52)
                ic._sync_stat_b()
        return bytes(out)

    def _cfg_readback(self, n, ic):
        c = bytearray(ic.cfg)
        now = self.ctx.now_us
        for g in range(5):
            if c[0] >> (3 + g) & 1:                          # pull-down off: the pin reads its logic level
                v = self._gpio_v(n, g, now)
                if v >= GPIO_VIH_V:
                    c[0] |= 1 << (3 + g)
                elif v <= GPIO_VIL_V:
                    c[0] &= ~(1 << (3 + g))
            else:
                c[0] &= ~(1 << (3 + g))                      # pull-down on: pin at logic 0
        c[0] = (c[0] & ~0x02) | (0x02 if DTEN_PIN else 0)    # DTEN is read only (Table 52)
        return bytes(c)

    def _finish_command(self, now):
        code = self.code
        if code in (WRCFG, WRSCTRL, WRPWM, WRCOMM):
            self._apply_write(code)
            return
        self._settle(now)
        base3 = code & ~0x187
        base4 = code & ~0x190
        md = (code >> 7) & 3
        adcopt = bool(self.ics[0].cfg[0] & 1)
        mode = _mode(md, adcopt)
        if base4 in (ADCVAX, ADCVSC):
            if base4 == ADCVAX:
                self._start(now, "cv_gpio", 0, CONV_ADCVAX[mode])
            else:
                self._start(now, "cv_sc", 0, CONV_ADCVSC[mode])
        elif base3 == ADCV:
            ch = code & 7
            self._start(now, "cv", ch, CONV_ADCV_ALL[mode] if ch == 0 else CONV_PAIR[mode])
        elif base3 == ADAX:
            ch = code & 7
            if ch <= 6:
                self._start(now, "aux", ch, CONV_ADCV_ALL[mode] if ch == 0 else CONV_PAIR[mode])
        elif base3 == ADSTAT:
            ch = code & 7
            if ch <= 4:
                self._start(now, "stat", ch, CONV_ADSTAT_ALL[mode] if ch == 0 else CONV_PAIR[mode])
        elif code == CLRCELL:
            for ic in self.ics:
                for g in ic.cv:
                    g[:] = b"\xFF" * 6
        elif code == CLRAUX:
            for ic in self.ics:
                for g in ic.aux:
                    g[:] = b"\xFF" * 6
        elif code == CLRSTAT:
            for ic in self.ics:                              # p. 33
                ic.stat[0][:] = b"\xFF" * 6
                ic.stat[1][0:2] = b"\xFF\xFF"
                ic.flags = [0xFF, 0xFF, 0xFF]
                ic.muxfail, ic.thsd = 1, 1
                ic._sync_stat_b()
        elif code == DIAGN:
            core_up = now < self.busy_until_us or bool(self.ics[0].cfg[0] & 4)
            self.diagn_done_us = now + (T_DIAGN_REFUP_US if core_up else T_DIAGN_STANDBY_US)
            self.busy_until_us = max(self.busy_until_us, self.diagn_done_us)
            self.pending.append((self.diagn_done_us, "diagn", 0))
        elif code == CLRSCTRL:
            for ic in self.ics:
                ic.sctrl[:] = bytes(6)
        # STSCTRL, STCOMM: accepted, no effect (not modelled).

    def _apply_write(self, code):
        reg = {WRCFG: "cfg", WRSCTRL: "sctrl", WRPWM: "pwm", WRCOMM: "comm"}[code]
        m = NUM_ICS
        if len(self.wbuf) != 8 * m:
            return
        for k in range(m):
            pkt = bytes(self.wbuf[8 * k:8 * k + 8])
            if pec15(pkt[:6]) != pkt[6:8]:
                self.stats["data_pec_errors"] += 1
                continue
            getattr(self.ics[m - 1 - k], reg)[:] = pkt[:6]

    # ---- conversions ---------------------------------------------------------------------------------

    def _start(self, now, kind, ch, conv_us):
        refon = bool(self.ics[0].cfg[0] & 4)
        in_progress = now < self.busy_until_us
        start = now
        if not refon and not in_progress:
            start = now + T_REFUP_US           # STANDBY -> reference power-up (p. 49, Figure 1)
        done = max(start, self.busy_until_us) + conv_us
        self.busy_until_us = done
        self.pending.append((done, kind, ch))

    def _all_done(self, now):
        return now >= self.busy_until_us

    def _settle(self, now):
        keep = []
        for done, kind, ch in self.pending:
            if done <= now:
                self._apply(done, kind, ch)
            else:
                keep.append((done, kind, ch))
        self.pending = keep

    def _cell_v(self, n, c, t):
        cells = CELLS_PER_IC[n] if CELLS_PER_IC is not None else 12
        if c >= cells:
            return 0.0
        if CELL_V is None:
            return 3.7
        return _eval(CELL_V[n][c], t)

    def _gpio_v(self, n, g, t):
        if GPIO_V is None:
            return 0.9 if g == 4 else 1.5
        return _eval(GPIO_V[n][g], t)

    def _apply(self, t, kind, ch):
        for n, ic in enumerate(self.ics):
            if kind == "diagn":
                ic.muxfail = 0
                ic._sync_stat_b()
                continue
            if kind in ("cv", "cv_gpio", "cv_sc"):
                # CH = 0: all 12 cells; 1..6: cells (ch, ch + 6) only (Table 39).
                cells = range(12) if ch == 0 else (ch - 1, ch + 5)
                for c in cells:
                    code = _code(self._cell_v(n, c, t))
                    ic.cv[c // 3][2 * (c % 3):2 * (c % 3) + 2] = struct.pack("<H", code)
                self._update_flags(n, ic, t, cells)
                if kind == "cv_sc":
                    self._update_stat(n, ic, t, 1)
            if kind in ("aux", "cv_gpio"):
                chans = range(2) if kind == "cv_gpio" else range(5) if ch == 0 else [ch - 1] if ch <= 5 else []
                for g in chans:
                    code = _code(self._gpio_v(n, g, t))
                    ic.aux[g // 3][2 * (g % 3):2 * (g % 3) + 2] = struct.pack("<H", code)
                if kind == "aux" and ch in (0, 6):
                    ic.aux[1][4:6] = struct.pack("<H", _code(VREF2_V))
            if kind == "stat":
                self._update_stat(n, ic, t, ch)

    def _update_flags(self, n, ic, t, cells):
        vuv = ic.cfg[1] | (ic.cfg[2] & 0x0F) << 8
        vov = ic.cfg[2] >> 4 | ic.cfg[3] << 4
        uv_code, ov_code = (vuv + 1) * 16, vov * 16          # Table 52: (VUV + 1) * 16 * 100 uV, VOV * 16 * 100 uV
        for c in cells:
            code = _code(self._cell_v(n, c, t))
            f, shift = c // 4, 2 * (c % 4)                   # STBR2..4: CxOV above CxUV, cell 1 in the low bits (Table 48)
            bits = (1 if code < uv_code else 0) | (2 if code > ov_code else 0)
            ic.flags[f] = (ic.flags[f] & ~(3 << shift)) | (bits << shift)
        ic._sync_stat_b()

    def _update_stat(self, n, ic, t, ch):
        """CHST: 0 = SC, ITMP, VA, VD; 1 = SC; 2 = ITMP; 3 = VA; 4 = VD."""
        if ch in (0, 1):
            total = sum(_code(self._cell_v(n, c, t)) for c in range(12))
            ic.stat[0][0:2] = struct.pack("<H", min(0xFFFF, total // 20))      # SC = sum * 100 uV * 20
        if ch in (0, 2):
            ic.stat[0][2:4] = struct.pack("<H", _code((DIE_TEMP_C + ITMP_OFFSET_C) * ITMP_V_PER_C))
        if ch in (0, 3):
            ic.stat[0][4:6] = struct.pack("<H", _code(VA_V))
        if ch in (0, 4):
            ic.stat[1][0:2] = struct.pack("<H", _code(VD_V))
