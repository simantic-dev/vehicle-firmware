exec(compile(open("@SIMANTIC@/peers/generic/spi/mcp3208.py").read(), "mcp3208.py", "exec"))
# ADC_0 (CS 10): ch1 2.5 V pedal reference, ch2 steering (analog), ch4/5 accel 1/2, ch6/7 brake 1/2. Raw counts follow the stand-in calibration.
def _ramp(pts, t):
    t = t / 1e6
    if t <= pts[0][0]: return pts[0][1]
    for (t0, v0), (t1, v1) in zip(pts, pts[1:]):
        if t <= t1: return v0 + (v1 - v0) * (t - t0) / (t1 - t0)
    return pts[-1][1]
BRAKE = [(0, 0), (2.0, 0), (2.1, 0.9), (3.5, 0.9), (3.6, 0)]
ACCEL = [(0, 0), (4.0, 0), (5.5, 1.0), (5.7, 1.0), (6.6, 0)]
STEER_ENC = [(0, 180), (3.6, 180), (4.6, 150), (7.0, 210), (8.2, 180)]
def _v(raw): return (raw + 0.5) * 3.3 / 4096
def _steer(t): return _v(2048 + (180 - _ramp(STEER_ENC, t)) / 0.09765625)
CHANNEL_V[:] = [0.0, 2.5, _steer, 1.0, lambda t: _v(700 + 2400 * _ramp(ACCEL, t)), lambda t: _v(600 + 2000 * _ramp(ACCEL, t)),
                lambda t: _v(800 + 2600 * _ramp(BRAKE, t)), lambda t: _v(700 + 2300 * _ramp(BRAKE, t))]
