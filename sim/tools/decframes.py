import os,re,sys,subprocess
# usage: decframes.py frames.txt ID[,ID..] [machine]  -> "t  decoded" for CAN Tx/Rx frames with those ids (hex ok)
f=sys.argv[1]; ids={int(x,0) for x in sys.argv[2].split(',')}; mach=sys.argv[3] if len(sys.argv)>3 else None
rx=re.compile(r'\[(\w+)\] \[([\d.]+)s\] \((\w+)\) CAN (Tx|Rx) id=0x([0-9A-F]+) dlc=(\d+) data=([0-9A-F ]*)')
rows=[]
for l in open(f,errors='replace'):
    m=rx.search(l)
    if not m: continue
    mm,t,bus,dr,i,dlc,d=m.groups(); i=int(i,16)
    if i in ids and (mach is None or mm==mach): rows.append((float(t),mm,bus,dr,i,d.replace(' ','')))
inp=''.join('%x %s\n'%(r[4],r[5] or '00') for r in rows)
out=subprocess.run([os.environ.get('HTCAN_DEC') or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'build', 'htcan_dec')],input=inp,capture_output=True,text=True).stdout.splitlines()
for r,o in zip(rows,out): print("%.4f %s %s %s 0x%X %s | %s"%(r[0],r[1],r[2],r[3],r[4],r[5],o))
print("n=%d decoded=%d"%(len(rows),len(out)),file=sys.stderr)
