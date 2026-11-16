# Stand-in for the front controller + dashboard + ACU + planner on the telemetry CAN: pedals, steering, dash buttons/dial,
# ACU_OK and the planner's speed/torque commands, driven by a timeline (ms of virtual time, 5 ms ticks).
import os
exec(open("@SIMANTIC@/peers/solo/htlib.py").read())
OUT = os.environ.get("RTD_OUT", ".")
PLAN = os.environ.get("RTD_PLAN", "A")
# (t_ms, {state updates})
PLANS = {
  "A": [
    (2000, dict(brake=0.6)),
    (2300, dict(start=1)),
    (3800, dict(start=0, brake=0.0)),
    (4000, dict(accel=0.2)), (4400, dict(accel=0.5)), (4800, dict(accel=0.8)), (5200, dict(accel=1.0)), (5600, dict(accel=0.0)),
    # accel + brake together with the pedal-system implausibility flags set, accel value still reported
    (5800, dict(accel=0.5, brake=0.3, both_impl=1)),
    # same, but the accel value is forced to 0 as the pedal controller does when it latches the implausibility
    (6200, dict(accel=0.0, brake=0.3, both_impl=1, exceeded=1)),
    (6600, dict(accel=0.0, brake=0.0, both_impl=0, exceeded=0)),
    (6800, dict(accel=0.4)),
    # pedals frames stop for 300 ms
    (7200, dict(pedals_tx=0)), (7500, dict(pedals_tx=1)),
    (8000, dict(accel=0.0)),
  ],
  "C": [
    (2000, dict(brake=0.6)), (2300, dict(start=1)), (3800, dict(start=0, brake=0.0)),
    (4000, dict(accel=0.2)),
    (4500, dict(steer_tx=0)), (4800, dict(steer_tx=1)),
    (5200, dict(accel=0.0, brake=0.6)), (5400, dict(start=1)), (5800, dict(start=0, brake=0.0)),
    (6000, dict(accel=0.3)),
    # HV drop is done by the inverter stand-in at 7000-7300
    (7600, dict(accel=0.0)),
  ],
  "D": [
    (2000, dict(brake=0.6)), (2300, dict(start=1)), (3800, dict(start=0, brake=0.0)),
    (4000, dict(accel=0.2)),
    # the inverter stand-in latches an error on FL at 4500
    (5400, dict(mc=1)), (5700, dict(mc=0)),
    (6500, dict(accel=0.0)),
  ],
  "B": [
    (2000, dict(brake=0.6)),
    (2300, dict(start=1)),
    (3800, dict(start=0, brake=0.0)),
    (4000, dict(accel=0.3)),
    # dial to 4 while the planner still asks 21 Nm: the mux must refuse (torque step > 0.5 Nm)
    (4400, dict(dial=4)),
    (5000, dict(db_t=0.0)),                          # planner asks 0 Nm: switch allowed
    (5400, dict(db_t=15.0, db_rpm=3000)),
    (5800, dict(db_t=8.0, db_rpm=5000)),
    (6200, dict(db_t=8.0, db_rpm=5000, dbtx=0)),     # planner silent: timeout path
    (6600, dict(dbtx=1)),
    (7000, dict(dial=0)),
  ],
}
class Node:
    def __init__(self, ctx):
        self.ctx = ctx
        self.n = 0
        self.plan = PLANS[PLAN]
        self.i = 0
        self.s = dict(accel=0.0, brake=0.0, start=0, dial=0, both_impl=0, exceeded=0, pedals_tx=1, steer_tx=1, dbtx=1,
                      db_t=21.0 if PLAN == "B" else 0.0, db_rpm=0, mc=0)
        self.f = open(os.path.join(OUT, "telem-%s.log" % PLAN), "w")
        self.rx = {}
        ctx.schedule_periodic(5000)
    def log(self, m):
        self.f.write("%d.%03d %s\n" % (self.n * 5 // 1000, self.n * 5 % 1000, m)); self.f.flush()
    def on_frame(self, frame):
        i = frame["id"]
        d = bytes(frame["data"])
        self.rx[i] = self.rx.get(i, 0) + 1
        if i in (0x207, 0x7f1):
            self.log("RX 0x%x %s" % (i, d.hex()))
    def on_timer(self):
        self.n += 1
        t = self.n * 5
        while self.i < len(self.plan) and self.plan[self.i][0] <= t:
            self.s.update(self.plan[self.i][1]); self.log("EVENT %s" % (self.plan[self.i][1],)); self.i += 1
        s = self.s
        ctx = self.ctx
        # at most 4 frames per tick: the receiving FIFO is 6 deep and the medium does not space frames
        if self.n % 2 == 0:
            if s["pedals_tx"]:
                ctx.send(0xc0, pedals(s["accel"], s["brake"], both_impl=s["both_impl"], exceeded=s["exceeded"]))
            if s["steer_tx"] and self.n % 4 == 0:
                ctx.send(0x41f, steering(0.0))
        else:
            if s["dbtx"]:
                ctx.send(0xf2, db_speed([s["db_rpm"]] * 4))
                ctx.send(0xf1, db_torque([s["db_t"]] * 4))
            if self.n % 8 == 1:
                ctx.send(0x300, dash(start=s["start"], dial=s["dial"], mc_cycle=s["mc"]))
            if self.n % 8 == 5:
                ctx.send(0x500, acu_ok())
