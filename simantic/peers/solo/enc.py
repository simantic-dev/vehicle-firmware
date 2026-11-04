exec(open("@SIM_FIXTURES@/peers/uart/abs_encoder.py").read())
# steering sweep: raw angle 180 -> 150 -> 210 -> 180 deg over 2.4 s
CONFIG.update(PROFILE={"type": "points", "points": [[0,180],[0.6,180],[1.1,150],[1.7,210],[2.2,180]]})
