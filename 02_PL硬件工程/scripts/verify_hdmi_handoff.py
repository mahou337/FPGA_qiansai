"""Read-only baseline comparison, writes its JSON report only to output directory.
Usage: python verify_hdmi_handoff.py UART1_BASE HDMI_PROJECT OUT [BASELINE_SNAPSHOT]
"""
import sys,json,hashlib,re,copy
from pathlib import Path
from verify_handoff import load_bd,load_hdf,sha

def main():
 base,new,out=map(Path,sys.argv[1:4]);out.mkdir(parents=True,exist_ok=True)
 checks={}
 def ck(k,v):checks[k]=bool(v)
 ck('baseline_hdf',sha(base/'build/vga_system.hdf')=='228e381e701fffbbf5ac3a9f571be6fb56f14140aada26a51e0add847c66db3d')
 ck('baseline_bit',sha(base/'build/vga_system.bit')=='71058d214479da36e67f7dca30fc2250d75b83208e3fe66f3f1f1433edf8670b')
 if len(sys.argv)>4:
  snapshot=json.loads(Path(sys.argv[4]).read_text())
  differences=[rel for rel,h in snapshot.items() if not (base/rel).is_file() or sha(base/rel)!=h]
  added=sorted(set(f.relative_to(base).as_posix() for f in base.rglob('*') if f.is_file())-set(snapshot))
  ck('original_all_files_unchanged',not differences);ck('original_no_added_files',not added)
 for folder in ['pl','config']:
  for f in (base/folder).rglob('*'):
   if f.is_file():
    rel=f.relative_to(base);ck('original_source:'+rel.as_posix(),(new/rel).is_file() and sha(f)==sha(new/rel))
 a,b=load_bd(base),load_bd(new)
 ck('BD_interface_ports',a['interface_ports']==b['interface_ports'])
 ck('BD_existing_ports',all(b['ports'].get(k)==v for k,v in a['ports'].items()))
 added_ports={'hdmi_clk_p','hdmi_clk_n','hdmi_data_p','hdmi_data_n'}
 ck('BD_only_HDMI_ports',set(b['ports'])-set(a['ports'])==added_ports)
 ck('BD_only_display_components',set(b['components'])-set(a['components'])=={'mask_display','display_clock','hdmi_encoder'})
 for k,v in a['components'].items():
  if k!='axi':ck('BD_component:'+k,b['components'][k]==v)
 oldaxi=a['components']['axi'];newaxi=copy.deepcopy(b['components']['axi'])
 ck('AXI_NUM_MI_3',newaxi['parameters']['NUM_MI']=={'value':'3'})
 newaxi['parameters']['NUM_MI']={'value':'2'}
 del newaxi['interface_ports']['M02_AXI']
 for k in ['M02_ACLK','M02_ARESETN']:del newaxi['ports'][k]
 m02=copy.deepcopy(newaxi['components']['m02_couplers'])
 m02['interface_nets']['m01_couplers_to_m01_couplers']=m02['interface_nets'].pop('m02_couplers_to_m02_couplers')
 ck('AXI_M02_coupler',m02==oldaxi['components']['m01_couplers'])
 del newaxi['components']['m02_couplers']
 ck('AXI_xbar_NUM_MI_3',newaxi['components']['xbar']['parameters']['NUM_MI']=={'value':'3'})
 newaxi['components']['xbar']['parameters']['NUM_MI']={'value':'2'}
 for k in ['m02_couplers_to_axi','xbar_to_m02_couplers']:del newaxi['interface_nets'][k]
 for k in ['axi_ACLK_net','axi_ARESETN_net']:
  newaxi['nets'][k]['ports']=[v for v in newaxi['nets'][k]['ports'] if not v.startswith('m02_couplers/')]
 ck('AXI_only_extra_master',oldaxi==newaxi)
 for k in ['hdmi_clk_p','hdmi_clk_n']:
  ck('BD_forwarded_clock_metadata:'+k,b['ports'][k]['parameters']['FREQ_HZ']['value']=='25200000')
 ck('BD_existing_interface_nets',all(b['interface_nets'].get(k)==v for k,v in a['interface_nets'].items()))
 ck('BD_only_extra_AXI_connection',set(b['interface_nets'])-set(a['interface_nets'])=={'axi_M02_AXI'})
 ck('BD_new_AXI_target',set(b['interface_nets']['axi_M02_AXI']['interface_ports'])=={'axi/M02_AXI','mask_display/s_axi'})
 net_add={
  'ps7_FCLK_CLK0':{'axi/M02_ACLK','mask_display/s_axi_aclk','display_clock/clk_in1'},
  'reset_interconnect_aresetn':{'axi/M02_ARESETN'},
  'reset_peripheral_aresetn':{'mask_display/s_axi_aresetn','display_clock/resetn'}}
 for k,v in a['nets'].items():
  ck('BD_net:'+k,set(b['nets'][k]['ports'])==set(v['ports'])|net_add.get(k,set()))
 addresses=copy.deepcopy(b['addressing'])
 newseg=addresses['/ps7']['address_spaces']['Data']['segments'].pop('SEG_mask_display_reg0')
 ck('BD_existing_addresses',addresses==a['addressing'])
 ck('BD_display_address',newseg=={'address_block':'/mask_display/s_axi/reg0','offset':'0x43C00000','range':'512K'})
 ah,ap,ae,ab,ai=load_hdf(base/'build/vga_system.hdf');bh,bp,be,bb,bi=load_hdf(new/'build/vga_system.hdf')
 ck('baseline_embedded_bit',ab==sha(base/'build/vga_system.bit'))
 ck('HDMI_embedded_bit',bb==sha(new/'build/vga_system.bit'))
 ck('HDF_all_PS_parameters_identical',ap['ps7']==bp['ps7'])
 for k in ai:ck('HDF_PS_init_byte_identical:'+k,ai[k]==bi.get(k))
 for k in ap:
  if k!='axi':ck('HDF_params:'+k,ap[k]==bp[k])
 ck('HDF_existing_external_ports',all(be.get(k)==v for k,v in ae.items()))
 ck('HDF_only_HDMI_external_ports',set(be)-set(ae)==added_ports)
 for port,pin in [('uart_tx','UART0_TX'),('uart_rx','UART0_RX'),('uart1_tx','UART1_TX'),('uart1_rx','UART1_RX')]:
  e=bh.find("./EXTERNALPORTS/PORT[@NAME='%s']"%port)
  ck('HDF_UART_connection:'+port,e is not None and any(c.get('INSTANCE')=='ps7' and c.get('PORT')==pin for c in e.findall('./CONNECTIONS/CONNECTION')))
 for port,pin in [('hdmi_clk_p','TMDS_Clk_p'),('hdmi_clk_n','TMDS_Clk_n'),('hdmi_data_p','TMDS_Data_p'),('hdmi_data_n','TMDS_Data_n')]:
  e=bh.find("./EXTERNALPORTS/PORT[@NAME='%s']"%port)
  ck('HDF_HDMI_connection:'+port,e is not None and any(c.get('INSTANCE')=='hdmi_encoder' and c.get('PORT')==pin for c in e.findall('./CONNECTIONS/CONNECTION')))
 report={'checks':checks,'all_passed':all(checks.values()),'original_changed_files':differences if len(sys.argv)>4 else None,
  'new_hdf_sha256':sha(new/'build/vga_system.hdf'),'new_bit_sha256':bb,
  'existing_PS_parameter_changes':{},'new_display_address':newseg,'physical_validation':'NOT PERFORMED',
  'limits':'Structural offline equivalence only, not camera/UART/performance or sink validation.'}
 (out/'hdmi_hardware_verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
 for k,v in checks.items():
  if not v:print('FAILED',k)
 print('Checks %d/%d passed'%(sum(checks.values()),len(checks)))
 if not all(checks.values()):sys.exit(1)
if __name__=='__main__':main()
