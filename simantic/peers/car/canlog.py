# bus monitor: one line per frame with a 0.5 ms timestamp: "<us> <id hex> <data hex>"
import os
class Node:
    def __init__(self, ctx):
        self.us = 0
        self.f = open(os.environ["CARLOG"], "w")
        ctx.schedule_periodic(500)
    def on_timer(self):
        self.us += 500
    def on_frame(self, frame):
        self.f.write("%d %x %s\n" % (self.us, frame["id"], bytes(frame["data"]).hex()))
        self.f.flush()
