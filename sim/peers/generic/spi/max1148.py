# Maxim MAX1148 (8 channel, 5 V, internal 4.096 V reference) / MAX1146 (4 channel); the MAX1149 / MAX1147 are the
# 3 V, 2.5 V reference twins. 14-bit SAR ADC as a scripted SPI peer.
# Wiring: chip select is GPIO line 0 of this peer, active low (numberOfGpios: 1, or put the peer behind an
# SPI.SPIMultiplexer slot). SPI mode 0, MSB first, external clock mode.
# Framing (Table 1, Figure 8): the first logic 1 on DIN after CS falls is the START bit; the control byte is
#   START | SEL2 SEL1 SEL0 | SGL/DIF | UNI/BIP | PD1 PD0      (bit 3 = SGL/DIF, bit 2 = UNI/BIP)
# In external clock mode (PD1:PD0 = 11) SSTRB pulses for two clocks after the control byte and the 14 result bits
# follow MSB first, one per SCLK falling edge (p. 15, Figure 8); in a 3 byte frame byte 1 bits 5:0 are D13..D8 and
# byte 2 is D7..D0, which is how a 3 byte DMA driver decodes it.
# Output: straight binary in unipolar mode, two's complement in bipolar mode (p. 16). Zero scale is the COM voltage
# (unipolar single-ended: COM at AGND), full scale VREF above it; bipolar spans COM +- VREF/2 (Table 7).
# Channel select: Table 2 (single-ended, MAX1148), Table 3 (differential), Tables 4 and 5 (MAX1146).
# Source: Maxim MAX1146-MAX1149 datasheet, 19-1480 Rev 0 (Wayback copy of datasheets.maximintegrated.com/en/ds/
# MAX1146-MAX1149.pdf); pages are the printed page numbers.
#
# Not modelled: internal clock modes and SSTRB, power-down modes PD1:PD0 (every control byte converts), the
# reference's startup time and REFADJ, INL/DNL/offset/gain error and noise (the code is the ideal quantisation),
# the 140 us conversion limit in external clock mode, and clocks beyond the first 24 per CS window (zeros).
# Differential mode with COM_V does not shift: the pair difference is converted as is (Table 7, differential row).

VREF_V = 4.096                 # MAX1146/MAX1148 internal reference (p. 1); 2.5 for the MAX1147/MAX1149
CHANNEL_V = [0.0] * 8          # CH0..CH7 volts, float or callable(t_us) -> volts
NUM_CHANNELS = 8               # 8 = MAX1148/1149, 4 = MAX1146/1147
COM_V = 0.0                    # voltage on COM: single-ended results are relative to it (AGND, or VREF/2 for bipolar)

RESOLUTION_BITS = 14
# Single-ended SEL2:0 -> channel: Table 2 for the MAX1148 (CH0, CH2, CH4, CH6, CH1, CH3, CH5, CH7), Table 4 for the
# MAX1146 (SEL2:0 = 000 CH0, 100 CH1, 001 CH2, 101 CH3; SEL1 ignored).
SEL_TO_CH = (0, 2, 4, 6, 1, 3, 5, 7)
SEL_TO_CH_4 = (0, 2, 0, 2, 1, 3, 1, 3)

SGL = 0x08                     # Table 1 bit 3
UNI = 0x04                     # Table 1 bit 2


def _volts(i, t):
    v = CHANNEL_V[i] if i < len(CHANNEL_V) else 0.0
    return v(t) if callable(v) else float(v)


def code_for(ctrl, t_us=0):
    sel = (ctrl >> 4) & 7
    unipolar, single = bool(ctrl & UNI), bool(ctrl & SGL)
    n = NUM_CHANNELS
    if single:
        v = _volts((SEL_TO_CH if n == 8 else SEL_TO_CH_4)[sel] % n, t_us) - COM_V
    else:
        pair = ((sel & 3) if n == 8 else (sel & 1)) * 2        # SEL1:0 pick the pair (Table 3; Table 5 uses SEL0), SEL2 flips the polarity
        a, b = (pair, pair + 1) if not sel & 4 else (pair + 1, pair)
        v = _volts(a % n, t_us) - _volts(b % n, t_us)
    full = 1 << RESOLUTION_BITS
    if unipolar:
        code = int(v / VREF_V * full)
        return max(0, min(full - 1, code))
    # Bipolar: two's complement, +-VREF/2 around COM / the pair midpoint (Table 7).
    code = int(v / (VREF_V / 2) * (full // 2))
    return max(-(full // 2), min(full // 2 - 1, code)) & (full - 1)


class Slave:
    def __init__(self, ctx):
        self.ctx = ctx
        self._reset()

    def _reset(self):
        self.clk = 0
        self.start = None
        self.ctrl = 0
        self.bits = []

    def on_select(self):
        self._reset()

    def on_deselect(self):
        self._reset()

    on_finish = on_deselect

    def on_transmit(self, b):
        out = 0
        for i in range(8):
            out = (out << 1) | self._clock((b >> (7 - i)) & 1)
        return out

    def _clock(self, din):
        self.clk += 1
        if self.start is None:
            if din:
                self.start = self.clk
                self.ctrl = 0x80
            return 0
        k = self.clk - self.start               # 1..7: rest of the control byte
        if k <= 7:
            self.ctrl |= din << (7 - k)
            if k == 7:
                code = code_for(self.ctrl, self.ctx.now_us)
                self.bits = [0, 0] + [(code >> (RESOLUTION_BITS - 1 - i)) & 1 for i in range(RESOLUTION_BITS)]
            return 0
        j = k - 8
        return self.bits[j] if j < len(self.bits) else 0
