#!/usr/bin/env python3
"""Build regional native 4x fonts, keeping exact guest-bitmap lookup keys.

Unicode mappings must be explicitly reviewed; OCR candidates alone are never
used. Unidentified symbols retain their identity through traced outlines.
"""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import struct
import unicodedata
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont
from resources import assets, fonts


def pixels(raw, side=12):
    return np.array([(b >> (6-2*k)) & 3 for b in raw for k in range(4)],
                    dtype=np.uint8).reshape(side, side)


def pack(image):
    a=np.asarray(image, dtype=np.uint16)
    a=((a*3+127)//255).astype(np.uint8).reshape(-1,4)
    return bytes((a[:,0]<<6)|(a[:,1]<<4)|(a[:,2]<<2)|a[:,3])


def pack_half(image,width=24,y_offset=0):
    # Records reserve 576 bytes, but the native reader advances rows by
    # width/4, not by the full-width glyph stride of 12. Unused bytes trail
    # the complete width*48/4 image rather than padding each scanline.
    assert image.size==(width,48) and width%4==0
    data=pack(image)
    return bytes([width,y_offset])+data+bytes(576-len(data))


def traced(raw):
    """Trace the supplied shape without guessing its Unicode identity.

    Supersampled contours and corner cutting preserve holes and disconnected
    marks. The result is antialiased before the official four-level packing.
    This cannot restore stroke details absent from the original 12px source.
    """
    shape=pixels(raw)
    mask=cv2.resize((shape>0).astype(np.uint8)*255,(96,96),interpolation=cv2.INTER_NEAREST)
    contours,hierarchy=cv2.findContours(mask,cv2.RETR_TREE,cv2.CHAIN_APPROX_SIMPLE)
    im=Image.new('L',(384,384),0);draw=ImageDraw.Draw(im)
    if hierarchy is None:return im.resize((48,48))
    def depth(index):
        count=0;parent=int(hierarchy[0,index,3])
        while parent>=0:count+=1;parent=int(hierarchy[0,parent,3])
        return count
    for index in sorted(range(len(contours)),key=depth):
        points=cv2.approxPolyDP(contours[index],0.65,True).reshape(-1,2).astype(float)
        if len(points)<3:continue
        # Cut only a small portion of each corner: thin strokes must survive.
        points=np.stack((.875*points+.125*np.roll(points,1,axis=0),
                         .875*points+.125*np.roll(points,-1,axis=0)),axis=1).reshape(-1,2)
        draw.polygon([tuple(4*p+2) for p in points],fill=255 if depth(index)%2==0 else 0)
    return im.resize((48,48),Image.Resampling.LANCZOS)


def unicode_glyph(char,font):
    im=Image.new('L',(192,192),0);draw=ImageDraw.Draw(im)
    box=draw.textbbox((0,0),char,font=font)
    draw.text((-box[0],-box[1]),char,font=font,fill=255)
    ink=im.crop((0,0,box[2]-box[0],box[3]-box[1]))
    # Match the collection's 44px ink region inside its 48px cell.
    scale=min(176/max(ink.width,1),176/max(ink.height,1))
    ink=ink.resize((max(1,round(ink.width*scale)),max(1,round(ink.height*scale))),Image.Resampling.LANCZOS)
    out=Image.new('L',(192,192),0)
    out.paste(ink,((176-ink.width)//2,(176-ink.height)//2))
    return out.resize((48,48),Image.Resampling.LANCZOS)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--audit',type=Path,required=True)
    ap.add_argument('--official',type=Path,required=True)
    ap.add_argument('--game',type=Path,required=True)
    ap.add_argument('--font',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--version',choices=['INTEGRAL','VR-DISK'],default='INTEGRAL')
    args=ap.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    rows=json.loads((args.audit/'resources.json').read_text())['glyphs']
    approved=json.loads((args.audit/'approved-unicode.json').read_text())
    font=ImageFont.truetype(str(args.font),176)
    original_src=(args.official/'system/patch/fontall.bin').read_bytes()
    original_hd=(args.official/'system/patch/kanji_4x.bin').read_bytes()
    src=[original_src[i:i+36] for i in range(0,len(original_src),36)]
    hd=[original_hd[i:i+576] for i in range(0,len(original_hd),576)]
    assert len(src)==len(hd)==7896
    source_to_hd={};metadata=[]
    for i,row in enumerate(rows):
        key=row['shape_hex'];char=approved.get(str(i))
        if char is not None:char=unicodedata.normalize('NFKC',char)
        # Punctuation and game-specific symbols depend on exact positioning.
        use_font=char is not None and len(char)==1 and 0x3400<=ord(char)<=0x9fff
        image=unicode_glyph(char,font) if use_font else traced(bytes.fromhex(key))
        source_to_hd[bytes.fromhex(key)]=pack(image)
        metadata.append({'index':i,'shape_hex':key,'unicode':char,'method':'SourceHanSerif vector' if use_font else 'faithful outline trace'})
    exe=(args.game/'METAL GEAR SOLID.exe').read_bytes()
    # Version-specific native bank-0 lookup table; checked against every slot
    # of the unmodified guest font before making any replacements.
    indices=struct.unpack_from('<441H',exe,0x76c7b0)
    old_banks=[];cn_banks=[];half_fonts=[]
    releases=['INTEGRAL-0','INTEGRAL-1'] if args.version=='INTEGRAL' else ['VR-DISK-0']
    for release in releases:
        for suffix,target in [('original',old_banks),('cn',cn_banks)]:
            data=(args.audit/f'{release}-MGS_STAGE.DIR_1-{suffix}.bin').read_bytes()
            found=[a for a in assets(data) if a[1]==0xca68 and a[2]==ord('r')]
            target.extend(next(fonts(a[1],a[2],a[4]))[2][:441*36] for a in found)
            if suffix=='cn':half_fonts.extend(a[4] for a in found)
    assert all(b==old_banks[0] for b in old_banks),'original base banks differ'
    # The main discs differ only in alternate drawings of punctuation and the
    # circle button. They have the same character identities. The VR disc has
    # a different character ordering and MUST have its own native font set.
    differences={i//36 for b in cn_banks for i in range(0,len(b),36)
                 if b[i:i+36]!=cn_banks[0][i:i+36]}
    assert not differences or args.version=='INTEGRAL' and differences<={170,171,172,173,195},'unexpected base-bank variants'
    assert all(src[index]==old_banks[0][k*36:(k+1)*36] for k,index in enumerate(indices))
    original_pairs=[];replaced=0
    for k,index in enumerate(indices):
        shape=cn_banks[0][k*36:(k+1)*36]
        if shape==src[index]:continue
        replacement=source_to_hd.get(shape)
        if replacement is None:
            assert not any(shape),'base-bank glyph missing from inventory'
            replacement=bytes(576)
        original_pairs.append((src[index],hd[index]))
        src[index]=shape;hd[index]=replacement;replaced+=1
    lookup={shape:i for i,shape in reversed(list(enumerate(src)))}
    # Keep original Japanese keys working even when their fixed slot became
    # Chinese. A changed fixed slot must not corrupt a dynamic bank using the
    # original glyph elsewhere.
    for shape,image in original_pairs+list(source_to_hd.items()):
        if shape not in lookup:
            lookup[shape]=len(src);src.append(shape);hd.append(image)
    assert len(src)<65535 and len(src)==len(hd)
    for shape,image in source_to_hd.items():
        assert hd[lookup[shape]]==image,'ambiguous key maps to wrong HD image'
    # Translated ASCII is fixed six-pixel width. Preserve the 16 platform
    # symbols above the ASCII range; their metadata is not a plain width.
    hdata=(args.official/'system/patch/integral_hankaku_4x.bin').read_bytes()
    halves=[hdata[i:i+578] for i in range(0,len(hdata),578)]
    assert all(f[:392]==half_fonts[0][:392] for f in half_fonts)
    for k in range(96):
        # The collection already has HD Latin glyphs. Retain their forms and
        # common baseline while adapting them to the PPF's fixed 6px advance.
        # Header bytes are independent width and vertical offset, not u16.
        old=halves[k];width,y_offset=old[:2]
        assert 0<width<=48 and width%4==0
        raw=old[2:2+width*48//4]
        ink=np.array([(b>>(6-2*j))&3 for b in raw for j in range(4)],dtype=np.uint8).reshape(48,width)
        im=Image.fromarray(ink*85).resize((24,48),Image.Resampling.LANCZOS)
        halves[k]=pack_half(im,y_offset=y_offset)
        if k+32 in [95,127]:
            offset=int.from_bytes(half_fonts[0][9+k*4:12+k*4],'big')
            raw=half_fonts[0][392+offset:392+offset+18]
            ink=np.array([(b>>(6-2*j))&3 for b in raw for j in range(4)],dtype=np.uint8).reshape(12,6)
            cell=np.zeros((12,12),dtype=np.uint8);cell[:,:6]=ink
            packed=bytes((cell.reshape(-1,4)[:,0]<<6)|(cell.reshape(-1,4)[:,1]<<4)|(cell.reshape(-1,4)[:,2]<<2)|cell.reshape(-1,4)[:,3])
            halves[k]=pack_half(traced(packed).crop((0,0,24,48)))
    prefix='cn_' if args.version=='INTEGRAL' else 'cn_vr_'
    outputs={prefix+'kanji_4x.bin':b''.join(hd),prefix+'fontall.bin':b''.join(src),
             prefix+'hankaku_4x.bin':b''.join(halves)}
    for name,data in outputs.items():(args.out/name).write_bytes(data)
    result={'schema':1,'version':args.version,'glyph_size':[48,48],'bits_per_pixel':2,'bit_order':'MSB first',
            'original_glyph_count':7896,'native_glyph_count':len(src),
            'translated_distinct_glyphs':len(rows),'fixed_bank_slots_replaced':replaced,
            'methods':dict(collections.Counter(r['method'] for r in metadata)),
            'font_source':str(args.font),'font_sha256':hashlib.sha256(args.font.read_bytes()).hexdigest(),
            'outputs':{name:{'size':len(data),'sha256':hashlib.sha256(data).hexdigest()} for name,data in outputs.items()},
            'glyphs':metadata,'native_font_lookup':{'matcher':'0x140107F80','renderer':'0x140107D60','fixed_table_file_offset':'0x76C7B0','fixed_table_slots':441},
            'halfwidth_format':{'renderer':'0x1401079F0','record_bytes':578,'header':['u8 packed width','u8 vertical offset'],'rows':48,'translated_width':24,'source':'official HD Latin glyphs, resampled horizontally; translated special symbols traced'},
            'limits':['Outlined unidentified glyphs preserve the 12px source identity; unavailable fine stroke details cannot be reconstructed.', 'Windows in-game rendering must still be verified.']}
    (args.out/(prefix+'font-build.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2))
    for page in range((len(rows)+95)//96):
        im=Image.new('RGB',(1152,8*120),'white');draw=ImageDraw.Draw(im)
        label=ImageFont.truetype(str(args.font),14)
        for j,row in enumerate(rows[page*96:(page+1)*96]):
            x=j%12*96;y=j//12*120;raw=bytes.fromhex(row['shape_hex'])
            old=Image.fromarray(255-pixels(raw)*85)
            new=Image.fromarray(255-pixels(source_to_hd[raw],48)*85)
            im.paste(old.resize((48,48),Image.Resampling.NEAREST),(x,y))
            im.paste(new,(x+48,y))
            i=page*96+j;draw.text((x,y+53),str(i)+' '+str(approved.get(str(i),'')),fill='black',font=label)
            draw.text((x,y+74),'font' if metadata[i]['method'].startswith('Source') else 'trace',fill='blue')
        im.save(args.out/f'{prefix}preview-{page:02d}.png')
    print({k:v for k,v in result.items() if k not in ['glyphs','outputs']})


if __name__=='__main__':main()
