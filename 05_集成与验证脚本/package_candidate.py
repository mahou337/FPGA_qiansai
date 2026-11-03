from pathlib import Path
import struct,json,hashlib,subprocess,shutil,os,zipfile,xml.etree.ElementTree as E
B=Path('/home/huzhen/hdmi_linux_integration_20261102')
C=B/'candidate';old=B/'backup/uart1_boot'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def fdt(data):
    h=struct.unpack_from('>10I',data);assert h[0]==0xd00dfeed
    pos=h[2];strings=data[h[3]:h[3]+h[8]];stack=[];nodes={}
    while True:
        tag=struct.unpack_from('>I',data,pos)[0];pos+=4
        if tag==1:
            end=data.index(b'\0',pos);name=data[pos:end].decode();pos=(end+4)&~3
            stack.append(name);path='/'.join(stack) or '/';nodes[path]={}
        elif tag==2:stack.pop()
        elif tag==3:
            length,offset=struct.unpack_from('>II',data,pos);pos+=8
            key=strings[offset:strings.index(b'\0',offset)].decode()
            nodes['/'.join(stack) or '/'][key]=data[pos:pos+length].hex();pos=(pos+length+3)&~3
        elif tag==4:pass
        elif tag==9:break
        else:raise ValueError(tag)
    return nodes
before=fdt((old/'system.dtb').read_bytes());after=fdt((C/'system.dtb').read_bytes())
changes=[]
for path in sorted(set(before)|set(after)):
    if before.get(path)!=after.get(path):
        changes.append({'path':path,'properties':{key:{'old':before.get(path,{}).get(key),'new':after.get(path,{}).get(key)} for key in set(before.get(path,{}))|set(after.get(path,{})) if before.get(path,{}).get(key)!=after.get(path,{}).get(key)}})
(B/'evidence/dt_semantic_diff.json').write_text(json.dumps(changes,indent=2,sort_keys=True))
print(json.dumps(changes,indent=2))
expected={'/amba_pl/mask_display_axi@43c00000','/amba_pl/misc_clk_1'}
assert set(x['path'] for x in changes)==expected,'Unexpected existing device tree change'
nodes=[(path,props) for path,props in after.items() if props.get('reg','').startswith('43c00000')]
assert len(nodes)==1
node=nodes[0][1];assert node['reg']=='43c0000000080000'
assert bytes.fromhex(node['compatible']).rstrip(b'\0')==b'hellofpga,mask-display-1.0'
assert node['clocks']=='000000010000000f';assert not set(('interrupts','memory-region','dmas','dma-coherent'))&set(node)
clk=after['/amba/slcr@f8000000/clkc@100']
assert clk['phandle']=='00000001';assert bytes.fromhex(clk['clock-output-names']).split(b'\0')[15]==b'fclk0'
assert after['/amba_pl/gesture_camera_vga@40000000']['assigned-clock-rates']=='02faf080'
# Verify actual working UART1 hardware, including all PS parameters and init files.
with zipfile.ZipFile(str(B/'backup/uart1_sources/system.hdf')) as z1, zipfile.ZipFile(str(B/'handoff_original/hardware/system.hdf')) as z2:
    init={n:z1.read(n)==z2.read(n) for n in z1.namelist() if 'ps7_init' in n}
    assert all(init.values())
    def params(z):
        root=E.fromstring(z.read('system.hwh'))
        return {m.get('INSTANCE'):{p.get('NAME'):p.get('VALUE') for p in m.findall('./PARAMETERS/PARAMETER')} for m in root.iter('MODULE')}
    p1,p2=params(z1),params(z2)
    preserved={n:p1[n]==p2[n] for n in ('ps7','capture','dma','memory_axi','camera_fifo','reset','one')}
    assert all(preserved.values())
    bitname=next(n for n in z2.namelist() if n.endswith('.bit'))
    assert hashlib.sha256(z2.read(bitname)).hexdigest()==sha(B/'handoff_original/hardware/system.bit')
# Reuse the exact previously working FSBL, U-Boot, kernel (PS init identical).
for n in ('fsbl.elf','u-boot.elf','zImage'):shutil.copyfile(str(old/n),str(C/n))
for n in ('system.bit','system.hdf'):shutil.copyfile(str(B/'handoff_original/hardware'/n),str(C/n))
(C/'hdmi.bif').write_text('the_ROM_image:\n{\n [bootloader] fsbl.elf\n system.bit\n u-boot.elf\n}\n')
(C/'image.its').write_text((old/'image.its').read_text().replace('UART1 hand candidate','HDMI MSK1 + preserved UART1 candidate').replace('Original GST2 plus UART1 EMIO','Original GST2 plus MSK1 + UART1 EMIO'))
tools=Path('/home/huzhen/zynq_projects/zynq_ov5640/build/tmp/sysroots-components/x86_64')
mk=tools/'u-boot-mkimage-native/usr/bin/mkimage';dtc=tools/'dtc-native/usr/bin'
os.environ['PATH']=str(dtc)+':'+os.environ['PATH']
subprocess.check_call(['/home/huzhen/petalinux/2019.1/tools/xsct/bin/bootgen','-arch','zynq','-image','hdmi.bif','-o','BOOT.BIN','-w','on'],cwd=str(C))
subprocess.check_call([str(mk),'-f','image.its','image.ub'],cwd=str(C))
subprocess.check_call([str(mk),'-l','image.ub'],cwd=str(C))
# Decode FIT and verify embedded data against inputs, not merely its description.
fit=fdt((C/'image.ub').read_bytes())
assert bytes.fromhex(fit['/images/kernel-1']['data'])==(C/'zImage').read_bytes()
assert bytes.fromhex(fit['/images/fdt-1']['data'])==(C/'system.dtb').read_bytes()
for node_name,file in (('kernel-1','zImage'),('fdt-1','system.dtb')):
    assert fit['/images/'+node_name+'/hash-1']['value']==sha(C/file)
ver=subprocess.check_output(['modinfo','-F','vermagic',str(C/'gesture_mask_display.ko')]).decode().strip()
assert ver==subprocess.check_output(['modinfo','-F','vermagic',str(B/'backup/gesture_vga.ko')]).decode().strip()
assert sha(B/'kernel-obj/arch/arm/boot/zImage')==sha(C/'zImage')
report={'all_checks_passed':True,'ps_initialization_equal':init,'preserved_hdf_modules':preserved,'dt_only_added_nodes':sorted(expected),'one_display_reg_node':True,'clock_fclk0_50mhz':True,'fit_embedded_kernel_and_dt_verified':True,'kernel_matches_build_tree':True,'vermagic':ver,'Module.symvers':sha(B/'kernel-obj/Module.symvers'),'FSBL_reused_reason':'six PS initialization files and every PS parameter byte/value identical to working UART1 hardware','physical_boot_verified':False,'board_running_uname_verified':False,'artifacts':{p.name:sha(p) for p in C.iterdir() if p.is_file()}}
(B/'evidence/component_consistency.json').write_text(json.dumps(report,indent=2,sort_keys=True))
(C/'vermagic.txt').write_text(ver+'\n')
print(json.dumps(report,indent=2))
