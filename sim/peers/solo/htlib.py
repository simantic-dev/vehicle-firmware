# CAN packers for the frames the stand-ins send (layouts from the vehicle CAN library's generated packers).
import struct
def pedals(accel=0.0, brake=0.0, brake_active=None, accel_active=None, accel_impl=0, brake_impl=0, both_impl=0, exceeded=0):
    ba = (brake > 0.05) if brake_active is None else brake_active
    aa = (accel > 0.05) if accel_active is None else accel_active
    mech = brake >= 0.2
    b0 = accel_impl | brake_impl << 1 | int(ba) << 2 | int(aa) << 3 | int(mech) << 4 | both_impl << 5 | exceeded << 6
    return struct.pack("<BHH", b0, int(accel / 0.000015259), int(brake / 0.000015259)) + b"\0\0\0"[:0]
def steering(angle_deg=0.0):
    ro = int((angle_deg + 360.0) / 0.01)
    d = bytearray(7)
    d[0] = (2048 & 0x7F) << 1
    d[1] = (2048 >> 7) & 0x1F
    d[4:7] = bytes([ro & 0xFF, (ro >> 8) & 0xFF, (ro >> 16) & 1])
    return bytes(d)
def dash(start=0, dial=0, mc_cycle=0, preset=0, data=0):
    return bytes([preset << 1 | mc_cycle << 2 | start << 4 | data << 5, dial, 0])
def acu_ok(bms=1, imd=1, latch=1):
    return bytes([bms | imd << 1 | latch << 2])
def db_speed(rpm):
    return struct.pack("<4h", *rpm)
def db_torque(nm):
    return struct.pack("<4h", *[int(round(x / 0.01)) for x in nm])
def inv_status(ready=0, error=0, quit_dc=0, dc_on=0, quit_inv=0, inv_on=0, vdc=0, diag=0):
    return bytes([0, ready | error << 1 | quit_dc << 3 | dc_on << 4 | quit_inv << 5 | inv_on << 6]) + struct.pack("<HH", vdc, diag) + b"\0\0"
def inv_dynamics(power_w=0, torque_nm=0.0, rpm=0):
    return struct.pack("<Ihh", power_w, int(torque_nm / 0.0098), rpm)
# inverter CAN ids per position: FL=INV1, FR=INV2, RL=INV3, RR=INV4
INV = {
    "FL": dict(status=0x80, dyn=0x82, word=0x92, inp=0x99),
    "FR": dict(status=0x85, dyn=0x87, word=0x93, inp=0x102),
    "RL": dict(status=0x70, dyn=0x72, word=0x90, inp=0x97),
    "RR": dict(status=0x75, dyn=0x77, word=0x91, inp=0x98),
}
