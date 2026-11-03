"""Verify generated PS settings and DDR initialization against the reference."""
import argparse
import hashlib
import json
import re
from pathlib import Path
from import_board_reference import ROOT, WORKSPACE, read_parameters

def ddr_arrays(path):
    text = path.read_text()
    text = re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S)
    return {name: re.sub(r'\s+', '', body) for name,body in re.findall(
        r'unsigned long (ps7_ddr_init_data_\d_\d)\[\]\s*=\s*\{(.*?)\};', text, re.S)}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--vga",action="store_true")
    args=parser.parse_args()
    manifest = json.loads((ROOT/'config/board_reference_provenance.json').read_text())
    for info in manifest['source_files'].values():
        assert hashlib.sha256((WORKSPACE/info['path']).read_bytes()).hexdigest() == info['sha256']
    generated = ROOT/('build/vivado_vga/gesture_vga.srcs/sources_1/bd/system/ip/system_ps7_0' if args.vga else 'build/vivado/gesture_zynq.srcs/sources_1/bd/system/ip/system_ps7_0')
    actual = read_parameters(generated/'system_ps7_0.xci')
    expected = dict(manifest['imported_settings'])
    expected.update(PCW_FPGA0_PERIPHERAL_FREQMHZ='50', PCW_USE_M_AXI_GP0='1',
        PCW_UART0_PERIPHERAL_ENABLE='1', PCW_UART0_UART0_IO='EMIO',
        PCW_UART1_PERIPHERAL_ENABLE='0', PCW_ENET0_PERIPHERAL_ENABLE='0',
        PCW_SD0_PERIPHERAL_ENABLE='1', PCW_SD0_SD0_IO='MIO 40 .. 45',
        PCW_SD0_GRP_CD_ENABLE='1', PCW_SD0_GRP_CD_IO='MIO 47',
        PCW_DDR_RAM_HIGHADDR='0x1FFFFFFF')
    if args.vga: expected.update(PCW_USE_S_AXI_HP0='1', PCW_S_AXI_HP0_DATA_WIDTH='64')
    differences = {k:{'expected':v,'actual':actual.get(k)} for k,v in expected.items() if actual.get(k)!=v}
    assert not differences, differences
    ref = WORKSPACE/'15_PS_BRAM_TEST/PS_BRAM_TEST/PS_BRAM_TEST.sdk/TOP_MODULE_hw_platform_0/ps7_init.c'
    reference = ddr_arrays(ref)
    produced = ddr_arrays(generated/'ps7_init.c')
    assert len(reference) == 3 and reference == produced, 'DDR register sequences changed'
    result = {'settings_checked':len(expected), 'imported_settings_checked':len(manifest['imported_settings']),
        'source_hashes_match':True,'ddr_arrays_equal':list(sorted(reference)),
        'reference_init_path':str(ref.relative_to(WORKSPACE)),
        'reference_init_sha256':hashlib.sha256(ref.read_bytes()).hexdigest(),
        'generated_init_sha256':hashlib.sha256((generated/'ps7_init.c').read_bytes()).hexdigest(),
        'physical_validation':False}
    (ROOT/('build/vga_board_reference_validation.json' if args.vga else 'build/board_reference_validation.json')).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
if __name__ == '__main__': main()
