"""Read EDID exported from the TARGET monitor on another computer; no guessing."""
from __future__ import print_function
import argparse,json,hashlib
p=argparse.ArgumentParser();p.add_argument('edid');a=p.parse_args()
data=open(a.edid,'rb').read()
if len(data)<128 or data[:8]!=bytes([0,255,255,255,255,255,255,0]):raise SystemExit('invalid EDID header')
blocks=1+data[126]
if len(data)<blocks*128:raise SystemExit('missing extension blocks')
if any(sum(data[i*128:(i+1)*128])%256 for i in range(blocks)):raise SystemExit('EDID checksum failed')
reasons=[]
if data[35]&32:reasons.append('established 640x480 @60')
def detailed(block,start,end):
    for pos in range(start,end-17,18):
        d=block[pos:pos+18];clock=(d[0]+256*d[1])*10000
        if not clock:continue
        h=d[2]+((d[4]&240)<<4);hb=d[3]+((d[4]&15)<<8)
        v=d[5]+((d[7]&240)<<4);vb=d[6]+((d[7]&15)<<8)
        hz=float(clock)/((h+hb)*(v+vb))
        if h==640 and v==480 and 59<=hz<=61 and not d[17]&128:
            reasons.append('detailed 640x480 progressive %.4f Hz'%hz)
detailed(data[:128],54,126)
for n in range(1,blocks):
    b=data[n*128:(n+1)*128]
    if b[0]!=2:continue
    end=b[2]
    if end==0:continue
    if not 4<=end<=127:raise SystemExit('invalid CTA block offset')
    i=4
    while i<end:
        tag=b[i]>>5;count=b[i]&31;i+=1
        if i+count>end:raise SystemExit('invalid CTA data block')
        if tag==2 and any(v&127==1 for v in b[i:i+count]):reasons.append('CTA VIC1')
        i+=count
    detailed(b,end,127)
print(json.dumps(dict(sha256=hashlib.sha256(data).hexdigest(),blocks=blocks,
    mode_advertised=bool(reasons),evidence=reasons,
    candidate='640x480 progressive, 800x525 total, 25.2MHz /60.000Hz',
    physical_link_test='still required; this parser does not verify cable/board/monitor lock'),indent=2))
if not reasons:raise SystemExit('No 640x480 ~60 evidence. Do not assume compatibility; review full EDID for another low-cost standard mode.')
