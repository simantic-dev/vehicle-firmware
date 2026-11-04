import re,sys,struct
# frames text -> pedal->torque table and key RTD events. usage: rtdtable.py frames.txt
rx=re.compile(r'\[(\w+)\] \[([\d.]+)s\] \((\w+)\) CAN (Tx|Rx) id=0x([0-9A-F]+) dlc=(\d+) data=([0-9A-F ]*)')
ev=[]
for l in open(sys.argv[1],errors='replace'):
    m=rx.search(l)
    if m: ev.append((float(m.group(2)),m.group(3),int(m.group(5),16),bytes.fromhex(m.group(7).replace(' ',''))))
def first(pred):
    for e in ev:
        if pred(e): return e
cw={0x92:'FL',0x93:'FR',0x90:'RL',0x91:'RR'}
for i,n in cw.items():
    e=first(lambda e:e[2]==i and e[3][1]&1); print("first INV %s CONTROL_WORD inverter_enable=1 at %.4f hv=%d drv=%d"%(n,e[0],e[3][1]>>1&1,e[3][1]>>2&1))
e=first(lambda e:e[2]==0x7f1); print("DASHBOARD_BUZZER_CONTROL 0x7f1 at %.4f data=%s"%(e[0],e[3].hex()))
for i,n in {0x80:'FL',0x85:'FR',0x70:'RL',0x75:'RR'}.items():
    e=first(lambda e,i=i:e[2]==i and e[3][1]>>5&1); print("first INV %s STATUS quit_inverter_on=1 at %.4f"%(n,e[0]))
e=first(lambda e:e[2]==0x207 and e[3][:2]==bytes([3,5])); print("CAR_STATES vehicle=3 drivetrain=5 at %s"%(e and "%.4f"%e[0]))
print("\nt(s)  FL_lim_Nm RL_lim_Nm  FL_echo_Nm(INV1_DYNAMICS)  speed_sp")
# CONTROL_INPUT sampled just before each window end
inp={0x99:'FL',0x97:'RL'}
last={}
wins=[(4.35,0.2),(4.75,0.5),(5.15,0.8),(5.55,1.0),(5.75,0.0)]
idx=0; out=[]
for t,bus,i,d in ev:
    if i in inp and bus=='can1' or i in inp: last[i]=(t,d)
    if i==0x82: last['dyn']=(t,d)
    while idx<len(wins) and t>=wins[idx][0]:
        w=wins[idx]; fl=last.get(0x99); rl=last.get(0x97); dy=last.get('dyn')
        s=lambda d:struct.unpack('<hhh',d[:6]) if d else None
        f=s(fl[1]); r=s(rl[1]); q=struct.unpack('<ihh',dy[1])[1]*0.0098
        print("%.2f accel=%.1f  FL +%.2f/-%.2f  RL +%.2f/-%.2f  FL_echo=%.2f  setpoint_rpm=%d"%(w[0],w[1],f[1]*.0098,f[2]*.0098,r[1]*.0098,r[2]*.0098,q,f[0]))
        idx+=1
