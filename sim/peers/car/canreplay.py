# replays a recorded bus log ("<us> <id hex> <data hex>") onto the bus, one frame at the recorded 0.5 ms tick
import os
class Node:
    def __init__(self, ctx):
        self.ctx = ctx
        self.frames = []
        for l in open(os.environ["REPLAY_LOG"]):
            p = l.split()
            self.frames.append((int(p[0]), int(p[1], 16), bytes.fromhex(p[2]) if len(p) > 2 else b""))
        self.i = 0
        self.us = 0
        ctx.schedule_periodic(500)
    def on_timer(self):
        self.us += 500
        while self.i < len(self.frames) and self.frames[self.i][0] <= self.us:
            _, fid, d = self.frames[self.i]
            self.ctx.send(fid, d)
            self.i += 1
