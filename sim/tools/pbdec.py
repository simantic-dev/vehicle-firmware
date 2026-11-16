"""Decode nanopb wire data using the field names/tags in a generated .pb.h (local tool)."""
import re,struct,sys,glob
class Schema:
    def __init__(self,hdrs):
        self.msgs={}  # name -> {tag:(fname,type)}
        txt=''.join(open(h,errors='replace').read() for h in hdrs)
        tags=dict(((m,f),int(t)) for m,f,t in re.findall(r'#define (\w+?)_(\w+)_tag (\d+)',txt) ) if False else {}
        tagmap={}
        for m in re.finditer(r'#define (\w+)_tag (\d+)',txt): tagmap[m.group(1)]=int(m.group(2))
        for m in re.finditer(r'typedef struct _(\w+) \{(.*?)\n\} \1;',txt,re.S):
            name=m.group(1); body=m.group(2); fields={}
            for line in body.split('\n'):
                line=re.sub(r'/\*.*?\*/','',line).strip()
                mm=re.match(r'^(?:struct )?([\w ]+?)\s+(\w+)(\[\d+\])?;$',line)
                if not mm: continue
                typ,fn,arr=mm.groups()
                if fn.startswith('has_') or fn.endswith('_count') or typ in('pb_size_t',): continue
                t=tagmap.get('%s_%s'%(name,fn))
                if t is None: continue
                fields[t]=(fn,typ.strip(),bool(arr))
            self.msgs[name]=fields
    def decode(self,name,data):
        out={}
        i=0;f=self.msgs.get(name,{})
        while i<len(data):
            k,i=varint(data,i);tag=k>>3;wt=k&7
            if wt==0: v,i=varint(data,i)
            elif wt==1: v=struct.unpack('<d',data[i:i+8])[0];i+=8
            elif wt==5: v=struct.unpack('<f',data[i:i+4])[0];i+=4
            elif wt==2:
                l,i=varint(data,i);v=data[i:i+l];i+=l
            else: break
            fn,typ,arr=f.get(tag,('tag%d'%tag,None,False))
            if wt==2 and typ in self.msgs: v=self.decode(typ,v)
            elif wt==2: v=bytes(v).hex()
            if arr: out.setdefault(fn,[]).append(v)
            else: out[fn]=v
        return out
def varint(d,i):
    r=0;s=0
    while True:
        b=d[i];i+=1;r|=(b&0x7f)<<s;s+=7
        if not b&0x80:return r,i
