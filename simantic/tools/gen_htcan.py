import re,sys
H=open(sys.argv[1]+'/ht_can.h',errors='replace').read()
msgs=[]
for m in re.finditer(r'// def @(\w+) CAN Message \((\d+)\s+0x([0-9a-f]+)\)',H):
    name=m.group(1); cid=int(m.group(2))
    st=H.index('typedef struct',m.end()); en=H.index('} %s_t;'%name,st)
    body=H[st:en]
    # first variant only (before '#else')
    body=body.split('#else')[0]
    fields=re.findall(r'^\s+((?:u?int\d+_t|bool|uint\d+_t))\s+(\w+);',body,re.M)
    msgs.append((name,cid,fields))
out=['#include <stdio.h>','#include <stdint.h>','#include <stdlib.h>','#include <string.h>','#include "ht_can.h"',
'int main(void){char line[256];while(fgets(line,sizeof line,stdin)){unsigned id;char hx[64]={0};if(sscanf(line,"%x %63s",&id,hx)<1)continue;uint8_t d[8]={0};int n=strlen(hx)/2;for(int i=0;i<n&&i<8;i++){unsigned b;sscanf(hx+2*i,"%2x",&b);d[i]=b;}',
'switch(id){']
for name,cid,fields in msgs:
    out.append('case %d:{%s_t m;memset(&m,0,sizeof m);Unpack_%s_ht_can(&m,d,n);printf("%s"'%(cid,name,name,name))
    for t,f in fields:
        out.append(' " %s=%%lld",(long long)m.%s'%(f,f)) if False else None
    fmt=''.join(' %s=%%lld'%f for t,f in fields)
    args=''.join(',(long long)m.%s'%f for t,f in fields)
    out[-1]='case %d:{%s_t m;memset(&m,0,sizeof m);Unpack_%s_ht_can(&m,d,n);printf("%s%s\\n"%s);break;}'%(cid,name,name,name,fmt,args)
out.append('default:printf("UNKNOWN_0x%x\\n",id);}}return 0;}')
open('htcan_dec.c','w').write('\n'.join(out))
print(len(msgs),'messages')
