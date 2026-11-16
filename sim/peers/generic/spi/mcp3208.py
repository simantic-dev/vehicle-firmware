# Microchip MCP3208 (8 channel) / MCP3204 (4 channel) 12-bit SAR ADC as a scripted SPI peer.
# Wiring: chip select is GPIO line 0 of this peer, active low (declare numberOfGpios: 1 and wire the CS
# pad to it, or put the peer behind an SPI.SPIMultiplexer slot). SPI mode 0 or 3, MSB first.
# Framing (datasheet section 5.0 and Figure 5-1): the first clock with CS low and DIN high is the start bit.
# SGL/DIFF, D2, D1, D0 follow. One more clock completes the sample; the next falling edge outputs a low
# null bit, then 12 result bits MSB first. The peer works on the bit clock, so a 3-byte frame with the start
# bit anywhere (leading zeros allowed, section 6.1) gets the right answer. After the 12 result bits the
# part repeats the result LSB first (Figure 5-2), then zeros.
# Source: Microchip MCP3204/3208 datasheet DS21298E, section cited per constant.
#
# Not modelled: sample-and-hold droop, INL/DNL/offset/gain error and noise (the code is the ideal
# floor(V / VREF * 4096)), the 100 ksps / 2 MHz limits and tCSH (any clock rate is answered),
# DOUT tri-state while CS is high (MISO reads 0 when the peer is not driving), a second start bit
# in the same CS window (ignored), supply dependence of VREF.
# The LSB-first tail is taken from the datasheet text only; typical 3-byte-frame drivers never read it.

# Stimulus. Edit these to drive the model from the bench. An entry may be a float (volts) or a callable
# taking the virtual time in microseconds and returning volts.
VREF_V = 3.3                       # reference voltage on VREF, section 4.1 (range 2.7 to 5.5 V)
CHANNEL_V = [0.0] * 8              # CH0..CH7 volts; MCP3204 uses the first four
NUM_CHANNELS = 8                   # 8 = MCP3208, 4 = MCP3204 (Table 5-1: D2 is a don't-care)

RESOLUTION_BITS = 12               # section 1.0
NULL_BITS = 1                      # section 5.0: one low null bit before the MSB
SAMPLE_CLOCKS_AFTER_D0 = 1         # section 5.0: "one more clock is required to complete the sample"


def _volts(i, now_us):
    v = CHANNEL_V[i] if i < len(CHANNEL_V) else 0.0
    return v(now_us) if callable(v) else float(v)


def code_for(sgl, sel, now_us=0):
    """Table 5-2: SGL/DIFF=1 single-ended CHsel; =0 differential, pair sel>>1, polarity sel&1."""
    n = NUM_CHANNELS
    if sgl:
        v = _volts(sel % n, now_us)
    else:
        # D0=0: CH(2k) is IN+ and CH(2k+1) IN-; D0=1: the reverse.
        a, b = (sel & ~1), (sel & ~1) + 1
        if sel & 1:
            a, b = b, a
        v = _volts(a % n, now_us) - _volts(b % n, now_us)
    code = int(v / VREF_V * (1 << RESOLUTION_BITS))
    return max(0, min((1 << RESOLUTION_BITS) - 1, code))


class Slave:
    def __init__(self, ctx):
        self.ctx = ctx
        self._reset()

    def _reset(self):
        self.clk = 0               # clocks seen in this CS window
        self.start = None          # clock number of the start bit
        self.cfg = 0               # bits after the start: SGL, D2, D1, D0
        self.out_bits = []         # result stream from clock start+NULL position
        self.converted = False

    def on_select(self):
        self._reset()

    def on_deselect(self):
        self._reset()

    on_finish = on_deselect

    def on_transmit(self, b):
        out = 0
        for i in range(8):
            din = (b >> (7 - i)) & 1
            out = (out << 1) | self._clock(din)
        return out

    def _clock(self, din):
        self.clk += 1
        if self.start is None:
            if din:
                self.start = self.clk
            return 0
        k = self.clk - self.start            # 1 = SGL, 2 = D2, 3 = D1, 4 = D0
        if k <= 4:
            self.cfg = (self.cfg << 1) | din
            if k == 4:
                self._convert()
            return 0
        # k == 5: sample completes; k == 6: null bit; k >= 7: result bits (sampled on the rising edge).
        idx = k - (4 + SAMPLE_CLOCKS_AFTER_D0 + NULL_BITS) - 1
        if idx < 0:
            return 0
        return self.out_bits[idx] if idx < len(self.out_bits) else 0

    def _convert(self):
        sgl = (self.cfg >> 3) & 1
        sel = self.cfg & 7
        if NUM_CHANNELS == 4:
            sel &= 3
        code = code_for(sgl, sel, self.ctx.now_us)
        msb_first = [(code >> (RESOLUTION_BITS - 1 - i)) & 1 for i in range(RESOLUTION_BITS)]
        # Figure 5-2: after B0 the part sends the result LSB first, then zeros.
        lsb_first = [(code >> i) & 1 for i in range(1, RESOLUTION_BITS)]
        self.out_bits = msb_first + lsb_first
        self.converted = True
