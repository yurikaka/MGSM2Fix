#!/usr/bin/env python3
"""Structurally inventory translated stage textures and font banks."""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'integral-english'))
import portio
import radiomap


def dar(data):
    p = 0
    while p+8 <= len(data):
        tid, ext, size = struct.unpack_from('<HhI',data,p)
        if size<=0 or p+8+size>len(data):
            return
        yield tid,ext,p+8,data[p+8:p+8+size]
        p += 8+size


def cache(tags, payloads, offsets):
    rows=[t for t in tags if t[1]==ord('c')]
    if not rows: return
    k=next(k for k,t in enumerate(tags) if t[1]==ord('c') and t[2]==255)
    files=[t for t in rows if t[2]!=255]
    for i,(tid,mode,ext,start) in enumerate(files):
        end=files[i+1][3] if i+1<len(files) else len(payloads[k])
        yield tid,ext,offsets[k]+start,payloads[k][start:end]


def assets(data):
    for name,(sector,_) in portio.entries(data).items():
        tags,payloads,offsets=portio.stage(data,name)
        for k,blob in payloads.items():
            if tags[k][1] in (ord('r'),ord('n')) and tags[k][2]==ord('d'):
                for tid,ext,off,asset in dar(blob):
                    yield name,tid,ext,sector*2048+offsets[k]+off,asset
        for tid,ext,off,asset in cache(tags,payloads,offsets):
            yield name,tid,ext,sector*2048+off,asset


def fonts(tid,ext,data):
    if tid==0xca68 and ext==ord('r'):
        start=struct.unpack_from('>I',data,4)[0]
        yield 'font.res',start,data[start:start+(len(data)-start)//36*36]
    if ext==ord('g') and len(data)>12:
        script=4+struct.unpack_from('>I',data)[0]
        if script+4>len(data): return
        end=script+4+struct.unpack_from('>I',data,script)[0]
        if end+4>len(data): return
        size=struct.unpack_from('>I',data,end)[0]
        if size and size%36==0 and end+4+size<=len(data):
            yield 'gcx',end+4,data[end+4:end+4+size]


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--audit',type=Path,required=True)
    ap.add_argument('--official',type=Path,required=True)
    args=ap.parse_args()
    fontall=(args.official/'system/patch/fontall.bin').read_bytes()
    known={fontall[i:i+36]:i//36 for i in range(0,len(fontall),36)}
    result={'textures':[],'fonts':[],'failures':[]}
    glyphs=collections.defaultdict(list)
    saved=args.audit/'textures';saved.mkdir(exist_ok=True)
    for path in sorted(args.audit.glob('*STAGE*cn.bin')):
        prefix=path.name.split('-MGS_')[0]
        original=path.with_name(path.name.replace('-cn.bin','-original.bin')).read_bytes()
        translated=path.read_bytes()
        originals={(name,tid,ext):(off,blob) for name,tid,ext,off,blob in assets(original)}
        for stage,tid,ext,off,blob in assets(translated):
            oldoff,old=originals.get((stage,tid,ext),(None,b''))
            if ext==ord('p') and blob!=old:
                target=saved/f'{prefix}-{stage}-{tid:04x}.pcx'
                target.write_bytes(blob)
                if old: target.with_suffix('.original.pcx').write_bytes(old)
                result['textures'].append({'disc':prefix,'stage':stage,'id':tid,'offset':off,'end':off+len(blob),'old_offset':oldoff,'file':str(target),'length':len(blob),'sha256':hashlib.sha256(blob).hexdigest()})
            for kind,start,bank in fonts(tid,ext,blob):
                oldbanks=list(fonts(tid,ext,old))
                oldbank=oldbanks[0][2] if oldbanks else b''
                changed=[]
                for i in range(0,len(bank),36):
                    shape=bank[i:i+36]
                    if shape!=oldbank[i:i+36] and any(shape):
                        changed.append(i//36)
                        glyphs[shape].append({'disc':prefix,'stage':stage,'kind':kind,'id':tid,'glyph':i//36,'offset':off+start+i})
                if changed:
                    result['fonts'].append({'disc':prefix,'stage':stage,'kind':kind,'id':tid,'offset':off+start,'end':off+start+len(bank),'glyph_count':len(bank)//36,'changed_glyphs':changed})
    for path in sorted(args.audit.glob('*RADIO*cn.bin')):
        prefix=path.name.split('-MGS_')[0]
        radio=path.read_bytes()
        old=path.with_name(path.name.replace('-cn.bin','-original.bin')).read_bytes()
        frags,_=radiomap.drop_nested(radiomap.fragments(radio))
        starts=sorted(frags)
        for j,frag in enumerate(starts):
            start=frags[frag]
            end=starts[j+1] if j+1<len(starts) else len(radio)
            # Sector padding is not font data. Require the invariant blank
            # twelfth row used by both original and translated glyph banks.
            changed=[]
            for i in range(start,end-35,36):
                shape=radio[i:i+36]
                if not any(shape): continue
                if any(shape[-3:]): break
                if shape!=old[i:i+36]:
                    changed.append((i-start)//36)
                    glyphs[shape].append({'disc':prefix,'kind':'radio','fragment':frag,'glyph':(i-start)//36,'offset':i})
            if changed:
                result['fonts'].append({'disc':prefix,'kind':'radio','fragment':frag,'offset':start,'end':end,'changed_glyphs':changed})
    result['glyphs']=[{'shape_hex':shape.hex(),'official_index':known.get(shape),'uses':uses} for shape,uses in sorted(glyphs.items())]
    result['summary']={'changed_textures':len(result['textures']),'changed_font_banks':len(result['fonts']),'distinct_translated_glyphs':len(glyphs),'already_in_official_fontall':sum(s in known for s in glyphs)}
    (args.audit/'resources.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result['summary'],indent=2))


if __name__=='__main__': main()
