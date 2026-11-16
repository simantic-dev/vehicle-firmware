exec(compile(open("@SIMANTIC@/peers/generic/i2c/mcp23017.py").read(), "mcp23017.py", "exec"))
# rotary dial on port B pins 0-5, one pin low at a time (the vehicle's port B is inverted): mode 0 until 1.0 s, 2 until 1.5 s, then 4
def _mode(t_us):
    return 0 if t_us < 1_000_000 else (2 if t_us < 1_500_000 else 4)
for _i in range(6):
    PINS_B[_i] = (lambda t, i=_i: i != _mode(t))
