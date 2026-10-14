#!/usr/bin/env python3
"""Combine texture, stream and initial-RAM comparisons without losing exceptions."""
import argparse
import hashlib
import json
from pathlib import Path


def runs(indices):
    out = []
    for i in indices:
        if out and out[-1][1] == i:
            out[-1][1] += 1
        else:
            out.append([i, i + 1])
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--audit', type=Path, required=True)
    p = ap.parse_args().audit
    textures = json.loads((p / 'texture-comparison.json').read_text())
    streams = json.loads((p / 'stream-resources.json').read_text())
    doc = json.loads((p / 'byte-conflicts.json').read_text())
    ram = []
    for disc in doc['discs']:
        release = f"{disc['version']}-{disc['disk']}"
        original = (p / (release + '-ram-original.bin')).read_bytes()
        chinese = (p / (release + '-ram-cn.bin')).read_bytes()
        assert len(original) == len(chinese)
        changed = [i for i, (a, b) in enumerate(zip(original, chinese)) if a != b]
        text_start, text_end = ((0x10EA0, 0x120F2) if disc['version'] == 'VR-DISK'
                               else (0x10EAC, 0x120FE))
        classified = [(text_start, text_end, 'item/storage/menu text')]
        if disc['version'] == 'INTEGRAL':
            classified.append((0x9E44C, 0x9E481, 'mineDetectorUnusable_8009E44C string'))
        unknown = [i for i in changed if not any(a <= i < b for a, b, _ in classified)]
        assert not unknown, 'new RAM changes require manual classification'
        ram.append({'disc': release, 'changed_bytes': len(changed), 'changed_ranges': runs(changed),
                    'classified_envelopes': [{'range': [a, b], 'role': role} for a, b, role in classified],
                    'unclassified_changed_bytes': len(unknown),
                    'original_sha256': hashlib.sha256(original).hexdigest(),
                    'chinese_sha256': hashlib.sha256(chinese).hexdigest()})
    exceptions = []
    for container in streams['containers']:
        for packet in container['changed_packets']:
            if packet['role'] == 'non-subtitle':
                exceptions.append({'file': container['file'], **packet})
    result = {'schema': 1, 'range_convention': '[start,end)', 'ram': ram,
              'low_texture_occurrences': sum(d['low_texture_occurrences'] for d in textures['discs']),
              'changed_low_texture_occurrences': textures['changed_pcx_occurrences'],
              'official_hd_bindings_checked': len(textures['official_hd_bindings']),
              'unclassified_stage_changes': textures['unclassified_changes'],
              'external_containers_checked': len(streams['containers']),
              'external_uncovered_changed_bytes': sum(c['uncovered_changed_bytes'] for c in streams['containers']),
              'changed_animation_or_movie_pictures': streams['picture_changes'],
              'nonpicture_exceptions': exceptions,
              'action': 'Keep official HD textures and pictures: this PPF has no translated nontext image differences to transplant.',
              'limits': 'The 37-byte VOX audio packet difference is retained verbatim from the supplied PPF; its intended purpose is unknown.'}
    (p / 'nontext-comparison.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print({k: v for k, v in result.items() if k not in ['ram', 'nonpicture_exceptions']})


if __name__ == '__main__':
    main()
