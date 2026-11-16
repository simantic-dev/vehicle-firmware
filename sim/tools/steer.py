import re,sys
# steering summary from a frames text: t, digital_raw, deg, flags
rx=re.compile(r'\[([\d.]+)s\] \(\w+\) CAN Tx id=0x41F dlc=7 data=([0-9A-F ]+)')
n=0; err=[0,0]; first_ok=None; rows=[]
for l in open(sys.argv[1]):
    m=rx.search(l)
    if not m: continue
    t=float(m.group(1)); d=bytes.fromhex(m.group(2).replace(' ',''))
    raw=((d[1]>>7)&1)|(d[2]<<1)|((d[3]&0x1f)<<9)
    ie=(d[3]>>7)&1; oor=(d[1]>>6)&1; both=(d[1]>>5)&1
    n+=1; err[ie]+=1
    if not ie and first_ok is None: first_ok=t
    rows.append((t,raw,ie,oor,both))
print("STEERING_DATA frames=%d interface_sensor_error: clear=%d set=%d first_clear_t=%s"%(n,err[0],err[1],first_ok))
step=int(sys.argv[2]) if len(sys.argv)>2 else 20
for r in rows[::step]: print("t=%.3f digital_raw=%5d (%.1f deg) iface_err=%d digital_oor=%d both_fail=%d"%(r[0],r[1],r[1]/16384*360,r[2],r[3],r[4]))
