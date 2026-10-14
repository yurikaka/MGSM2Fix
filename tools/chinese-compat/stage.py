#!/usr/bin/env python3
"""Prepare external runtime fonts and policy in a NEW directory.

Does not open game archives, edit scripts/INI/ASI files, or activate PPFs.
"""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--audit', type=Path, required=True)
    ap.add_argument('--fonts', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    assert not args.out.exists(), 'output must be a new directory; no files will be overwritten'
    files = {}
    for prefix in ['cn_', 'cn_vr_']:
        doc = json.loads((args.fonts / (prefix + 'font-build.json')).read_text())
        for name, info in doc['outputs'].items():
            data = (args.fonts / name).read_bytes()
            assert len(data) == info['size'] and hashlib.sha256(data).hexdigest() == info['sha256']
            files[name] = data
    policy = json.loads((args.audit / 'manifest.json').read_text())
    policy['font'] = []
    policy['texture'] = []
    policy['profile'] = 'runtime External HD font registration; original archives intact'
    files['manifest.json'] = json.dumps(policy, ensure_ascii=False, indent=2).encode()
    files['manifest-fallback.json'] = (args.audit / 'manifest.json').read_bytes()
    files['LICENSE-SourceHanSerif.txt'] = (args.audit.parent / 'fonts/LICENSE-SourceHanSerif.txt').read_bytes()
    files['FONT-ATTRIBUTION.txt'] = b'Chinese glyphs use Adobe Source Han Serif SC Regular under SIL OFL 1.1. Modified raster font names: cn_kanji_4x.bin, cn_vr_kanji_4x.bin. Original collection glyphs retain their original ownership.\n'
    args.out.mkdir(parents=True)
    for name, data in files.items():
        (args.out / name).write_bytes(data)
    print('Prepared external fonts and manifests only:', args.out)


if __name__ == '__main__':
    main()
