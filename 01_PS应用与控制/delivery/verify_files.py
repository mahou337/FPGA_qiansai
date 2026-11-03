"""Read-only complete release verification, including nested paths."""
from pathlib import Path
import hashlib,sys

def verify():
    base=Path(__file__).resolve().parent
    entries={}
    for line in (base/'SHA256SUMS').read_text().splitlines():
        digest,name=line.split('  ',1)
        parts=name.split('/')
        if not name or any(x in ('','.','..') for x in parts) or '\\' in name or ':' in name:
            raise RuntimeError('Bad manifest path')
        if name in entries or len(digest)!=64:raise RuntimeError('Bad manifest entry')
        p=base/name
        if not p.is_file():raise RuntimeError('Missing manifest file: '+name)
        if any(parent.is_symlink() for parent in [p]+list(p.parents) if parent!=base.parent):
            raise RuntimeError('Symlink refused')
        if hashlib.sha256(p.read_bytes()).hexdigest()!=digest:raise RuntimeError('Hash mismatch: '+name)
        entries[name]=digest
    actual=set(p.relative_to(base).as_posix() for p in base.rglob('*') if p.is_file())-{'SHA256SUMS'}
    if actual!=set(entries):raise RuntimeError('Unmanifested or missing files')
    print('FOLLOW_FINAL_FILES_VERIFIED: '+str(len(entries)),flush=True)
    return len(entries)

if __name__=='__main__':
    try:verify()
    except Exception as exc:
        print('FOLLOW_FINAL_VERIFY_REFUSED: '+str(exc),file=sys.stderr);sys.exit(1)
