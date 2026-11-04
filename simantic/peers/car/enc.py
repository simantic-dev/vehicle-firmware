exec(open("@SIM_FIXTURES@/peers/uart/abs_encoder.py").read())
# steering angle (raw encoder degrees; 180 = centre): hold, 150 (30 deg/s), 210 (25 deg/s), back to 180
CONFIG.update(PROFILE={"type": "points", "points": [[0,180],[3.6,180],[4.6,150],[7.0,210],[8.2,180]]})
