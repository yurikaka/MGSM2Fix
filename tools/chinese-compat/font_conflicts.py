#!/usr/bin/env python3
"""Report fixed-font slot addresses and native HD lookup conflicts."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import unicodedata
from PIL import Image,ImageDraw,ImageFont
from hd_fonts import pixels
from resources import assets,fonts
from policy import FONT_ENTRIES


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--game',type=Path,required=True)
    ap.add_argument('--audit',type=Path,required=True)
    ap.add_argument('--official',type=Path,required=True)
    ap.add_argument('--fonts',type=Path,required=True)
    args=ap.parse_args();p=args.audit
    doc=json.loads((p/'byte-conflicts.json').read_text())
    inventory=json.loads((p/'resources.json').read_text())['glyphs']
    approved=json.loads((p/'approved-unicode.json').read_text())
    mapping={bytes.fromhex(r['shape_hex']):unicodedata.normalize('NFKC',approved[str(i)]) for i,r in enumerate(inventory) if str(i)in approved}
    exe=(args.game/'METAL GEAR SOLID.exe').read_bytes();indices=struct.unpack_from('<441H',exe,0x76c7b0)
    original_src=(args.official/'system/patch/fontall.bin').read_bytes()
    official_hd=(args.official/'system/patch/kanji_4x.bin').read_bytes()
    known={original_src[q:q+36] for q in range(0,len(original_src),36)}
    unmatched=[{'index':i,**r,'unicode':mapping.get(bytes.fromhex(r['shape_hex']))} for i,r in enumerate(inventory) if bytes.fromhex(r['shape_hex']) not in known]
    slots=[];corruptions=[];out=p/'font-comparison';out.mkdir(exist_ok=True)
    label=ImageFont.truetype(str(args.audit.parent/'fonts/SourceHanSerifSC-Regular.otf'),15)
    for disc in doc['discs']:
        release=f"{disc['version']}-{disc['disk']}";prefix='cn_vr_' if disc['version']=='VR-DISK' else 'cn_'
        hd=(args.fonts/(prefix+'kanji_4x.bin')).read_bytes()
        old=list(assets((p/f'{release}-MGS_STAGE.DIR_1-original.bin').read_bytes()))
        cn=list(assets((p/f'{release}-MGS_STAGE.DIR_1-cn.bin').read_bytes()))
        original_asset=next(a for a in old if a[0]=='init' and a[1]==0xca68 and a[2]==ord('r'))
        chinese_asset=next(a for a in cn if a[0]=='init' and a[1]==0xca68 and a[2]==ord('r'))
        _,oldbase,oldfont=next(fonts(original_asset[1],original_asset[2],original_asset[4]))
        _,cnbase,cnfont=next(fonts(chinese_asset[1],chinese_asset[2],chinese_asset[4]))
        stagefile=next(f for f in disc['files'] if 'STAGE.DIR' in f['name'])
        def raw_cd(logical):return (stagefile['lba']+logical//2048)*2352+24+logical%2048
        local=[]
        for k,index in enumerate(indices):
            source=oldfont[k*36:(k+1)*36];translated=cnfont[k*36:(k+1)*36]
            assert source==original_src[index*36:(index+1)*36]
            oldpos=original_asset[3]+oldbase+k*36;cnpos=chinese_asset[3]+cnbase+k*36
            row={'disc':release,'slot':k,'changed':source!=translated,'original_stage_range':[oldpos,oldpos+36],'chinese_stage_range':[cnpos,cnpos+36],
                 'original_raw_cd_start':raw_cd(oldpos),'chinese_raw_cd_start':raw_cd(cnpos),'original_hex':source.hex(),'chinese_hex':translated.hex(),
                 'unicode':mapping.get(translated),'native_hd_index':index,'official_hd_range':[index*576,(index+1)*576],
                 'rebuilt_hd_range':[index*576,(index+1)*576],'official_hd_sha256':hashlib.sha256(official_hd[index*576:(index+1)*576]).hexdigest(),
                 'rebuilt_hd_sha256':hashlib.sha256(hd[index*576:(index+1)*576]).hexdigest()}
            slots.append(row);local.append(row)
        for page in range(5):
            im=Image.new('RGB',(1536,12*90),'white');draw=ImageDraw.Draw(im)
            for j,row in enumerate(local[page*96:(page+1)*96]):
                k=row['slot'];index=row['native_hd_index'];x=j%8*192;y=j//8*90
                bitmaps=[(bytes.fromhex(row['original_hex']),12),(official_hd[index*576:(index+1)*576],48),
                         (bytes.fromhex(row['chinese_hex']),12),(hd[index*576:(index+1)*576],48)]
                for col,(raw,side) in enumerate(bitmaps):im.paste(Image.fromarray(255-pixels(raw,side)*85).resize((48,48),Image.Resampling.NEAREST),(x+col*48,y))
                draw.text((x,y+51),str(k)+' '+(row['unicode']or'')+' / '+str(index),font=label,fill='black')
            im.save(out/f'{release}-{page:02d}.png')
        for patch in disc['patches']:
            if patch['file'] not in ['font_menu.bin','font_view.bin']:continue
            sector,pos=divmod(patch['offset'],2352);logical=(sector-stagefile['lba'])*2048+pos-24
            asset=next(a for a in cn if a[1]==0xca68 and a[2]==ord('r') and a[3]<=logical<a[3]+len(a[4]))
            _,base,bank=next(fonts(asset[1],asset[2],asset[4]))
            q=logical-asset[3]-base;first=q//36;last=(q+patch['length']-1)//36
            corruptions.append({'disc':release,'patch_index':patch['index'],'source':patch['file'],'raw_cd_range':[patch['offset'],patch['end']],
                                'affected_chinese_glyphs':[{'index':i,'shape_hex':bank[i*36:(i+1)*36].hex(),'unicode':mapping.get(bank[i*36:(i+1)*36]),
                                 'bytes_overwritten':min(q+patch['length'],(i+1)*36)-max(q,i*36)} for i in range(first,last+1)]})
    roles=['set font bank and build exact-key native index list','full-width glyph call in font_draw_string','blank full-width glyph call in font_draw_string','styled/ruby full-width glyph call in font_draw_string','render half-width glyph','render ruby helper','clear glyph buffer','upload glyph buffer']
    hooks=[{'version':version,'physical_address':address,'guest_address':address|0x80000000,'role':role,'fallback_action':'disable only for supplied PPF','hd_action':'keep, with rebuilt native font data'} for version,addresses in FONT_ENTRIES.items() for address,role in zip(addresses,roles)]
    report={'schema':1,'font_hooks':hooks,'unmatched_translated_shapes':unmatched,'unmatched_count':len(unmatched),'fixed_slots':slots,'official_cd_font_writes':corruptions,
            'comparison_columns':['original 12px','official 48px','Chinese 12px','rebuilt Chinese 48px'],
            'mechanism':'Bank 0 uses the fixed 441-slot table, so PPF codepoints would select original Japanese HD glyphs. Banks 1/2/3 match exact 36-byte keys and the original fontall contains none of the translated keys. Rebuild both fixed slots and the complete key table; preserve all original Japanese keys.'}
    (p/'font-conflicts.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print('unmatched',len(unmatched),'fixed slots',len(slots),'CD glyph writes',len(corruptions))


if __name__=='__main__':main()
