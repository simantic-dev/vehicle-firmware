exec(compile(open("@SIMANTIC@/peers/generic/spi/ltc6811.py").read(), "ltc6811.py", "exec"))
NUM_ICS = 6
CELLS_PER_IC = [12, 9, 12, 9, 12, 9]
_g = lambda ic: ic + 6 * 0           # chip index within the pack
CELL_V = [[3.5 + 0.003 * (12 * _g(ic) + c) for c in range(12)] for ic in range(6)]
GPIO_V = [[ntc_v(20.0 + _g(ic))] * 4 + [mcp9701_v(30.0 + _g(ic))] for ic in range(6)]
# cell 1 of the first IC sags below the undervoltage limit from 8.0 s (ramp over 0.5 s)
CELL_V[0][0] = lambda t: 3.5 if t < 8_000_000 else max(2.9, 3.5 - 1.2 * (t - 8_000_000) / 1e6)
