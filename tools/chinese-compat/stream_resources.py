#!/usr/bin/env python3
"""Audit native stream packets and STR frames against every changed byte.

Layouts follow libfs/stream.c, game/jimctrl.c, game/movie.c in mgs_reversing.
Type 3/6 stream packets and STR type 1/2 carry subtitle data and font bank 3;
STR type 0x8001 carries compressed picture data.
"""
import argparse
import collections
import json
from pathlib import Path
import struct
import text_export
from resources import assets,fonts


def packets(data):
    cursor=0
    while cursor+4<=len(data):
        header=struct.unpack_from('<I',data,cursor)[0];kind=header&255;size=header>>8
        if kind not in [1,2,3,4,5,6,7,0x10] or size<4 or size>0x100000 or size%4 or cursor+size>len(data):
            cursor=(cursor//2048+1)*2048;continue
        yield cursor,kind,size,data[cursor+4:cursor+size]
        cursor+=size


def subtitle_font(blob):
    if len(blob)<16:return None
    offset=struct.unpack_from('<I',blob,12)[0]
    text,table=struct.unpack_from('<HH',blob,8)
    if not (16<=offset<=len(blob) and text<=offset and table<=offset):return None
    return offset


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--audit',type=Path,required=True)
    args=ap.parse_args();p=args.audit
    original_inventory=json.loads((p/'resources.json').read_text())
    glyphs={bytes.fromhex(r['shape_hex']):dict(r,uses=[u for u in r['uses'] if u['kind'] not in ['stream-bank3','movie-bank3']]) for r in original_inventory['glyphs']}
    baseline={shape for shape,r in glyphs.items() if r['uses']};reports=[];banks=[];subtitles=[]
    approved=json.loads((p/'approved-unicode.json').read_text())
    mapping={bytes.fromhex(r['shape_hex']):approved[str(i)] for i,r in enumerate(original_inventory['glyphs']) if str(i) in approved}
    for path in sorted(p.glob('*cn.bin')):
        if not any(n in path.name for n in ['DEMO.DAT','VOX.DAT','ZMOVIE.STR']):continue
        data=path.read_bytes();old=path.with_name(path.name.replace('-cn','-original')).read_bytes()
        release=path.name.split('-MGS_')[0]
        stage=(p/f'{release}-MGS_STAGE.DIR_1-cn.bin').read_bytes()
        base_font=next(next(fonts(a[1],a[2],a[4]))[2] for a in assets(stage) if a[0]=='init' and a[1]==0xca68 and a[2]==ord('r'))
        covered=bytearray(len(data));changed_packets=[];native_types=collections.Counter()
        def fontbank(blob,offset,locations,label,oldblob):
            base=subtitle_font(blob)
            if base is None:return
            original_base=subtitle_font(oldblob)
            count=0;changed=0
            for q in range(base,len(blob)-35,36):
                shape=blob[q:q+36]
                if not any(shape):continue
                if any(shape[-3:]):break
                count+=1
                original=oldblob[original_base+q-base:original_base+q-base+36] if original_base is not None else b''
                if shape==original:continue
                changed+=1
                use={'disc':path.name.split('-MGS_')[0],'kind':label,'container':path.name,
                     'packet_offset':offset,'glyph':(q-base)//36,'offset':locations[q]}
                if shape not in glyphs:glyphs[shape]={'shape_hex':shape.hex(),'official_index':None,'uses':[]}
                glyphs[shape]['uses'].append(use)
            banks.append({'file':path.name,'offset':offset,'type':label,'font_offset':base,'glyphs':count,'changed':changed})
            # jimctrl/movie consume a linked list: four little-endian words
            # (next offset, start tick, duration, flags), then a NUL string.
            q=struct.unpack_from('<H',blob,10)[0];seen=set()
            while q not in seen and 16<=q<base-16:
                seen.add(q);step,start,duration,flags=struct.unpack_from('<4I',blob,q)
                if not (step or start or duration):break
                end=blob.find(b'\0',q+16,base)
                if end<0:break
                raw=blob[q+16:end];out=[];used=[]
                for code in text_export.codes(raw):
                    if code<0x8100:out.append(chr(code&255) if 32<=code&255<127 else '');continue
                    if code>=0x9a00:
                        t=(code-0x9a00)//512;u=code-0x9a00-t*512
                        index=u-1-u//256;bank=t+2
                    else:index=-1;bank=-1
                    shape=blob[base+index*36:base+(index+1)*36] if bank==3 and index>=0 else text_export.glyph(code,base_font,None)
                    used.append(shape.hex() if shape and len(shape)==36 else None)
                    out.append(mapping.get(shape,f'⟨{code:04X}⟩'))
                old_start=q+16
                subtitles.append({'file':path.name,'packet_offset':offset,'record_offset':q,'start':start,'duration':duration,'text':''.join(out),'shapes':used,'raw_hex':raw.hex(),
                                  'ppf_changed_text_bytes':raw!=oldblob[old_start:old_start+len(raw)]})
                if not step:break
                if step<17 or q+step>=base:break
                q+=step
        if 'ZMOVIE' not in path.name:
            # Original packet boundaries remain authoritative even if a PPF
            # overwrites a packet header. Never let payload bytes masquerade
            # as an arbitrary multi-megabyte packet.
            for off,kind,size,previous in packets(old):
                blob=data[off+4:off+size]
                native_types[kind]+=1;covered[off:off+size]=b'\1'*size
                if blob!=previous:
                    changed_packets.append({'offset':off,'end':off+size,'type':kind,'role':'subtitle and font' if kind in [3,6] else 'non-subtitle','changed_bytes':sum(a!=b for a,b in zip(blob,previous))})
                if kind in [3,6]:fontbank(blob,off,list(range(off+4,off+size)),'stream-bank3',previous)
        else:
            chunks=collections.defaultdict(list)
            for off in range(2048,len(data)-2047,2048):
                if data[off:off+2]!=b'\x60\x01':continue
                kind,chunk,total=struct.unpack_from('<3H',data,off+2)
                frame=struct.unpack_from('<I',data,off+8)[0]
                native_types[kind]+=1;covered[off:off+2048]=b'\1'*2048
                if data[off:off+2048]!=old[off:off+2048]:
                    changed_packets.append({'offset':off,'end':off+2048,'type':kind,'frame':frame,'chunk':chunk,'role':'MDEC picture' if kind==0x8001 else 'subtitle and font','changed_bytes':sum(a!=b for a,b in zip(data[off:off+2048],old[off:off+2048]))})
                if kind in [1,2]:chunks[(kind,frame,total)].append((chunk,off))
            for (kind,frame,total),parts in chunks.items():
                parts=sorted(parts)
                if len(parts)!=total or [c for c,_ in parts]!=list(range(total)):continue
                blob=b''.join(data[o+32:o+2048] for _,o in parts)
                previous=b''.join(old[o+32:o+2048] for _,o in parts)
                loc=[o+i for _,o in parts for i in range(32,2048)]
                fontbank(blob,parts[0][1],loc,'movie-bank3',previous)
        uncovered=[i for i,(a,b) in enumerate(zip(data,old)) if a!=b and not covered[i]]
        reports.append({'file':path.name,'native_types':dict(native_types),'changed_packets':changed_packets,'uncovered_changed_bytes':len(uncovered),'uncovered_examples':uncovered[:40]})
    extras=[r for shape,r in sorted(glyphs.items()) if shape not in baseline]
    result={'containers':reports,'font_banks':banks,'additional_translated_glyphs':extras,
            'subtitles':subtitles,
            'additional_glyph_count':len(extras),
            'picture_changes':sum(r['role']=='MDEC picture' for d in reports for r in d['changed_packets']),
            'unclassified_packets':sum(r['role']=='non-subtitle' for d in reports for r in d['changed_packets'])}
    (p/'stream-resources.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    # Append new shapes without renumbering the reviewed Unicode mappings;
    # repeated runs refresh uses and preserve the same baseline comparison.
    ordered=[glyphs[bytes.fromhex(r['shape_hex'])] for r in original_inventory['glyphs']]
    existing={r['shape_hex'] for r in ordered}
    ordered.extend(r for r in extras if r['shape_hex'] not in existing)
    original_inventory['glyphs']=ordered
    (p/'resources.json').write_text(json.dumps(original_inventory,ensure_ascii=False,indent=2))
    print('extra glyphs',len(extras),'picture changes',result['picture_changes'],'non-subtitle changes',result['unclassified_packets'],'uncovered',[(r['file'],r['uncovered_changed_bytes']) for r in reports])


if __name__=='__main__':main()
