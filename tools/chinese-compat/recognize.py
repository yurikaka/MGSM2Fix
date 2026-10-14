#!/usr/bin/env python3
"""Produce reviewable Unicode candidates; OCR is never an approved mapping."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import subprocess
from PIL import Image


def bitmap(shape):
    raw=bytes.fromhex(shape)
    im=Image.new('L',(12,12))
    im.putdata([255-((int.from_bytes(raw[y*3:y*3+3],'big')>>(22-2*x))&3)*85 for y in range(12) for x in range(12)])
    return im


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--audit',type=Path,required=True)
    ap.add_argument('--limit',type=int)
    args=ap.parse_args()
    rows=json.loads((args.audit/'glyph-map.json').read_text())
    directory=args.audit/'ocr';directory.mkdir(exist_ok=True)
    def recognize(i):
        path=directory/f'{i:04d}.png'
        im=Image.new('L',(144,144),255)
        im.paste(bitmap(rows[i]['shape_hex']).resize((96,96),Image.Resampling.NEAREST),(24,24))
        im.save(path)
        proc=subprocess.run(['tesseract',str(path),'stdout','--tessdata-dir',str(args.audit.parent/'fonts'),'-l','chi_sim','--psm','10','-c','tessedit_create_tsv=1'],capture_output=True,text=True,check=True)
        tokens=[]
        for line in proc.stdout.splitlines()[1:]:
            fields=line.split('\t')
            if len(fields)==12 and fields[11].strip():
                tokens.append({'text':fields[11],'confidence':float(fields[10])})
        return i,tokens
    indices=[i for i,r in enumerate(rows) if 'unicode' not in r and not r.get('ocr')]
    if args.limit:indices=indices[:args.limit]
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures=[pool.submit(recognize,i) for i in indices]
        for n,future in enumerate(as_completed(futures),1):
            i,tokens=future.result();rows[i]['ocr']=tokens
            if n%100==0:
                print(n,'/',len(indices),flush=True)
                (args.audit/'glyph-map.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
    (args.audit/'glyph-map.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
    print('recognized',len(indices),flush=True)


if __name__=='__main__':main()
