# Local stand-in for the host-side planner at 192.168.3.30: answers ARP for that address and records every UDP datagram sent to it.
import os, struct
OUT = os.environ.get("FULLCAR_OUT", ".")
IP = bytes([192, 168, 3, 30])
class Peer:
    def __init__(self, ctx):
        self.ctx = ctx
        self.mac = bytes(int(b, 16) for b in ctx.mac.split(":"))
        self.f = open(os.path.join(OUT, "udp.jsonl"), "w")
        self.t = 0
        self.arp = 0
        self.udp = {}
        ctx.schedule_periodic(10000)
    def on_timer(self):
        self.t += 1
    def on_frame(self, frame):
        b = frame["bytes"]
        et = frame["ethertype"]
        if et == 0x0806 and len(b) >= 42:
            op = struct.unpack(">H", b[20:22])[0]
            if op == 1 and b[38:42] == IP:
                self.arp += 1
                reply = b[6:12] + self.mac + b"\x08\x06\x00\x01\x08\x00\x06\x04\x00\x02" + self.mac + IP + b[22:28] + b[28:32]
                self.ctx.send(reply)
        elif et == 0x0800 and b[23] == 17 and b[30:34] == IP:
            ihl = (b[14] & 15) * 4
            u = 14 + ihl
            sport, dport, ln = struct.unpack(">HHH", b[u:u + 6])
            payload = bytes(b[u + 8:u + ln])
            src = ".".join(str(x) for x in b[26:30])
            self.udp[(src, dport)] = self.udp.get((src, dport), 0) + 1
            n = self.udp[(src, dport)]
            if n <= 3 or n % 50 == 0:
                self.f.write('{"t10ms":%d,"src":"%s","sport":%d,"dport":%d,"n":%d,"len":%d,"hex":"%s"}\n' % (self.t, src, sport, dport, n, len(payload), payload.hex()))
                self.f.flush()
