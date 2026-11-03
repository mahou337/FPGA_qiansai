"""Inspect the supplied U-Boot FIT without modifying source images.
Extract embedded payloads and inventory newc initramfs; never extract symlinks.
"""
from pathlib import Path
import argparse, gzip, hashlib, json, re, struct, zlib

class Fdt:
    def __init__(self, blob):
        self.blob = blob
        h = struct.unpack_from('>10I', blob)
        magic, total, st, strings, reserve, version, compatible, cpu, ns, nt = h
        if magic != 0xd00dfeed or total > len(blob) or version < 16:
            raise ValueError('Invalid FDT header')
        self.total = total
        self.nodes = {}
        stack = []
        pos = st
        while pos < st + nt:
            token, = struct.unpack_from('>I', blob, pos); pos += 4
            if token == 1:
                end = blob.index(b'\0', pos)
                name = blob[pos:end].decode()
                stack.append(name)
                path = '/' + '/'.join(stack[1:])
                self.nodes[path] = {}
                pos = (end + 4) & ~3
            elif token == 2:
                stack.pop()
            elif token == 3:
                size, off = struct.unpack_from('>II', blob, pos); pos += 8
                if off >= ns or pos + size > st + nt:
                    raise ValueError('Invalid FDT property bounds')
                end = blob.index(b'\0', strings + off)
                name = blob[strings + off:end].decode()
                self.nodes['/' + '/'.join(stack[1:])][name] = blob[pos:pos+size]
                pos = (pos + size + 3) & ~3
            elif token == 4:
                pass
            elif token == 9:
                break
            else:
                raise ValueError(f'Invalid FDT token {token}')
        self.reservations = blob[reserve:st]
        self.cpu = cpu

    def encode(self):
        names = {}
        strings = bytearray()
        for props in self.nodes.values():
            for key in props:
                if key not in names:
                    names[key] = len(strings); strings += key.encode() + b'\0'
        tree = bytearray()
        def word(n): tree.extend(struct.pack('>I', n))
        def padded(b):
            tree.extend(b); tree.extend(b'\0' * (-len(tree) % 4))
        def emit(path):
            word(1); padded((path.rsplit('/',1)[-1] if path != '/' else '').encode() + b'\0')
            for key, value in self.nodes[path].items():
                word(3); word(len(value)); word(names[key]); padded(value)
            for child in self.nodes:
                if child != '/' and (child.rsplit('/',1)[0] or '/') == path:
                    emit(child)
            word(2)
        emit('/'); word(9)
        reserve = self.reservations or b'\0' * 16
        st = 40 + len(reserve)
        ss = st + len(tree)
        header = struct.pack('>10I', 0xd00dfeed, ss+len(strings), st, ss, 40, 17, 16, self.cpu, len(strings), len(tree))
        return header + reserve + tree + strings

    def readable(self):
        def value(b):
            if b and b[0] != 0 and b[-1] == 0 and all(x == 0 or 32 <= x < 127 for x in b):
                return b.rstrip(b'\0').decode().split('\0')
            if len(b) % 4 == 0: return ['0x%08x' % n for n in struct.unpack('>%dI' % (len(b)//4), b)]
            return b.hex()
        return {path: {key: value(data) for key, data in props.items() if key != 'data'} for path,props in self.nodes.items()}


def newc(blob):
    pos = 0
    while pos + 110 <= len(blob):
        h = blob[pos:pos+110]
        if h[:6] not in (b'070701', b'070702'): raise ValueError(f'Unsupported cpio at {pos}')
        fields = [int(h[6+i*8:14+i*8],16) for i in range(13)]
        mode, size, namesize = fields[1], fields[6], fields[11]
        start = pos+110
        name = blob[start:start+namesize-1].decode('utf-8', 'replace')
        data = (start+namesize+3)&~3
        if data+size > len(blob): raise ValueError('Truncated cpio')
        if name == 'TRAILER!!!': return
        yield name, mode, blob[data:data+size]
        pos = (data+size+3)&~3


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('directory'); ap.add_argument('--output', required=True)
    args=ap.parse_args(); source=Path(args.directory); out=Path(args.output); out.mkdir(parents=True,exist_ok=True)
    image=(source/'image.ub').read_bytes(); fit=Fdt(image)
    assert Fdt(fit.encode()).nodes == fit.nodes
    report={'source':str(source.resolve()),'files':{},'fit':fit.readable(),'payloads':{},'rootfs':{}}
    for name in ('BOOT.BIN','image.ub'):
        b=(source/name).read_bytes(); report['files'][name]={'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
    for path,props in fit.nodes.items():
        if not path.startswith('/images/') or 'data' not in props: continue
        data=props['data']; name=path.rsplit('/',1)[-1]
        typ=props.get('type',b'').rstrip(b'\0').decode()
        filename={'kernel':'kernel.bin','flat_dt':'system-original.dtb','ramdisk':'rootfs.cpio.gz'}.get(typ,name+'.bin')
        (out/filename).write_bytes(data)
        hashes=[]
        for child,cp in fit.nodes.items():
            if child.rsplit('/',1)[0] == path and 'algo' in cp:
                algo=cp['algo'].rstrip(b'\0').decode()
                digest=struct.pack('>I',zlib.crc32(data)&0xffffffff) if algo=='crc32' else hashlib.new(algo,data).digest()
                if digest != cp['value']: raise ValueError(f'FIT hash mismatch {child}')
                hashes.append(algo)
        report['payloads'][name]={'type':typ,'file':filename,'bytes':len(data),'verified_hashes':hashes}
        if typ == 'flat_dt':
            dt=Fdt(data); assert Fdt(dt.encode()).nodes==dt.nodes
            (out/'device-tree-original.json').write_text(json.dumps(dt.readable(),indent=2)+'\n')
        elif typ == 'kernel':
            raw=None
            for m in re.finditer(b'\x1f\x8b\x08',data):
                try: raw=zlib.decompress(data[m.start():],31); break
                except zlib.error: pass
            if raw:
                (out/'kernel-uncompressed.bin').write_bytes(raw)
                match=re.search(rb'Linux version [^\x00\n]+',raw)
                report['kernel_version']=match.group().decode(errors='replace') if match else 'not found'
                marker=raw.find(b'IKCFG_ST')
                if marker>=0:
                    config=zlib.decompress(raw[marker+8:],31)
                    (out/'kernel.config').write_bytes(config)
        elif typ == 'ramdisk':
            raw=gzip.decompress(data) if data[:2]==b'\x1f\x8b' else data
            inventory=[]; candidates=[]; versions=[]
            for fname,mode,content in newc(raw):
                inventory.append({'path':fname,'mode':oct(mode),'bytes':len(content)})
                if re.search(r'(python|numpy|opencv|cv2|/modules/|/build/)',fname,re.I): candidates.append(fname)
                if fname.lstrip('./') in ('etc/os-release','etc/inittab','etc/issue','init'):
                    (out/(fname.replace('/','_').lstrip('.'))).write_bytes(content)
                if fname.endswith('.ko'):
                    m=re.search(rb'vermagic=([^\x00]+)',content)
                    if m: versions.append(m.group(1).decode(errors='replace'))
            report['rootfs']={'entries':len(inventory),'runtime_candidates':candidates,'module_vermagic':sorted(set(versions))}
            (out/'rootfs-inventory.json').write_text(json.dumps(inventory,indent=2)+'\n')
    (out/'inspection.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k != 'fit'},indent=2))

if __name__=='__main__': main()
