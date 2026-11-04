exec(compile(open("@SIM_FIXTURES@/peers/spi/mcp3208.py").read(), "mcp3208.py", "exec"))
# ADC1 (CS 36): eight thermistor channels at 1.2 V
CHANNEL_V[:] = [1.2] * 8
