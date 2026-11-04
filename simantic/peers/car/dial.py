exec(compile(open("@SIM_FIXTURES@/peers/i2c/mcp23017.py").read(), "mcp23017.py", "exec"))
# rotary dial on port B pins 0-5, one pin low at a time (the vehicle's port B is inverted): mode 0, then 4 from 6.8 s to 8.4 s
def _mode(t_us):
    return 4 if 6_800_000 <= t_us < 8_400_000 else 0
for _i in range(6):
    PINS_B[_i] = (lambda t, i=_i: i != _mode(t))
