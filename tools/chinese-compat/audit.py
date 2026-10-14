#!/usr/bin/env python3
"""Audit supplied PPF3 translations against the collection's patch tables.

Outputs local game data only into the requested report directory.
All addresses in reports are half-open byte ranges.
"""
import argparse
import bisect
import ctypes
import ctypes.util
import hashlib
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'integral-english'))
from m2archive import Archive, Psb
from iso import Disc
import portio


class PPF:
    def __init__(self, path):
        self.path = Path(path)
        data = self.path.read_bytes()
        assert data[:6] == b'PPF30\x02', 'Expected PPF3'
        self.sha256 = hashlib.sha256(data).hexdigest()
        self.records = []
        p = 60 + (1024 if data[57] else 0)
        while p < len(data):
            assert p + 9 <= len(data), ('PPF trailing data', p)
            offset, size = struct.unpack_from('<QB', data, p)
            p += 9
            assert size and p + size * (2 if data[58] else 1) <= len(data)
            self.records.append((offset, data[p:p+size]))
            p += size * (2 if data[58] else 1)
        # Last record wins, including overlaps.
        self.bytes = {}
        for offset, payload in self.records:
            self.bytes.update((offset+i, b) for i, b in enumerate(payload))
        self.addresses = sorted(self.bytes)

    def range(self, start, end):
        a = bisect.bisect_left(self.addresses, start)
        b = bisect.bisect_left(self.addresses, end)
        return self.addresses[a:b]

    def logical(self, original, lba):
        out = bytearray(original)
        for offset in self.range(lba*2352, (lba+(len(out)+2047)//2048)*2352):
            sector, pos = divmod(offset, 2352)
            i = (sector-lba)*2048+pos-24
            if 24 <= pos < 2072 and 0 <= i < len(out):
                out[i] = self.bytes[offset]
        return bytes(out)


def runs(addresses):
    result = []
    for address in sorted(set(addresses)):
        if result and result[-1][1] == address:
            result[-1][1] += 1
        else:
            result.append([address, address+1])
    return result


def initial_ram(blob):
    p = blob.find(b'lz4a', 4)+4
    packed, unpacked, n = struct.unpack_from('<IIB', blob, p)
    assert blob[p+9:p+9+n] == b'ram.le32.bin'
    p += 9+n
    lib = ctypes.CDLL(ctypes.util.find_library('lz4'))
    fn = lib.LZ4_decompress_safe
    fn.argtypes = [ctypes.c_char_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    out = ctypes.create_string_buffer(unpacked)
    assert fn(blob[p:p+packed], out, packed, unpacked) == unpacked
    return out.raw


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--game', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    archives = [Archive(str(p)) for p in [args.game/'windata/alldata.bin', *sorted((args.game/'windata/dlc').glob('*.bin'))] if p.with_suffix('.psb.m').exists()]
    def arc(member):
        return next(a for a in archives if member in a.files)
    def extract(member):
        return arc(member).extract(member)
    def config(member):
        return Psb(extract(member)).root()
    profile = config('099/config/title_prof.psb.m')['root']['m2epi']['version']
    table = config('099/config/title_patchdata.psb.m')
    out = {'schema': 1, 'range_convention': '[start,end)', 'discs': []}
    for version, disk, base, length in [('INTEGRAL',0,0x131D2238,0x9c000),('INTEGRAL',1,0x0eb38078,0x9c000),('VR-DISK',0,0x865f8,0x99800)]:
        matches = list((args.game/'mods').glob(f'*/{version}/'+(f'{disk}/' if version=='INTEGRAL' else '')+'*.ppf'))
        assert len(matches)==1, matches
        ppf = PPF(matches[0])
        cfg = profile[version]
        diskname = cfg['disk'][disk] if isinstance(cfg['disk'], list) else cfg['disk']
        member = 'system/'+diskname
        archive = arc(member)
        disc = Disc(archive.path, archive.files[member][0])
        files = [(name,lba,size) for name,lba,size,isdir in disc.walk() if not isdir]
        ram_member = 'system/'+cfg['rom']
        ram = initial_ram(arc(ram_member).read(ram_member))
        ram_cn = bytearray(ram)
        ram_bytes = {}
        for address in ppf.range(base,base+length//2048*2352):
            sector,pos = divmod(address-base,2352)
            if pos < 2048 and sector*2048+pos < length:
                addr = 0x10000+sector*2048+pos
                ram_cn[addr] = ppf.bytes[address]
                ram_bytes[addr] = ppf.bytes[address]
        report = {'version':version,'disk':disk,'ppf':str(ppf.path),'sha256':ppf.sha256,'records':len(ppf.records),'ram_changed_ranges':runs(a for a,b in ram_bytes.items() if ram[a]!=b),'patches':[],'files':[]}
        (args.out/f'{version}-{disk}-ram-original.bin').write_bytes(ram)
        (args.out/f'{version}-{disk}-ram-cn.bin').write_bytes(ram_cn)
        for index,patch in enumerate(table[version]['patchs']):
            isram = 'memory' in patch
            if not isram and patch.get('disc',0)!=disk: continue
            names = [patch.get('file')]
            if names[0] and not names[0].endswith('.bin'):
                names = sorted(n.removeprefix('099/patch/').removesuffix('.m') for n in arc('099/config/title_patchdata.psb.m').files if n.startswith('099/patch/'+names[0]+'_') and n.endswith('.bin.m'))
            for filename in names:
                payload = bytes(patch['data']) if 'data' in patch else extract('099/patch/'+filename+'.m')
                offset = patch['offset']
                covered = [a for a in (ram_bytes if isram else ppf.range(offset,offset+len(payload))) if offset<=a<offset+len(payload)]
                conflicting = [a for a in covered if (ram_bytes[a] if isram else ppf.bytes[a])!=payload[a-offset]]
                row = {'index':index,'kind':'ram' if isram else 'cd','file':filename,'offset':offset,'end':offset+len(payload),'length':len(payload),'overlap_ranges':runs(covered),'conflict_ranges':runs(conflicting),'action':'partial' if conflicting and len(conflicting)<len(payload) else 'disable' if conflicting else 'keep','payload_sha256':hashlib.sha256(payload).hexdigest(),'conflict_values':[]}
                for start,end in runs(conflicting):
                    if isram:
                        original = ram[start:end] if end<=len(ram) else b''
                        chinese = bytes(ram_bytes[a] for a in range(start,end))
                    else:
                        disc.f.seek(disc.base+start)
                        original = disc.f.read(end-start)
                        chinese = bytes(ppf.bytes[a] for a in range(start,end))
                    row['conflict_values'].append({'start':start,'end':end,'original_hex':original.hex(),'official_hex':payload[start-offset:end-offset].hex(),'chinese_hex':chinese.hex()})
                report['patches'].append(row)
        for name,lba,size in files:
            addresses = ppf.range(lba*2352,(lba+(size+2047)//2048)*2352)
            if not addresses: continue
            original = disc.read(lba,size)
            chinese = ppf.logical(original,lba)
            changed = [i for i,(a,b) in enumerate(zip(original,chinese)) if a!=b]
            entry = {'name':name,'lba':lba,'size':size,'ppf_bytes':len(addresses),'changed_bytes':len(changed),'logical_changed_ranges':runs(changed)}
            report['files'].append(entry)
            if any(key in name.upper() for key in ['STAGE.DIR','RADIO.DAT']):
                clean = name.strip('/').replace('/','_').replace(';','_')
                (args.out/f'{version}-{disk}-{clean}-original.bin').write_bytes(original)
                (args.out/f'{version}-{disk}-{clean}-cn.bin').write_bytes(chinese)
        out['discs'].append(report)
        print(version,disk,'records',len(ppf.records),'patch variants',len(report['patches']),'conflicting',sum(bool(p['conflict_ranges']) for p in report['patches']), 'files',len(report['files']),flush=True)
    (args.out/'byte-conflicts.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
