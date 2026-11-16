exec(compile(open("@SIMANTIC@/peers/generic/spi/mcp3208.py").read(), "mcp3208.py", "exec"))
# ADC0 (CS 10): RL/RR load cells, RL/RR sus pots, GLV sense, current sense, reference
CHANNEL_V[:] = [1.65, 1.60, 1.20, 1.25, 2.77, 1.65, 3.3, 0.0]
