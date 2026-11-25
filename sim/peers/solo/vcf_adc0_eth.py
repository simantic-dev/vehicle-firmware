exec(compile(open("@SIMANTIC@/peers/generic/spi/mcp3208.py").read(), "mcp3208.py", "exec"))
# ADC_0 as vcf_adc0.py, but the driver presses the accelerator: both accel sensors ramp together from 2.2 s to 4.2 s.
def ramp(lo, hi, t0=2.2e6, t1=4.2e6):
    return lambda us: lo + (hi - lo) * min(max((us - t0) / (t1 - t0), 0.0), 1.0)
CHANNEL_V[:] = [0.0, 2.5, 1.0, 2.2, ramp(0.50, 2.50), ramp(0.55, 2.75), 0.40, 0.45]
