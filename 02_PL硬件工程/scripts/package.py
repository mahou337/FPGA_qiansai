"""Create an ARM Linux deployment zip from reviewed source modules."""
import hashlib
import json
from pathlib import Path
import zipfile
ROOT=Path(__file__).resolve().parents[1]
manifest=json.loads((ROOT/'config/reference_manifest.json').read_text())
files={}
for name,expected in manifest.items():
    path=ROOT.parent/'gesture_classic'/name
    if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
        raise SystemExit(f'Reference changed: {name}; rerun parity review before packaging')
    files['reference/'+name]=path
for path in (ROOT/'ps').glob('*'):
    if path.suffix in ('.py','.c','.so'): files['ps/'+path.name]=path
for name in ('algorithm.json','ov5640_qvga_rgb565.json','ov5640_vga_rgb565.json','camera_wiring.json','reference_manifest.json','board_reference_provenance.json'):
    files['config/'+name]=ROOT/'config'/name
for path in (ROOT/'linux').iterdir():
    if path.is_file(): files['linux/'+path.name]=path
for path in (ROOT/'docs').glob('*.md'):
    files['docs/'+path.name]=path
files['README.md']=ROOT/'README.md'
# Legacy QVGA helper is optional; VGA uses the kernel driver.
archive=ROOT/'build/gesture_arm_linux.zip'
with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as z:
    for name,path in sorted(files.items()): z.write(path,'gesture_arm_linux/'+name)
    z.writestr('gesture_arm_linux/SHA256SUMS', ''.join(
        f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {n}\n' for n,p in sorted(files.items())))
print(archive)
