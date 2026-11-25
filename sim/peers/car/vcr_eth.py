# Stand-in for the VCR at 192.168.3.31 on the car Ethernet: answers ARP for that address and decodes every
# hytech_msgs.VCFData protobuf the VCF sends to UDP 4444 with sim/tools/pbdec.py and the HT_proto nanopb headers
# (fetched into build/proto by ./demo eth), printing a few decoded values every PRINT_MS of virtual time.
import glob, struct, sys

sys.path.insert(0, "@SIMANTIC@/../../tools")
import pbdec

IP = bytes([192, 168, 3, 31])
PORT = 4444
PRINT_MS = 250
SCHEMA = pbdec.Schema(glob.glob("@SIMANTIC@/../proto/*.pb.h"))
SHOW = [("pedals_system_data.accel_is_pressed", "accel pressed %d"),
        ("pedals_system_data.accel_is_implausible", "implausible %d"),
        ("pedals_system_data.brake_percent", "brake %4.1f %%"),
        ("steering_system_data.analog_steering_angle", "steer analog %6.1f"),
        ("steering_system_data.digital_steering_angle", "digital %6.1f deg")]

def get(d, path):
    for k in path.split("."):
        if not isinstance(d, dict) or k not in d:
            return None  # absent: proto3 default
        d = d[k]
    return d


class Peer:
    def __init__(self, ctx):
        self.ctx = ctx
        self.mac = bytes(int(x, 16) for x in ctx.mac.split(":"))
        self.n = 0
        self.next_ms = 0

    def on_frame(self, frame):
        b = frame["bytes"]
        et = frame["ethertype"]
        if et == 0x0806 and len(b) >= 42 and struct.unpack(">H", b[20:22])[0] == 1 and b[38:42] == IP:
            self.ctx.send(b[6:12] + self.mac + b"\x08\x06\x00\x01\x08\x00\x06\x04\x00\x02" + self.mac + IP + b[22:28] + b[28:32])
            print("vcr-eth  ARP who-has 192.168.3.31 from %s: replied" % ".".join(str(x) for x in b[28:32]), flush=True)
            return
        if et != 0x0800 or b[23] != 17 or b[30:34] != IP:
            return
        u = 14 + (b[14] & 15) * 4
        _, dport, ln = struct.unpack(">HHH", b[u:u + 6])
        if dport != PORT:
            return
        self.n += 1
        ms = self.ctx.now_us // 1000
        if ms < self.next_ms:
            return
        self.next_ms = ms + PRINT_MS
        msg = SCHEMA.decode("hytech_msgs_VCFData_s", bytes(b[u + 8:u + ln]))
        vals = [fmt % (get(msg, path) or 0) for path, fmt in SHOW]  # proto3 leaves zeros out of the wire
        print("vcr-eth  %6.2fs  VCFData #%-4d %3d B  %s" % (ms / 1000, self.n, ln - 8, "  ".join(vals)), flush=True)
