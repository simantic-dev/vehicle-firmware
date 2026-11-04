exec(compile(open("@SIM_FIXTURES@/peers/spi/mcp3208.py").read(), "mcp3208.py", "exec"))
# ADC_1 (CS 38): SHDN H/D (24 V ~ 3439 counts), FL/FR load cells, FR/FL sus pots, brake pressures front/rear
CHANNEL_V[:] = [2.77, 2.77, 1.65, 1.60, 1.20, 1.25, 0.8, 0.9]
