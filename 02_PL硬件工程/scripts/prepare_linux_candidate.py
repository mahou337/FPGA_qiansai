"""Create a diagnostic FIT/DT candidate for the gesture hardware.
Kernel and initramfs bytes stay unchanged. This does NOT add the missing driver
or Python/OpenCV. The original vendor BOOT.BIN loads an incompatible PL image.
"""
from pathlib import Path
import argparse, hashlib, json, struct
from inspect_linux_image import Fdt

def cells(*values): return struct.pack('>%dI'%len(values), *values)
def text(value): return value.encode()+b'\0'

def dts(tree):
    lines=['/dts-v1/;','']
    def emit(path,depth):
        indent='    '*depth
        lines.append(indent+('/' if path=='/' else path.rsplit('/',1)[-1])+' {')
        for key,value in tree.nodes[path].items():
            if not value: suffix=''
            elif value[0]!=0 and value[-1]==0 and all(x==0 or 32<=x<127 for x in value):
                suffix=' = '+', '.join(json.dumps(x) for x in value[:-1].decode().split('\0'))
            elif len(value)%4==0:
                suffix=' = <'+' '.join('0x%x'%v for v in struct.unpack('>%dI'%(len(value)//4),value))+'>'
            else: suffix=' = ['+' '.join('%02x'%v for v in value)+']'
            lines.append(indent+'    '+key+suffix+';')
        for child in tree.nodes:
            if child!='/' and (child.rsplit('/',1)[0] or '/')==path: emit(child,depth+1)
        lines.append(indent+'};')
    emit('/',0); return '\n'.join(lines)+'\n'

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('image'); ap.add_argument('--output',required=True)
    args=ap.parse_args(); out=Path(args.output); out.mkdir(parents=True,exist_ok=True)
    image=Path(args.image).read_bytes(); fit=Fdt(image)
    if any('/signature' in p for p in fit.nodes): raise ValueError('Signed FIT requires authorized signing workflow')
    path=next(p for p,v in fit.nodes.items() if v.get('type')==text('flat_dt'))
    tree=Fdt(fit.nodes[path]['data'])
    assert tree.nodes['/memory']['reg']==cells(0,0x20000000)
    clkc='/amba/slcr@f8000000/clkc@100'
    phandle=struct.unpack('>I',tree.nodes[clkc]['phandle'])[0]
    assert tree.nodes[clkc]['ps-clk-frequency']==cells(33333333)
    changes=[]
    for p in ('/amba/spi@e0006000','/amba/ethernet@e000b000','/amba/usb@e0002000','/usb_phy@0'):
        tree.nodes[p]['status']=text('disabled'); changes.append(p+' disabled: absent from gesture PS configuration')
    for key in ('ethernet0','spi0'): tree.nodes['/aliases'].pop(key,None)
    tree.nodes[clkc]['fclk-enable']=cells(1)
    mmc=tree.nodes['/amba/mmc@e0100000']
    mmc['bus-width']=cells(4); mmc['xlnx,has-cd']=cells(1); mmc['disable-wp']=b''
    camera='/amba/camera@40000000'
    assert camera not in tree.nodes
    # No separate xilinx_dma driver may bind the same register window.
    for p,props in tree.nodes.items():
        if props.get('reg',b'')[:4] in (cells(0x40000000),cells(0x40400000)):
            raise ValueError('Conflicting device node '+p)
    tree.nodes[camera]={
        'compatible':text('linqiao,gesture-vga-1.0'),
        'reg':cells(0x40000000,0x40000,0x40400000,0x10000),
        'reg-names':text('capture')+text('dma'),
        'clocks':cells(phandle,15),'clock-names':text('fclk0'),
        'assigned-clocks':cells(phandle,15),'assigned-clock-rates':cells(50000000),
        'status':text('okay')}
    # Keep console/getty for bring-up; do not silently remove the only login path.
    changes+=['SD0 4-bit, card detect enabled, write protect disabled',
              'GST2 capture/DMA ownership node; FCLK0 assigned 50MHz',
              'UART0 Linux console/getty retained: not an application telemetry image']
    dt=tree.encode(); assert Fdt(dt).nodes==tree.nodes
    fit.nodes[path]['data']=dt
    for p,props in fit.nodes.items():
        if p.rsplit('/',1)[0]==path and 'algo' in props:
            algo=props['algo'].rstrip(b'\0').decode(); props['value']=hashlib.new(algo,dt).digest()
    candidate=fit.encode(); parsed=Fdt(candidate)
    assert parsed.nodes==fit.nodes
    original=Fdt(image)
    for p,props in original.nodes.items():
        if props.get('type') in (text('kernel'),text('ramdisk')):
            assert parsed.nodes[p]['data']==props['data']
    for p,props in parsed.nodes.items():
        if 'data' not in props: continue
        for child,h in parsed.nodes.items():
            if child.rsplit('/',1)[0]==p and 'value' in h and 'algo' in h:
                assert hashlib.new(h['algo'].rstrip(b'\0').decode(),props['data']).digest()==h['value']
    (out/'system-gesture.dtb').write_bytes(dt)
    (out/'system-gesture.dts').write_text(dts(tree))
    (out/'image-diagnostic.ub').write_bytes(candidate)
    report={'source_sha256':hashlib.sha256(image).hexdigest(),'output_sha256':hashlib.sha256(candidate).hexdigest(),
            'changes':changes,'kernel_unchanged':True,'rootfs_unchanged':True,'fit_hashes_verified':True,
            'driver_included':False,'python_opencv_included':False,'board_boot_tested':False,
            'requires':'matching gesture bitstream/PS initialization; old vendor BOOT.BIN must not be paired as-is'}
    (out/'candidate-validation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
if __name__=='__main__': main()
