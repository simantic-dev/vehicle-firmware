exec(compile(open("@SIM_FIXTURES@/peers/spi/ltc6811.py").read(), "ltc6811.py", "exec"))
NUM_ICS = 6
CELLS_PER_IC = [12, 9, 12, 9, 12, 9]
_g = lambda ic: ic + 6 * 1           # chip index within the pack
CELL_V = [[3.5 + 0.003 * (12 * _g(ic) + c) for c in range(12)] for ic in range(6)]
GPIO_V = [[ntc_v(20.0 + _g(ic))] * 4 + [mcp9701_v(30.0 + _g(ic))] for ic in range(6)]
