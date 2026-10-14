#!/usr/bin/env python3
"""Transfer reviewed Unicode identities by bitmap hash, never inventory index."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action',choices=['export','apply'])
    ap.add_argument('--audit',type=Path,required=True)
    ap.add_argument('--mapping',type=Path,default=Path(__file__).with_name('reviewed-glyphs.json'))
    args=ap.parse_args();rows=json.loads((args.audit/'resources.json').read_text())['glyphs']
    keys=[hashlib.sha256(bytes.fromhex(r['shape_hex'])).hexdigest() for r in rows]
    assert len(set(keys))==len(keys)
    if args.action=='export':
        approved=json.loads((args.audit/'approved-unicode.json').read_text())
        doc={'schema':1,'key':'SHA-256 of the exact 36-byte guest bitmap','review':'Glyph images and in-game Chinese contexts; OCR is a candidate, not approval',
             'unicode':{keys[int(i)]:char for i,char in approved.items()},'traced_keys':[keys[i] for i in range(len(keys)) if str(i)not in approved]}
        args.mapping.write_text(json.dumps(doc,ensure_ascii=False,indent=2));print('exported',len(doc['unicode']),'Unicode identities',len(doc['traced_keys']),'traced shapes')
    else:
        doc=json.loads(args.mapping.read_text());assert doc['schema']==1
        allowed=set(doc['unicode'])|set(doc['traced_keys'])
        missing=[i for i,key in enumerate(keys) if key not in allowed]
        assert not missing,'unreviewed glyphs: '+str(missing)
        approved={str(i):doc['unicode'][key] for i,key in enumerate(keys) if key in doc['unicode']}
        (args.audit/'approved-unicode.json').write_text(json.dumps(approved,ensure_ascii=False,indent=2));print('applied',len(approved),'identities by hash')


if __name__=='__main__':main()
