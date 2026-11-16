exec(compile(open("@SIMANTIC@/peers/generic/spi/max1148.py").read(), "max1148.py", "exec"))
# ACU ADC0 (CS 10): iso pack N/P, pack sense, shunt out/P/N, TS out filtered, pack out filtered
CHANNEL_V[:] = [0.4 * (c + 1) for c in range(8)]
