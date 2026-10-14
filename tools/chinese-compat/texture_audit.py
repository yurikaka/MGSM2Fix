#!/usr/bin/env python3
"""Compare every stage asset and each official native HD texture binding.

Stage names/IDs are not globally unique; each occurrence is checked separately.
Changed nontexture blobs are classified rather than silently ignored.
"""
import argparse
import collections
import hashlib
import io
import json
from pathlib import Path
import sys
from PIL import Image
from resources import assets
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'integral-english'))
from m2archive import Archive


def sha(data):return hashlib.sha256(data).hexdigest()


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--game',type=Path,required=True)
    ap.add_argument('--audit',type=Path,required=True)
    ap.add_argument('--official',type=Path,required=True)
    args=ap.parse_args()
    arc=Archive(str(args.game/'windata/alldata.bin'))
    results=[];bound=[];unknown=[]
    for path in sorted(args.audit.glob('*STAGE*cn.bin')):
        vr=path.name.startswith('VR-DISK')
        table=json.loads((args.official/'099/config'/('title_texdata_vrm.json' if vr else 'title_texdata.json')).read_text())['textures']
        byid=collections.defaultdict(list)
        for record in table:byid[record['id']].append(record)
        prefix='099/texture/vrm/' if vr else '099/texture/'
        originals={(n,t,e):(o,b) for n,t,e,o,b in assets(path.with_name(path.name.replace('-cn','-original')).read_bytes())}
        changed=[];totals=collections.Counter();lowtextures=0
        for stage,tid,ext,offset,data in assets(path.read_bytes()):
            previous=originals.get((stage,tid,ext));totals[chr(ext)]+=1
            is_changed=previous is None or previous[1]!=data
            if is_changed:
                record={'stage':stage,'id':tid,'extension':chr(ext),'offset':offset,'size':len(data),
                        'original_sha256':sha(previous[1]) if previous else None,'chinese_sha256':sha(data),
                        'type':'PCX image' if ext==ord('p') else 'script plus embedded font' if ext==ord('g') else 'resident font' if tid==0xca68 and ext==ord('r') else 'unclassified'}
                changed.append(record)
                if record['type']=='unclassified':unknown.append(record)
            if ext!=ord('p'):continue
            lowtextures+=1
            for entry in byid.get(tid,[]):
                members=[n for n in arc.files if n.startswith(prefix+entry['file']) and n.endswith('.pcx.m')]
                # file prefixes only admit the exact PCX or a platform suffix.
                members=[n for n in members if n[len(prefix+entry['file'])] in '._']
                high=[]
                for member in members:
                    blob=arc.extract(member)
                    try:
                        im=Image.open(io.BytesIO(blob));im.load()
                        high.append({'member':member,'size':list(im.size),'sha256':sha(blob)})
                    except Exception as error:high.append({'member':member,'decode_error':str(error),'sha256':sha(blob)})
                bound.append({'disc':path.name,'stage':stage,'id':tid,'translated_changed':is_changed,
                              'low_original_sha256':sha(previous[1]) if previous else None,
                              'low_chinese_sha256':sha(data),'official_hd':high})
        results.append({'disc':path.name,'assets_by_extension':dict(totals),'low_texture_occurrences':lowtextures,'changed_assets':changed})
    report={'schema':1,'scope':'all structurally parsed STAGE.DIR assets and all matching official texture records',
            'discs':results,'official_hd_bindings':bound,'unclassified_changes':unknown,
            'changed_pcx_occurrences':sum(r['translated_changed'] for r in bound),
            'remaining_external_containers':['DEMO.DAT','VOX.DAT','ZMOVIE.STR'],
            'claim_limit':'STAGE results do not prove external containers have no changed images.'}
    (args.audit/'texture-comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print('HD bindings',len(bound),'changed PCX bindings',report['changed_pcx_occurrences'],'unclassified stage changes',len(unknown))


if __name__=='__main__':main()
