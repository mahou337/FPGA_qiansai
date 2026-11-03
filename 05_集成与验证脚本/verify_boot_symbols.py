from pathlib import Path
import struct,hashlib,json
B=Path(__file__).resolve().parents[1]
data=(B/'candidate/BOOT.BIN').read_bytes();old=(B/'backup/uart1_boot/BOOT.BIN').read_bytes();bit=(B/'candidate/system.bit').read_bytes()
pos=2+struct.unpack_from('>H',bit,0)[0]
assert bit[pos:pos+2]==b'\x00\x01';pos+=2
while bit[pos]!=ord('e'):
    size=struct.unpack_from('>H',bit,pos+1)[0];pos+=3+size
size=struct.unpack_from('>I',bit,pos+1)[0];payload=bit[pos+5:pos+5+size]
assert pos+5+size==len(bit)
converted=b''.join(payload[j:j+4][::-1] for j in range(0,len(payload),4))
partoff=struct.unpack_from('<I',data,0x9c)[0];oldoff=struct.unpack_from('<I',old,0x9c)[0]
checks=[]
for i,name in enumerate(('fsbl','bitstream','uboot')):
    h=struct.unpack_from('<16I',data,partoff+i*64)
    assert sum(h)&0xffffffff==0xffffffff
    p=data[h[5]*4:(h[5]+h[0])*4]
    if i==1:
        assert p[:len(converted)]==converted
        assert p[len(converted):]==b'\x00\x00\x00\x20' # word-swapped NOOP padding
        equal='exact candidate bit payload after bootgen word swap; one NOOP padding word'
    else:
        oh=struct.unpack_from('<16I',old,oldoff+i*64)
        assert p==old[oh[5]*4:(oh[5]+oh[0])*4]
        equal='byte-identical to working UART1 BOOT partition'
    checks.append(dict(partition=name,bytes=len(p),sha256=hashlib.sha256(p).hexdigest(),check=equal))
# Match every imported kernel symbol CRC, not merely module vermagic.
symbols={line.split()[1]:int(line.split()[0],16) for line in (B/'backup/Module.symvers').read_text().splitlines()}
required=[]
for line in (B/'evidence/module_symbol_versions.txt').read_text().splitlines():
    crc,name=line.split();assert symbols[name]==int(crc,16);required.append(name)
report={'boot_partitions':checks,'all_passed':True,'module_symbol_crc_matched':len(required),'symbols':required,'board_loaded_test':False}
(B/'evidence/boot_and_symbol_verification.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
