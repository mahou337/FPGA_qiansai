from pathlib import Path
import shutil,zipfile,hashlib,json
B=Path('/home/huzhen/hdmi_linux_integration_20261102')
cache=B/'petalinux_project/components/plnx_workspace/device-tree/device-tree'
# Independent copy only: eliminate inherited pre-UART1 generated cache artifacts.
for p in (B/'generated-dt').iterdir():
 if p.is_file():shutil.copyfile(str(p),str(cache/p.name))
with zipfile.ZipFile(str(B/'candidate/system.hdf')) as z:
 for name in z.namelist():
  if name.startswith('ps7_init') or name.endswith('.bit'):
   (cache/name).write_bytes(z.read(name))
shutil.copyfile(str(B/'candidate/system.hdf'),str(cache/'hardware_description.hdf'))
# system-conf is project generated; final custom overrides remain in meta-user.
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
report={p.name:sha(p) for p in cache.iterdir() if p.is_file()}
assert report['hardware_description.hdf']==sha(B/'candidate/system.hdf')
assert report['vga_system.bit']==sha(B/'candidate/system.bit')
(B/'evidence/project_cache_consistency.json').write_text(json.dumps(report,indent=2))
print('Independent project generated hardware cache now matches candidate HDF/bit/PS init')
