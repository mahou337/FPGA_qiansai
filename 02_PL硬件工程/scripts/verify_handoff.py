#!/usr/bin/env python3
"""Offline verification of a UART1-only derivative. Python standard library only.
Usage: python verify_handoff.py BASELINE_PROJECT UART1_PROJECT OUTPUT_DIRECTORY
BASELINE_PROJECT must contain the original build/vga_system.hdf and .bit.
No Vivado, board connection, serial I/O, or filesystem writes outside OUTPUT_DIRECTORY.
"""
import sys, json, hashlib, zipfile, difflib, re
from pathlib import Path
from xml.etree import ElementTree as ET

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def load_bd(p):
    return json.loads((p/'build/vivado_vga/gesture_vga.srcs/sources_1/bd/system/system.bd').read_text())['design']
def load_hdf(p):
    with zipfile.ZipFile(p) as z:
        root=ET.fromstring(z.read('system.hwh'))
        bits=[n for n in z.namelist() if n.endswith('.bit')]
        assert len(bits)==1, bits
        bh=hashlib.sha256(z.read(bits[0])).hexdigest()
        init={n:z.read(n).decode('utf-8',errors='replace') for n in z.namelist() if n.startswith('ps7_init')}
    modules={m.get('INSTANCE'):m for m in root.findall('./MODULES/MODULE')}
    params={k:{p.get('NAME'):p.get('VALUE') for p in v.findall('./PARAMETERS/PARAMETER')} for k,v in modules.items()}
    ports={p.get('NAME'):ET.tostring(p,encoding='unicode').strip() for p in root.findall('./EXTERNALPORTS/PORT')}
    return root,params,ports,bh,init

def main():
    base,new,out=map(Path,sys.argv[1:4]);out.mkdir(parents=True,exist_ok=True)
    checks={}
    def ck(name,ok): checks[name]=bool(ok)
    ck('baseline_hdf_known_sha256',sha(base/'build/vga_system.hdf')=='1ca63e2794e0e02a26dd5351a3917fbeedc5623fbd18188f4a8a03ac39903042')
    ck('baseline_bit_known_sha256',sha(base/'build/vga_system.bit')=='47a9ff8681c5c43ab23e362c4d318db78021dc2fc9f5716acb1fe695f566b02d')
    for folder in ['pl','config']:
        for f in (base/folder).rglob('*'):
            if f.is_file():
                rel=f.relative_to(base)
                ck('unchanged:'+rel.as_posix(),(new/rel).is_file() and sha(f)==sha(new/rel))
    a,b=load_bd(base),load_bd(new)
    for key in ['interface_ports','interface_nets','addressing']:
        ck('BD_'+key+'_unchanged',a[key]==b[key])
    ck('same_IP_inventory',set(a['components'])==set(b['components']))
    for name in a['components']:
        if name!='ps7':ck('BD_component_unchanged:'+name,a['components'][name]==b['components'][name])
    ck('BD_existing_ports_unchanged',all(b['ports'].get(k)==v for k,v in a['ports'].items()))
    ck('BD_only_two_added_ports',set(b['ports'])-set(a['ports'])=={'uart1_tx','uart1_rx'})
    ck('BD_existing_nets_unchanged',all(b['nets'].get(k)==v for k,v in a['nets'].items()))
    added={k:v for k,v in b['nets'].items() if k not in a['nets']}
    ck('BD_only_two_added_nets',len(added)==2)
    for port,pin,di in [('uart1_tx','UART1_TX','O'),('uart1_rx','UART1_RX','I')]:
        ck('BD_direct_connection:'+port,any(set(v['ports'])=={port,'ps7/'+pin} for v in added.values()) and b['ports'][port]['direction']==di)
    ah,ap,ae,abit,ai=load_hdf(base/'build/vga_system.hdf')
    bh,bp,be,bbit,bi=load_hdf(new/'build/vga_system.hdf')
    ck('baseline_embedded_bit_matches',abit==sha(base/'build/vga_system.bit'))
    ck('new_embedded_bit_matches',bbit==sha(new/'build/vga_system.bit'))
    ck('HDF_same_IP_inventory',set(ap)==set(bp))
    for name in ap:
        if name!='ps7':ck('HDF_params_unchanged:'+name,ap[name]==bp[name])
    diffs={k:{'old':ap['ps7'].get(k),'new':bp['ps7'].get(k)} for k in sorted(set(ap['ps7'])|set(bp['ps7'])) if ap['ps7'].get(k)!=bp['ps7'].get(k)}
    allowed={'PCW_EN_EMIO_UART1','PCW_EN_UART1','PCW_UART1_PERIPHERAL_ENABLE','PCW_UART1_UART1_IO'}
    ck('HDF_only_UART1_PS_parameter_changes',set(diffs)<=allowed)
    expected={'PCW_EN_EMIO_UART0':'1','PCW_EN_EMIO_UART1':'1','PCW_EN_UART0':'1','PCW_EN_UART1':'1','PCW_UART0_UART0_IO':'EMIO','PCW_UART1_UART1_IO':'EMIO','PCW_UART0_BAUD_RATE':'115200','PCW_UART0_GRP_FULL_ENABLE':'0','PCW_UART1_GRP_FULL_ENABLE':'0','PCW_ACT_UART_PERIPHERAL_FREQMHZ':'100.000000'}
    for k,v in expected.items():ck('HDF_expected:'+k,bp['ps7'].get(k)==v)
    ck('HDF_existing_external_ports_unchanged',all(be.get(k)==v for k,v in ae.items()))
    ck('HDF_only_two_added_ports',set(be)-set(ae)=={'uart1_tx','uart1_rx'})
    for port,pin in [('uart_tx','UART0_TX'),('uart_rx','UART0_RX'),('uart1_tx','UART1_TX'),('uart1_rx','UART1_RX')]:
        elem=bh.find("./EXTERNALPORTS/PORT[@NAME='%s']"%port)
        ck('HDF_port_connection:'+port,elem is not None and any(c.get('INSTANCE')=='ps7' and c.get('PORT')==pin for c in elem.findall('./CONNECTIONS/CONNECTION')))
    # Compare all module port/interface and address sections outside ps7 as structural XML.
    for name in ap:
        if name=='ps7':continue
        am=ah.find("./MODULES/MODULE[@INSTANCE='%s']"%name)
        bm=bh.find("./MODULES/MODULE[@INSTANCE='%s']"%name)
        for key in ['PORTS','BUSINTERFACES','MEMORYMAP']:
            aa=am.find(key);bb=bm.find(key)
            ck('HDF_structure_unchanged:'+name+'/'+key,(ET.tostring(aa) if aa is not None else b'')==(ET.tostring(bb) if bb is not None else b''))
    # Verify generated PS initialization: retain all old register writes except
    # enabling UART1 clock gates and adding UART1-only peripheral setup.
    def init_arrays(text):
        text=re.sub(r'/\*.*?\*/','',text,flags=re.S)
        text=re.sub(r'//[^\n]*','',text)
        return {n:re.sub(r'\s+','',body) for n,body in re.findall(r'unsigned long\s+(ps7_\w+)\[\]\s*=\s*\{(.*?)\};',text,re.S)}
    old_arrays=init_arrays(ai['ps7_init.c'])
    new_arrays=init_arrays(bi['ps7_init.c'])
    ck('PS_init_array_inventory_unchanged',bool(old_arrays) and set(old_arrays)==set(new_arrays))
    uart1_init_regs={
        '0XE0001034':('0x000000FFU','0x00000006U'),
        '0XE0001018':('0x0000FFFFU','0x0000007CU'),
        '0XE0001000':('0x000001FFU','0x00000017U')}
    for name,body in new_arrays.items():
        normalized=body.replace('EMIT_MASKWRITE(0XF8000154,0x00003F33U,0x00001003U)',
                                'EMIT_MASKWRITE(0XF8000154,0x00003F33U,0x00001001U)')
        normalized=normalized.replace('EMIT_MASKWRITE(0XF800012C,0x01FFCCCDU,0x017C040DU)',
                                      'EMIT_MASKWRITE(0XF800012C,0x01FFCCCDU,0x015C040DU)')
        for addr,(mask,value) in uart1_init_regs.items():
            normalized=normalized.replace('EMIT_MASKWRITE(%s,%s,%s),'%(addr,mask,value),'')
        for mask in ['0x000003FFU','0x00000FFFU']:
            normalized=normalized.replace('EMIT_MASKWRITE(0XE0001004,%s,0x00000020U),'%mask,'')
        ck('PS_init_unchanged_except_UART1:'+name,normalized==old_arrays.get(name))
    changes={}
    for n in ai:
        if n in bi and ai[n]!=bi[n]:
            changes[n]=''.join(difflib.unified_diff(ai[n].splitlines(True),bi[n].splitlines(True),fromfile='baseline/'+n,tofile='uart1/'+n))
            (out/(n+'.diff')).write_text(changes[n],encoding='utf-8')
    bd_ps_diff={k:{'old':a['components']['ps7']['parameters'].get(k),'new':b['components']['ps7']['parameters'].get(k)} for k in sorted(set(a['components']['ps7']['parameters'])|set(b['components']['ps7']['parameters'])) if a['components']['ps7']['parameters'].get(k)!=b['components']['ps7']['parameters'].get(k)}
    ck('BD_only_UART1_PS_parameter_changes',set(bd_ps_diff)<=allowed|{'PCW_UART1_GRP_FULL_ENABLE'})
    ck('BD_UART1_flow_control_explicitly_disabled',b['components']['ps7']['parameters'].get('PCW_UART1_GRP_FULL_ENABLE')=={'value':'0'} and ap['ps7'].get('PCW_UART1_GRP_FULL_ENABLE')=='0')
    clk=float(bp['ps7']['PCW_ACT_UART_PERIPHERAL_FREQMHZ'])*1000000
    uart_math={'reference_clock_hz':clk,'CLKS':0,'CD_example':20,'BDIV_example':4,'calculated_baud':clk/(20*(4+1)),'physical_tested':False}
    ck('1Mbps_exact_nominal_divisor_exists',uart_math['calculated_baud']==1000000)
    report={'checks':checks,'all_passed':all(checks.values()),'hdf_ps_parameter_diff':diffs,'bd_ps_parameter_diff':bd_ps_diff,'added_bd_nets':added,'baud_feasibility':uart_math,'new_hdf_sha256':sha(new/'build/vga_system.hdf'),'new_bit_sha256':bbit,'changed_ps_init_files':list(changes),'physical_validation':'NOT PERFORMED'}
    (out/'hardware_verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    for k,v in checks.items():
        if not v:print('FAILED',k)
    print('HDF PS diff',json.dumps(diffs,indent=2))
    print('BD PS diff',json.dumps(bd_ps_diff,indent=2))
    print('Checks',sum(checks.values()),'/',len(checks),'passed')
    print('HDF embedded bit SHA256',bbit)
    if not all(checks.values()):sys.exit(1)
if __name__=='__main__':main()
