"""Build a stage-two development handoff, not a deployable application."""
import ast
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[2]
PROJECT=ROOT/'zynq_gesture'
RETURNED=PROJECT/'deliverables/received_linux_stage1_20261030/delivery'
NAME='linux_stage2_handoff_20261030'
STAGE=PROJECT/'build/stage2_package_build'/datetime.now().strftime('%Y%m%d_%H%M%S_%f')/NAME
PROVENANCE={}

def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def copy(source,relative):
    source=Path(source)
    target=STAGE/relative
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(source,target)
    PROVENANCE[Path(relative).as_posix()]={'source':source.relative_to(ROOT).as_posix(),'sha256':digest(source)}

def tree(source,relative):
    source=Path(source)
    for f in sorted(source.rglob('*')):
        if f.is_file() and '__pycache__' not in f.parts and f.suffix not in ('.pyc','.pyo'):
            copy(f,Path(relative)/f.relative_to(source))

def text(relative,content):
    target=STAGE/relative
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(content,encoding='utf-8',newline='\n')

def main():
    STAGE.mkdir(parents=True,exist_ok=False)
    docs=PROJECT/'docs/stage2_handoff'
    for name in ('README_先读我.md','LINUX_CODEX_PROMPT.md'): copy(docs/name,name)
    for name in ('PHOTO_REVIEW.md','ACCEPTANCE.md'): copy(docs/name,'docs/'+name)
    for name in ('UART_PROTOCOL.md','DEPLOY_LINUX.md','ARCHITECTURE.md'):
        copy(PROJECT/'docs'/name,'docs/reference_'+name)
    copy(PROJECT/'docs/UART_PROTOCOL.md','docs/UART_PROTOCOL.md')
    tree(ROOT/'run-d5d7ca2a5b784049be1bf39a964ebed5','samples/run-d5d7ca2a5b784049be1bf39a964ebed5')
    tree(PROJECT/'build/stage2_handoff_review','review')
    copy(PROJECT/'scripts/review_stage2_samples.py','tools/review_stage2_samples.py')
    copy(Path(__file__),'tools/package_linux_stage2_handoff.py')
    text('tools/README.md','# Tools\n\nverify_package.py runs on Python3.5+ from the package root.\nreview_stage2_samples.py is DESKTOP ONLY; --workspace points to reference_desktop, --samples to the sample directory, --output to a NEW directory outside this checksum-protected bundle. Requires the original modern Python/OpenCV environment.\npackage_linux_stage2_handoff.py records the original Windows packaging recipe; it is not a Linux installer and expects the original workspace layout.\n')
    classic=ROOT/'gesture_classic'
    for f in sorted(classic.iterdir()):
        if f.is_file() and f.suffix in ('.py','.md','.json','.txt'):
            copy(f,Path('reference_desktop/gesture_classic')/f.name)
    tree(classic/'tests','reference_desktop/gesture_classic/tests')
    historical=sorted((classic/'archive').glob('pre_finger_*'))[-1]
    copy(historical/'skin_detection.py',Path('reference_desktop/gesture_classic/archive')/historical.name/'skin_detection.py')
    images=sorted((classic/'results').glob('*/original.png'))
    selected=images[::max(1,len(images)//24)][:24]
    if not selected: raise RuntimeError('Missing parity fixtures')
    for f in selected: copy(f,Path('reference_desktop/gesture_classic/results')/f.parent.name/f.name)
    tree(PROJECT/'ps','reference_desktop/zynq_gesture/ps')
    tree(PROJECT/'tests','reference_desktop/zynq_gesture/tests')
    for name in ('algorithm.json','reference_manifest.json','ov5640_qvga_rgb565.json','ov5640_vga_rgb565.json'):
        copy(PROJECT/'config'/name,Path('reference_desktop/zynq_gesture/config')/name)
    tree(RETURNED/'source','stage1_baseline/source')
    for name in ('README_先读我.md','STATUS.json'): copy(RETURNED/name,Path('stage1_baseline')/name)
    for name in ('操作说明.md','实现与验证.md','上板验证_现在就做.md'):
        copy(RETURNED/'docs'/name,Path('stage1_baseline/docs')/name)
    for name in ('run_camera_test.sh','gesture-camera.init'):
        copy(RETURNED/'scripts'/name,Path('stage1_baseline/scripts')/name)
    for name in ('OFFLINE_VERIFICATION.json','system.decompiled.dts','modules/gesture_vga.ko','boot-inputs/system.dtb'):
        copy(RETURNED/'artifacts'/name,Path('stage1_baseline/artifacts')/name)
    tree(RETURNED/'hardware','hardware')
    expected={'system.hdf':'1ca63e2794e0e02a26dd5351a3917fbeedc5623fbd18188f4a8a03ac39903042','system.bit':'47a9ff8681c5c43ab23e362c4d318db78021dc2fc9f5716acb1fe695f566b02d'}
    for name,sha in expected.items():
        if digest(STAGE/'hardware'/name)!=sha: raise RuntimeError('Hardware mismatch '+name)
    boot={f.name:{'sha256':digest(f),'bytes':f.stat().st_size} for f in sorted((RETURNED/'artifacts/boot').iterdir()) if f.is_file()}
    text('stage1_baseline/BOOT_FILES_IDENTITY.json',json.dumps(boot,indent=2)+'\n')
    text('stage1_baseline/README_VERSION_PRIORITY.md',"# Verified camera baseline\n\nUser reports first-board acceptance passed; samples contain the subsequent physical run. Original STATUS.json describes the earlier delivery time.\n\nThis backend/driver/UAPI overrides old hardware.py/hardware_vga.py in reference_desktop. The module is reference-only for the original kernel; do not overwrite the working module by default. BOOT_FILES_IDENTITY.json identifies the returned release inputs; boot binaries/rootfs/SD image are not duplicated here. Keep the Linux colleague's working system.\n")
    tree(PROJECT/'ps','migration_seed/ps')
    for name in ('hardware.py','hardware_vga.py','camera_probe.py'):
        copy(RETURNED/'source/ps'/name,Path('migration_seed/ps')/name)
    for f in sorted(classic.glob('*.py')): copy(f,Path('migration_seed/reference')/f.name)
    copy(classic/'config.json','migration_seed/reference/config.json')
    copy(PROJECT/'config/algorithm.json','migration_seed/config/algorithm.json')
    copy(RETURNED/'source/config/ov5640_vga_rgb565.json','migration_seed/config/ov5640_vga_rgb565.json')
    text('migration_seed/README_NOT_READY.md','# 尚未适配的迁移种子\n\n不能直接上板。按提示词复制到独立工作目录再修改。ps/hardware.py、hardware_vga.py、camera_probe.py来自已验证第一阶段；其他识别代码是原始新版Python实现。reference.py从相邻reference目录加载算法。config/algorithm.json尚未针对本次实拍标定。不得把含手照片作为空背景。\n')
    inventory=[]
    for f in sorted((STAGE/'migration_seed').rglob('*.py')):
        code=f.read_text(encoding='utf-8-sig')
        syntax=ast.parse(code)
        row={'file':f.relative_to(STAGE).as_posix(),'f_string_nodes':sum(isinstance(n,ast.JoinedStr) for n in ast.walk(syntax)),'annotated_assignments':sum(isinstance(n,ast.AnnAssign) for n in ast.walk(syntax)),'dataclasses_imported':'from dataclasses import' in code,'findContours_lines':[i+1 for i,l in enumerate(code.splitlines()) if 'findContours' in l]}
        try:
            ast.parse(code,feature_version=(3,5))
            row['modern_parser_python35_syntax']='accepted; runtime NOT verified'
        except SyntaxError as exc:
            row['modern_parser_python35_syntax']={'line':exc.lineno,'message':exc.msg}
        inventory.append(row)
    text('review/compatibility_inventory.json',json.dumps(inventory,ensure_ascii=False,indent=2)+'\n')
    text('tools/verify_package.py','''"""Read-only package integrity check for Python 3.5+."""
import hashlib
from pathlib import Path
import sys

def main():
    root=Path(sys.argv[1] if len(sys.argv)>1 else '.').resolve()
    failures=[]
    count=0
    for line in (root/'SHA256SUMS').read_text(encoding='utf-8').splitlines():
        expected,relative=line.split('  ',1)
        target=(root/relative).resolve()
        if root not in target.parents:
            failures.append(relative+': invalid path')
            continue
        if not target.is_file():
            failures.append(relative+': missing')
            continue
        actual=hashlib.sha256(target.read_bytes()).hexdigest()
        if actual!=expected: failures.append(relative+': checksum mismatch')
        count+=1
    for item in failures: print(item)
    print('Checked {0} files; failures={1}'.format(count,len(failures)))
    return 1 if failures else 0

if __name__=='__main__': sys.exit(main())
''')
    text('PACKAGE_STATUS.json',json.dumps({'date':'2026-10-30','purpose':'stage2_development_input_not_deployable_application','stage1_user_reports_board_pass':True,'stage1_physical_evidence_directory':'samples/run-d5d7ca2a5b784049be1bf39a964ebed5','desktop_algorithm_tests':{'total':100,'passed':100},'desktop_ps_tests':{'total':20,'passed':20},'desktop_real_replay':{'orientations':[0,180],'frames_per_orientation':3,'all_status':'NEED CALIBRATION','all_code':'????'},'python35_migration_complete':False,'arm_stage2_execution_verified':False,'stage2_board_verified':False,'hardware_sha256':expected,'desktop_parity_fixture_count':len(selected)},ensure_ascii=False,indent=2)+'\n')
    text('SOURCE_PROVENANCE.json',json.dumps(PROVENANCE,ensure_ascii=False,indent=2)+'\n')
    members=sorted(f for f in STAGE.rglob('*') if f.is_file())
    text('SHA256SUMS',''.join(digest(f)+'  '+f.relative_to(STAGE).as_posix()+'\n' for f in members))
    archive=PROJECT/'deliverables'/(NAME+'.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for f in sorted(STAGE.rglob('*')):
            if f.is_file(): z.write(f,NAME+'/'+f.relative_to(STAGE).as_posix())
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None: raise RuntimeError('ZIP CRC failure')
        for line in (STAGE/'SHA256SUMS').read_text(encoding='utf-8').splitlines():
            sha,rel=line.split('  ',1)
            if hashlib.sha256(z.read(NAME+'/'+rel)).hexdigest()!=sha: raise RuntimeError('ZIP SHA mismatch '+rel)
    sha=digest(archive)
    archive.with_suffix('.zip.sha256').write_text(sha+'  '+archive.name+'\n',encoding='ascii')
    build={'package':str(archive),'staging':str(STAGE),'sha256':sha,'bytes':archive.stat().st_size,'manifest_files':len(members),'zip_crc_and_manifest_verified':True}
    (PROJECT/'build/stage2_package_latest.json').write_text(json.dumps(build,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(build,ensure_ascii=False,indent=2))

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
