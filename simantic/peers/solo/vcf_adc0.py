exec(compile(open("@SIM_FIXTURES@/peers/spi/mcp3208.py").read(), "mcp3208.py", "exec"))
# ADC_0 (CS 10): ch1 2.5 V pedal reference, steering 1/2, accel 1/2, brake 1/2
CHANNEL_V[:] = [0.0, 2.5, 1.0, 2.2, 0.50, 0.55, 0.40, 0.45]
