#!/usr/bin/env python3
"""Resolve translated font indices in actual scripts, and verify HD coverage."""
import argparse
import bisect
import collections
import csv
import json
from pathlib import Path
import struct
import sys
from resources import assets,fonts
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'integral-english'))
import radiomap,radiotext,rendertext,gclparse,abst_build,jptext


def codes(raw):
    i=0
    while i<len(raw):
        b=raw[i];i+=1
        if b<0x80:yield b;continue
        if i==len(raw):break
        yield ((b<<8)|raw[i])&~0x6000;i+=1


def glyph(code,base,bank):
    if code<0x8100:return None
    if code>=0x9a01:
        t=(code-0x9a00)//512;u=code-0x9a00-t*512
        index=u-1-u//256;source=bank if t==0 else None
    elif 0x9600<=code<0x9a00:index=radiomap.bank1_index(code);source=bank
    else:index=rendertext.zen_index(code);source=base
    if index<0 or source is None:return None
    shape=source[index*36:(index+1)*36]
    return shape if len(shape)==36 else None


def decode(raw,base,bank,mapping,original=False):
    out=[];unresolved=[]
    for code in codes(raw):
        if code<0x80:
            out.append(chr(code) if 32<=code<127 else '\n' if code==10 else '');continue
        if code<0x8100:
            out.append(chr(code&255) if 32<=code&255<127 else f'⟨{code:04X}⟩');continue
        shape=glyph(code,base,bank)
        char=mapping.get(shape)
        if not char and original:
            char=jptext.char_for_shape(shape) if shape else None
            if not char and code<0x9600:char=jptext.glyph_char(code)
        if not char:
            char=f'⟨{code:04X}⟩';unresolved.append((code,shape))
        out.append(char)
    return ''.join(out),unresolved


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--audit',type=Path,required=True)
    ap.add_argument('--fonts',type=Path,required=True)
    args=ap.parse_args();p=args.audit
    shapes=json.loads((p/'resources.json').read_text())['glyphs'];unicode=json.loads((p/'approved-unicode.json').read_text())
    mapping={bytes.fromhex(r['shape_hex']):unicode[str(i)] for i,r in enumerate(shapes) if str(i) in unicode}
    # Punctuation is drawn from its original outline; Unicode here is only
    # for reading sentences and never changes its native HD lookup key.
    pending=json.loads((p/'manual-unicode.json').read_text())
    mapping.update({bytes.fromhex(r['shape_hex']):pending[str(i)] for i,r in enumerate(shapes) if str(i)not in unicode and str(i)in pending})
    outputs=[];coverage=[];failures=[];parse_failures=[];contexts=collections.defaultdict(list)
    shape_contexts=collections.defaultdict(list)
    for release in ['INTEGRAL-0','INTEGRAL-1','VR-DISK-0']:
        data=(p/f'{release}-MGS_STAGE.DIR_1-cn.bin').read_bytes();aa=list(assets(data))
        base=next(next(fonts(a[1],a[2],a[4]))[2] for a in aa if a[0]=='init' and a[1]==0xca68 and a[2]==ord('r'))
        native=(args.fonts/('cn_vr_fontall.bin' if release.startswith('VR') else 'cn_fontall.bin')).read_bytes()
        known={native[i:i+36] for i in range(0,len(native),36)}
        def emit(kind,where,offset,raw,bank):
            text,unknown=decode(raw,base,bank,mapping)
            outputs.append({'disc':release,'kind':kind,'where':where,'offset':hex(offset),'text':text,'raw_hex':raw.hex()})
            for code in codes(raw):
                shape=glyph(code,base,bank)
                if shape and shape not in known:failures.append({'disc':release,'where':where,'code':hex(code),'shape':shape.hex()})
                if shape:
                    if len(shape_contexts[shape.hex()])<12:
                        shape_contexts[shape.hex()].append({'disc':release,'where':where,'text':text})
                    char=mapping.get(shape)
                    if char and len(contexts[char])<8:contexts[char].append({'disc':release,'where':where,'text':text})
            return unknown
        for stage,tid,ext,off,asset in aa:
            if ext!=ord('g'):continue
            banks=list(fonts(tid,ext,asset));bank=banks[0][2] if banks else None
            if bank:
                missing=[i//36 for i in range(0,len(bank),36) if any(bank[i:i+36]) and bank[i:i+36] not in known]
                coverage.append({'disc':release,'kind':'gcx','stage':stage,'id':hex(tid),'glyphs':len(bank)//36,'missing':missing})
            try:g,_=abst_build.parse_gcx(asset,0)
            except Exception:continue
            for name,body in [('script',g['script'])]+[(f'proc:{i}',b) for i,b in g['procs']]:
                body_offset=asset.find(body)
                assert body_offset>=0
                nodes=[]
                try:gclparse.parse_values(body,0,len(body),nodes)
                except Exception:continue
                def walk(node):
                    if node.kind=='STRING':emit('gcx',stage+'/'+hex(tid)+'/'+name,off+body_offset+node.pos+2,body[node.pos+2:node.end-1],bank)
                    for child in node.kids:walk(child)
                for node in nodes:walk(node)
        path=p/f'{release}-MGS_RADIO.DAT_1-cn.bin'
        if path.exists():
            radio=path.read_bytes();frags,_=radiomap.drop_nested(radiomap.fragments(radio));starts=sorted(frags)
            for j,frag in enumerate(starts):
                start=frags[frag];end=starts[j+1] if j+1<len(starts) else len(radio);bank=radio[start:end]
                # Verify every glyph used by real TALK records, rather than
                # treating the padded remainder of a fragment as a font.
                def talk(a,b,depth):emit('radio',hex(frag),a,radio[a:b],bank)
                def walk_radio(pos,limit,depth=0):
                    if depth>24:return
                    try:records,_=radiomap.walk_block(radio,pos,limit)
                    except ValueError as error:
                        if radio[pos+1:pos+3]==b'\x00\x03' and radio[pos+3]==0:return
                        parse_failures.append({'disc':release,'fragment':hex(frag),'position':hex(pos),'error':str(error)})
                        return
                    for rpos,code,size in records:
                        payload=rpos+4;rend=rpos+size+2
                        if code==1:talk(payload+6,rend,depth)
                        elif code==2:
                            # VOICE wraps a subtitle block after its 32-bit
                            # voice identifier. Omitting it misses almost all
                            # voiced dialogue, including translated strings.
                            walk_radio(payload+4,rend,depth+1)
                        elif code==0x10:
                            q=radiotext.value_end(radio,payload)
                            while q<rend:
                                walk_radio(q,rend,depth+1)
                                q=radiotext.block_end(radio,q)
                                if q+1>=rend or radio[q]!=255:break
                                branch=radio[q+1];q+=2
                                if branch==0x12:q=radiotext.value_end(radio,q)
                                elif branch!=0x11:break
                        elif code in (0x20,0x30):
                            q=payload+2 if code==0x30 else radiotext.value_end(radio,payload)
                            while q<rend and radio[q]:
                                branch=radio[q];q+=1
                                if branch in (0x21,0x31):q+=2
                                elif branch!=0x22:break
                                walk_radio(q,rend,depth+1)
                                if branch==0x22:break
                                q=radiotext.block_end(radio,q)
                walk_radio(frag+8,start)
    with (p/'translated-text.tsv').open('w',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(outputs[0]),delimiter='\t');writer.writeheader();writer.writerows(outputs)
    (p/'glyph-contexts.json').write_text(json.dumps(contexts,ensure_ascii=False,indent=2))
    (p/'shape-contexts.json').write_text(json.dumps(shape_contexts,ensure_ascii=False,indent=2))
    result={'script_lines':len(outputs),'gcx_banks_checked':len(coverage),'missing_used_glyphs':failures,'banks':coverage,'parse_failures':parse_failures}
    (p/'hd-coverage.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print('lines',len(outputs),'banks',len(coverage),'missing_used_glyphs',len(failures),'banks_with_missing',sum(bool(b['missing']) for b in coverage),'parse_failures',len(parse_failures))


if __name__=='__main__':main()
