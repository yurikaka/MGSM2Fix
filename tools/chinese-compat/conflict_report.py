#!/usr/bin/env python3
"""Expand every blocked record into byte evidence and its enclosing text.

Official intent is decoded with the original banks; Chinese intent is decoded
with the PPF banks. This distinction matters because codepoints were remapped.
"""
import argparse
import bisect
import collections
import csv
import json
from pathlib import Path
import struct
from audit import Archive,Psb,runs
from resources import assets,fonts
from text_export import decode,codes


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--game',type=Path,required=True)
    ap.add_argument('--audit',type=Path,required=True)
    args=ap.parse_args();p=args.audit
    doc=json.loads((p/'byte-conflicts.json').read_text())
    inventory=json.loads((p/'resources.json').read_text())['glyphs']
    approved=json.loads((p/'approved-unicode.json').read_text())
    mapping={bytes.fromhex(r['shape_hex']):approved[str(i)] for i,r in enumerate(inventory) if str(i)in approved}
    arcs=[Archive(str(f)) for f in [args.game/'windata/alldata.bin',*sorted((args.game/'windata/dlc').glob('*.bin'))] if f.with_suffix('.psb.m').exists()]
    def extract(name):return next(a for a in arcs if name in a.files).extract(name)
    table=Psb(extract('099/config/title_patchdata.psb.m')).root()
    stream=json.loads((p/'stream-resources.json').read_text())
    texts=collections.defaultdict(list)
    with (p/'translated-text.tsv').open() as f:
        for r in csv.DictReader(f,delimiter='\t'):
            r['address']=int(r['offset'],16)
            texts[(r['disc'],r['kind'])].append(r)
    for entries in texts.values():entries.sort(key=lambda r:r['address'])
    results=[]
    for disc in doc['discs']:
        release=f"{disc['version']}-{disc['disk']}"
        stage_old=(p/f'{release}-MGS_STAGE.DIR_1-original.bin').read_bytes()
        stage_cn=(p/f'{release}-MGS_STAGE.DIR_1-cn.bin').read_bytes()
        old_assets=list(assets(stage_old));cn_assets=list(assets(stage_cn))
        base_old=next(next(fonts(a[1],a[2],a[4]))[2] for a in old_assets if a[0]=='init' and a[1]==0xca68 and a[2]==ord('r'))
        base_cn=next(next(fonts(a[1],a[2],a[4]))[2] for a in cn_assets if a[0]=='init' and a[1]==0xca68 and a[2]==ord('r'))
        files={}
        for row in disc['files']:
            clean=row['name'].strip('/').replace('/','_').replace(';','_')
            path=p/f'{release}-{clean}-original.bin'
            if path.exists():files[row['name']]=(path.read_bytes(),path.with_name(path.name.replace('-original','-cn')).read_bytes())
        radio_banks={}
        radio_path=p/f'{release}-MGS_RADIO.DAT_1-original.bin'
        if radio_path.exists():
            import radiomap
            radio=radio_path.read_bytes();frags,_=radiomap.drop_nested(radiomap.fragments(radio));starts=sorted(frags)
            radio_banks={frag:(start,starts[j+1] if j+1<len(starts) else len(radio)) for j,(frag,start) in enumerate(sorted(frags.items()))}
        for patch in disc['patches']:
            if not patch['conflict_ranges']:continue
            raw=table[disc['version']]['patchs'][patch['index']]
            payload=extract('099/patch/'+patch['file']+'.m') if patch['file'] else bytes(raw['data'])
            offset=patch['offset'];location=[];kind=None
            if patch['kind']=='ram':
                original=(p/f'{release}-ram-original.bin').read_bytes()
                chinese=(p/f'{release}-ram-cn.bin').read_bytes()
                logical=offset;official=bytearray(original);official[logical:logical+len(payload)]=payload
                purpose='主程序内物品/武器说明文字表；官方整块表包含平台按键提示，PPF改为中文说明' if patch['file'] else '主程序存储提示：メモリーカード 改为 ストレージ，PPF 改为中文'
            else:
                file=next(f for f in disc['files'] if f['lba']*2352<=offset<(f['lba']+(f['size']+2047)//2048)*2352)
                if file['name'] not in files:
                    raise ValueError('missing original/CN file '+file['name'])
                original,chinese=files[file['name']];sector,pos=divmod(offset,2352)
                logical=(sector-file['lba'])*2048+pos-24
                official=bytearray(original)
                for j,b in enumerate(payload):
                    sector,pos=divmod(offset+j,2352);q=(sector-file['lba'])*2048+pos-24
                    if 24<=pos<2072 and 0<=q<len(official):official[q]=b
                location.append(f"{file['name']}+0x{logical:X}")
                kind='radio' if 'RADIO' in file['name'] else 'gcx' if 'STAGE' in file['name'] else None
                if len(payload)==14 and not patch['file']:purpose='光盘脚本存储提示：メモリーカード 改为 ストレージ，PPF 改为中文'
                elif len(payload)==1:purpose='font.res 半角字宽：官方减小 1 像素，汉化统一为 6 像素'
                elif (patch['file'] or '').startswith('font_'):purpose='font.res 中单个 12×12 字形：官方菜单/平台图标替换，PPF已重编字形'
                else:purpose='脚本文字及嵌入字库：官方平台按键、换盘或存储措辞；整块回写同时恢复其他原文'
                for stage,tid,ext,start,asset in old_assets if kind=='gcx' else []:
                    if start<=logical<start+len(asset):location.append(f'{stage}/{tid:04x}.{chr(ext)}+0x{logical-start:X}')
            snippets=[]
            entries=texts[(release,kind)] if kind else []
            if kind=='gcx':
                # Some original OPTION size fields overflow u8. The parser
                # cannot walk their enclosing command, although its STRING
                # records are well formed. Recover only declared, terminated
                # strings with valid game character codes in the same asset.
                for asset in old_assets:
                    if not asset[3]<=logical<asset[3]+len(asset[4]):continue
                    local=[];start=asset[3];blob=asset[4]
                    for q in range(max(0,logical-start-256),min(len(blob)-3,logical-start+len(payload))):
                        if blob[q]!=7:continue
                        n=blob[q+1];end=q+2+n
                        if n<3 or end>len(blob) or blob[end-1]!=0:continue
                        raw_text=blob[q+2:end-1]
                        if not all(c in (9,10,13) or 32<=c<127 or 0x8000<=c<0x9e00 for c in codes(raw_text)):continue
                        a=start+q+2;cn_size=chinese[a-1]-1
                        if cn_size<0:continue
                        cn_asset=next((x for x in cn_assets if x[0:3]==asset[0:3]),None)
                        cn_banks=list(fonts(cn_asset[1],cn_asset[2],cn_asset[4])) if cn_asset else []
                        cn_bank=cn_banks[0][2] if cn_banks else None
                        cn_raw=chinese[a:a+cn_size]
                        local.append({'address':a,'raw_hex':cn_raw.hex(),'where':asset[0]+'/'+hex(asset[1])+'/recovered-string','text':decode(cn_raw,base_cn,cn_bank,mapping)[0]})
                    seen={r['address'] for r in entries}
                    entries=sorted(entries+[r for r in local if r['address'] not in seen],key=lambda r:r['address'])
            addresses=[r['address'] for r in entries]
            for r in entries[max(0,bisect.bisect_left(addresses,logical)-1):bisect.bisect_right(addresses,logical+len(payload))]:
                a=r['address'];cn_raw=bytes.fromhex(r['raw_hex'])
                if a+len(cn_raw)<=logical:continue
                if kind=='gcx':
                    asset=next((x for x in old_assets if x[3]<=a<x[3]+len(x[4])),None)
                    if not asset:continue
                    bank_list=list(fonts(asset[1],asset[2],asset[4]));bank=bank_list[0][2] if bank_list else None
                    size=original[a-1]-1
                else:
                    frag=int(r['where'],16);start,end=radio_banks[frag];bank=original[start:end]
                    size=struct.unpack_from('>H',original,a-8)[0]-8
                if size<0:continue
                old_raw=original[a:a+size];off_raw=bytes(official[a:a+size])
                old_text=decode(old_raw,base_old,bank,{},original=True)[0]
                official_text=decode(off_raw,base_old,bank,{},original=True)[0]
                snippets.append({'file_offset':a,'where':r['where'],'original':old_text,'official':official_text,'chinese':r['text'],'original_hex':old_raw.hex(),'official_hex':off_raw.hex(),'chinese_hex':cn_raw.hex()})
            if patch['kind']=='ram':
                # RAM records contain C strings; they use bank 0 only.
                end=logical+len(payload);q=logical
                while q<end:
                    z=original.find(b'\0',q,end)
                    if z<0:z=end
                    if z-q>2:
                        cn_end=chinese.find(b'\0',q,end);cn_end=end if cn_end<0 else cn_end
                        snippets.append({'file_offset':q,'original':decode(original[q:z],base_old,None,{},original=True)[0],'official':decode(bytes(official[q:z]),base_old,None,{},original=True)[0],'chinese':decode(chinese[q:cn_end],base_cn,None,mapping)[0]})
                    q=z+1
            elif kind is None and 'VOX' in file['name']:
                from stream_resources import subtitle_font
                for line in stream['subtitles']:
                    if not line['file'].startswith(release+'-') or 'VOX' not in line['file']:continue
                    a=line['packet_offset']+4+line['record_offset']+16
                    if not a<logical+len(payload) or a+len(bytes.fromhex(line['raw_hex']))<=logical:continue
                    packet=line['packet_offset'];size=struct.unpack_from('<I',original,packet)[0]>>8
                    blob=original[packet+4:packet+size];base=subtitle_font(blob)
                    if base is None:continue
                    bank=blob[base:];end=original.find(b'\0',a,packet+4+base)
                    if end<0:end=packet+4+base
                    old_raw=original[a:end];off_raw=bytes(official[a:end]);cn_raw=bytes.fromhex(line['raw_hex'])
                    # decode() takes a bank-2/1 argument; stream codes use
                    # bank 3. Shift the bank selector while retaining indices.
                    def bank2(raw):
                        out=bytearray();i=0
                        while i<len(raw):
                            b=raw[i];out.append(b);i+=1
                            if b<128 or i==len(raw):continue
                            if b&~0x60 in [0x9c,0x9d]:out[-1]=b-2
                            out.append(raw[i]);i+=1
                        return bytes(out)
                    snippets.append({'file_offset':a,'where':line['file']+'/stream-subtitle','original':decode(bank2(old_raw),base_old,bank,{},original=True)[0],'official':decode(bank2(off_raw),base_old,bank,{},original=True)[0],'chinese':line['text'],'original_hex':old_raw.hex(),'official_hex':off_raw.hex(),'chinese_hex':cn_raw.hex()})
            before=[];after_cn=[];changes=[];outside=[]
            for j,target in enumerate(payload):
                if patch['kind']=='ram':q=offset+j
                else:
                    sector,pos=divmod(offset+j,2352)
                    if not 24<=pos<2072:continue
                    q=(sector-file['lba'])*2048+pos-24
                old=original[q];cn_byte=chinese[q];before.append(old);after_cn.append(cn_byte)
                if old!=target:
                    changes.append(offset+j)
                    if not any(a<=offset+j<b for a,b in patch['conflict_ranges']):outside.append(offset+j)
            results.append({**{k:patch[k] for k in ['kind','index','file','offset','end','conflict_ranges','conflict_values']},'version':disc['version'],'disk':disc['disk'],'location':location,'purpose':purpose,'text_contexts':snippets,
                            'original_payload_hex':bytes(before).hex(),'official_payload_hex':payload.hex(),'chinese_payload_hex':bytes(after_cn).hex(),
                            'effective_official_change_ranges':runs(changes),'effective_changes_outside_conflict_ranges':runs(outside),
                            'exclusion_unit':'whole official record; do not splice instructions, encoded strings, or glyph records'})
    result={'schema':1,'records_and_platform_variants':results,'interpretation':'Official text is decoded using original glyph banks; Chinese text uses the supplied PPF glyph banks. Exact byte evidence remains authoritative.'}
    (p/'semantic-conflicts.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print('conflicting records/variants',len(results),'with text contexts',sum(bool(r['text_contexts']) for r in results))


if __name__=='__main__':main()
