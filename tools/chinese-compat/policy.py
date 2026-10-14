#!/usr/bin/env python3
"""Generate scoped whole-record exclusions and exhaustive keep/block lists.

Do not split instructions or strings at individual conflicting bytes: a record
is the atomic unit. Exact byte conflicts remain available in byte-conflicts.json.
"""
import argparse
import csv
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'integral-english'))
from m2archive import Archive,Psb
from resources import assets,fonts

FONT_ENTRIES={'INTEGRAL':[0x44bc0,0x4659c,0x46644,0x4679c,0x4544c,0x459b0,0x468fc,0x4695c],
              'VR-DISK':[0x44c88,0x46664,0x4670c,0x46864,0x45514,0x45a78,0x469c4,0x46a24]}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--audit',type=Path,required=True)
    args=ap.parse_args()
    doc=json.loads((args.audit/'byte-conflicts.json').read_text())
    resources=json.loads((args.audit/'resources.json').read_text())
    policy={'schema':1,'range_convention':'[start,end)','scope':'supplied CN.ppf hashes only','ram':[],'cd':[],'font':[],'texture':[],'inputs':[]}
    rows=[]
    for disc in doc['discs']:
        version,disk=disc['version'],disc['disk']
        common={'title':99,'version':version,'disk':disk}
        policy['inputs'].append({**common,'ppf':disc['ppf'],'sha256':disc['sha256']})
        stage_entry=next(f for f in disc['files'] if 'STAGE.DIR' in f['name'])
        prefix=f'{version}-{disk}'
        stage_data=(args.audit/f'{prefix}-MGS_STAGE.DIR_1-original.bin').read_bytes()
        stage_assets=list(assets(stage_data))
        for patch in disc['patches']:
            conflicting=bool(patch['conflict_ranges'])
            if conflicting:
                rule={**common,'start':patch['offset'],'end':patch['end']}
                if rule not in policy[patch['kind']]:policy[patch['kind']].append(rule)
            locations=[]
            if patch['kind']=='ram':
                if patch['offset']==0x200000:purpose='扩展 RAM：合集控制菜单、手柄参数、奖杯事件接口'
                elif 'item_text' in (patch['file'] or ''):purpose='物品/武器说明文字表：官方按钮标记及布局；汉化中文说明'
                elif 'codec_' in (patch['file'] or ''):purpose='Codec 按键提示：官方平台对应按钮图标'
                elif patch['length']==14:purpose='存储卡相关提示：官方存储空间措辞；汉化中文提示'
                else:purpose='英文 STORAGE/SELECT STORAGE 提示及留白'
            else:
                for f in disc['files']:
                    if f['lba']*2352<=patch['offset']<(f['lba']+(f['size']+2047)//2048)*2352:
                        sector,pos=divmod(patch['offset'],2352)
                        logical=(sector-f['lba'])*2048+pos-24
                        locations.append(f"{f['name']}+0x{logical:X}")
                        if 'STAGE.DIR' in f['name']:
                            for stage,tid,ext,off,blob in stage_assets:
                                if off<=logical<off+len(blob):
                                    locations.append(f'{stage}/{tid:04x}.{chr(ext)}+0x{logical-off:X}')
                if patch['file']:
                    purpose='合集平台按钮提示、换盘/存储提示文字或字体资源；整块回写可恢复原文'
                    if patch['file'].startswith('font_'):purpose='官方字体/字宽资源；与汉化重新编码的字形和度量冲突'
                elif patch['length'] in (6,8,14):purpose='官方存储/按键提示文字；汉化替换为中文提示'
                else:purpose='官方程序或脚本字节；内容见精确比较，尚需逐指令语义校验'
            rows.append({'version':version,'disk':disk,'kind':patch['kind'],'index':patch['index'],'file':patch['file'] or '<inline>','start':f"0x{patch['offset']:X}",'end':f"0x{patch['end']:X}",'bytes':patch['length'],'action':'disable' if conflicting else 'keep','conflict_bytes':sum(b-a for a,b in patch['conflict_ranges']),'conflict_ranges':'; '.join(f'0x{a:X}..0x{b:X}' for a,b in patch['conflict_ranges']),'location':'; '.join(locations),'purpose':purpose})
        # These entries form one font pipeline: setting either bank, rendering
        # its indices, uploading and flushing the resulting texture. Existing
        # native glyph lookup lacks every translated bitmap, so falling back
        # for just the changed MIPS instructions would still lose Chinese.
        for address in FONT_ENTRIES[version]:
            policy['font'].append({**common,'start':address,'end':address+1})
    for texture in resources['textures']:
        version,disk=texture['disc'].rsplit('-',1)
        rule={'title':99,'version':version,'disk':int(disk),'start':texture['id'],'end':texture['id']+1}
        if rule not in policy['texture']:policy['texture'].append(rule)
    (args.audit/'manifest.json').write_text(json.dumps(policy,ensure_ascii=False,indent=2))
    with (args.audit/'patch-decisions.csv').open('w',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    lines=['# 汉化兼容：全部官方补丁决策','', '地址为半开区间 `[start,end)`。RAM 是物理 RAM 偏移；CD 是 PPF 原始 2352 字节光盘地址。','', '冲突判据：PPF 明确写入的字节与官方目标字节不同。禁用的最小安全单位为一条官方补丁记录，避免拼接出半条指令或半个字符。平台文件变体分别列出，不能把变体总数当成同时应用的补丁数量。','']
    for version,disk in [(d['version'],d['disk']) for d in doc['discs']]:
        subset=[r for r in rows if r['version']==version and r['disk']==disk]
        lines += [f'## {version} / disk {disk}','', '| 类别 | 官方记录数 | 禁用 | 保留 |','|---|---:|---:|---:|']
        for kind in ['ram','cd']:
            records={r['index']:r['action'] for r in subset if r['kind']==kind}
            lines.append(f"| {kind} | {len(records)} | {sum(a=='disable' for a in records.values())} | {sum(a=='keep' for a in records.values())} |")
        lines += ['', '| 决策 | 类别 | 表索引 | 地址段 | 数据来源 | 位置 | 作用 |','|---|---|---:|---|---|---|---|']
        grouped={}
        for row in subset:
            key=(row['index'],row['kind'],row['start'],row['end'],row['action'])
            grouped.setdefault(key,[]).append(row)
        for key,group in grouped.items():
            r=group[0];source=r['file'] if len(group)==1 else r['file'].split('_NX')[0]+'：全部 '+str(len(group))+' 种平台变体'
            lines.append(f"| {r['action']} | {r['kind']} | {r['index']} | {r['start']}..{r['end']} | {source} | {r['location']} | {r['purpose']} |")
        lines += ['', '原始高清字体尚不包含汉化字形：该发行版八个字体处理入口暂时回退到客机流程。其他版本的字体加速和所有未改变的纹理 ID 均可保留。安装经过验证的新高清字库后，字体回退清单需要相应缩减。','']
    (args.audit/'patch-decisions.md').write_text('\n'.join(lines))
    print('policy', {k:len(policy[k]) for k in ['ram','cd','font','texture']})


if __name__=='__main__':main()
