#!/usr/bin/env python3
"""Execute the supplied game's x64 halfwidth renderer against generated data.

Requires Unicorn. This checks the real native routine, including row strides
and both metadata bytes. It does not replace a Windows in-game playtest.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
from unicorn import Uc, UC_ARCH_X86, UC_MODE_64, UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_RCX, UC_X86_REG_RDX, UC_X86_REG_R8, UC_X86_REG_R9, UC_X86_REG_RSP, UC_X86_REG_RAX, UC_X86_REG_RIP


def render(exe,font,code):
    uc=Uc(UC_ARCH_X86,UC_MODE_64)
    entry=0x1401079f0;code_base=0x140107000;stop=code_base+0x2000
    uc.mem_map(code_base,0x3000)
    uc.mem_write(code_base,exe[0x107000-0xc00:0x109000-0xc00])
    obj=0x1000000;data=0x1100000;output=0x1200000;stack=0x1300000
    for base in [obj,data,output,stack]:uc.mem_map(base,0x10000)
    uc.mem_write(data,font)
    uc.mem_write(obj+8,struct.pack('<Q',data))
    uc.mem_write(obj+0x30,struct.pack('<Q',output))
    rsp=stack+0x8000
    uc.mem_write(rsp,struct.pack('<Q',stop))
    uc.mem_write(rsp+0x28,struct.pack('<H',code))
    for reg,value in [(UC_X86_REG_RCX,obj),(UC_X86_REG_RDX,0),(UC_X86_REG_R8,0),(UC_X86_REG_R9,40),(UC_X86_REG_RSP,rsp)]:uc.reg_write(reg,value)
    uc.emu_start(entry,stop,count=100000)
    return bytes(uc.mem_read(output,320*120))


def match_all(exe,font,shapes):
    uc=Uc(UC_ARCH_X86,UC_MODE_64);entry=0x140107f80
    code_base=0x140107000;stop=code_base+0x2000
    uc.mem_map(code_base,0x3000);uc.mem_write(code_base,exe[0x107000-0xc00:0x109000-0xc00])
    obj=0x1000000;data=0x1100000;input_=0x1200000;stack=0x1300000;indices=0x1400000
    for base in [obj,data,input_,stack,indices]:uc.mem_map(base,0x100000)
    uc.mem_map(0x141bca000,0x1000);uc.mem_write(0x141bca428,struct.pack('<Q',obj))
    uc.mem_write(data,font);uc.mem_write(obj+0x28,struct.pack('<Q',data));uc.mem_write(obj+0x38,struct.pack('<I',len(font)//36))
    bank=3;vector=obj+0x40+bank*24
    uc.mem_write(vector,struct.pack('<3Q',indices,indices,indices+0x100000))
    rsp=stack+0x8000;uc.mem_write(rsp,struct.pack('<Q',stop))
    keys={font[i:i+36]:i//36 for i in reversed(range(0,len(font),36))}
    for shape in shapes:
        uc.mem_write(input_,shape)
        for reg,value in [(UC_X86_REG_RCX,bank),(UC_X86_REG_RDX,input_),(UC_X86_REG_RSP,rsp)]:uc.reg_write(reg,value)
        uc.emu_start(entry,stop,count=400000)
        assert uc.reg_read(UC_X86_REG_RIP)==stop,'native matcher did not complete'
        found=uc.reg_read(UC_X86_REG_RAX)&0xffffffff
        assert found==keys.get(shape,0xffffffff),'native exact key matcher disagrees'
        assert found!=0xffffffff,'translated glyph is missing in native font table'
    assert struct.unpack('<Q',uc.mem_read(vector+8,8))[0]==indices+2*len(shapes)
    return len(shapes)


def registration(exe, data, font_type):
    """Execute actual entryMGSFontData; stub only Binary conversion and queue."""
    uc = Uc(UC_ARCH_X86, UC_MODE_64)
    base = 0x140000000
    uc.mem_map(base, 0x50000)
    uc.mem_write(base + 0x1000, exe[0x400:0x4f400])
    helper, queue, entry, stop = base+0x4c60, base+0x2d2a0, base+0x2b020, base+0x40000
    uc.mem_write(helper, b'\xc3'); uc.mem_write(queue, b'\xc3')
    object_, vm, binary, values, native_task = [0x1000000+i*0x10000 for i in range(5)]
    replacement, stack = 0x1100000, 0x1800000
    uc.mem_map(0x1000000, 0x100000)
    uc.mem_map(replacement, (len(data)+0xfff)//0x1000*0x1000)
    uc.mem_map(stack, 0x10000)
    uc.mem_write(replacement, data)
    uc.mem_write(object_+0x1b0, struct.pack('<Q', native_task))
    uc.mem_write(native_task+8, struct.pack('<2Q', 0x111, 0x222))
    uc.mem_write(vm+0x30, struct.pack('<Q', values))
    uc.mem_write(vm+0x54, struct.pack('<I', 0))
    uc.mem_write(values+16, struct.pack('<IIQ', 0x5000002, 0, font_type))
    original = bytes(0x80)
    uc.mem_write(binary, original)
    uc.mem_write(binary+0x50, struct.pack('<QI', replacement, len(data)))
    rsp = stack+0x8000
    uc.mem_write(rsp, struct.pack('<Q', stop))
    captured = []
    def intercept(machine, address, size, context):
        if address == helper:
            out = machine.reg_read(UC_X86_REG_RCX)
            machine.mem_write(out, struct.pack('<Q', binary))
            machine.reg_write(UC_X86_REG_RAX, out)
        elif address == queue:
            sp = machine.reg_read(UC_X86_REG_RSP)
            pointer = struct.unpack('<Q', machine.mem_read(sp+0x28, 8))[0]
            length = struct.unpack('<I', machine.mem_read(sp+0x30, 4))[0]
            assert machine.reg_read(UC_X86_REG_R8) == 0x1000e
            assert machine.reg_read(UC_X86_REG_R9) == font_type
            assert pointer == replacement and length == len(data)
            assert bytes(machine.mem_read(pointer, length)) == data
            captured.append(length)
    uc.hook_add(UC_HOOK_CODE, intercept)
    for reg, value in [(UC_X86_REG_RCX, object_), (UC_X86_REG_RDX, vm), (UC_X86_REG_RSP, rsp)]:
        uc.reg_write(reg, value)
    uc.emu_start(entry, stop, count=1000)
    assert captured == [len(data)]
    # The C++ scoped override has an independently tested unwind/restoration.
    uc.mem_write(binary, original)
    assert bytes(uc.mem_read(binary, 0x80)) == original
    return {'type': font_type, 'bytes': len(data), 'native_registration': '0x14002B020',
            'stubbed_boundaries': ['Binary conversion', 'emulator command queue'], 'status': 'pass'}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--game',type=Path,required=True)
    ap.add_argument('--fonts',type=Path,required=True)
    ap.add_argument('--audit',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args();exe=(args.game/'METAL GEAR SOLID.exe').read_bytes()
    assert hashlib.sha256(exe).hexdigest()=='e320062847ec71a52292e9931bcf2ee33ea6586429ecb2a38e567ab37b66c373','unsupported executable'
    results=[]
    for path in sorted(args.fonts.glob('cn_*hankaku_4x.bin')):
        font=path.read_bytes();assert len(font)==112*578
        for code in range(32,128):
            record=font[(code-32)*578:(code-31)*578];width,y_offset=record[:2]
            assert width==24
            assert not any(record[2+width*48//4:]),'image must be packed at its actual width; padding trails the image'
            expected=bytearray(320*120)
            raw=record[2:2+width*48//4]
            values=[(b>>(6-2*k))&3 for b in raw for k in range(4)]
            for row in range(48):expected[(row+y_offset)*320:(row+y_offset)*320+width]=bytes(values[row*width:(row+1)*width])
            assert render(exe,font,code)==expected,f'native glyph differs: {path.name}, {code:#x}'
        results.append({'file':path.name,'sha256':hashlib.sha256(font).hexdigest(),'glyphs_checked':96,'native_renderer':'0x1401079F0','status':'pass'})
    shapes=[bytes.fromhex(r['shape_hex']) for r in json.loads((args.audit/'resources.json').read_text())['glyphs']]
    matches=[]
    for path in sorted(args.fonts.glob('cn_*fontall.bin')):
        checked=match_all(exe,path.read_bytes(),shapes)
        matches.append({'file':path.name,'translated_glyphs_checked':checked,'native_matcher':'0x140107F80','status':'pass'})
    registrations=[]
    reader=bytes.fromhex('8b4258448bcb488b8fb001000041b80e00010089442428488b42504889442420')
    assert exe[0x2b077-0xc00:0x2b077-0xc00+len(reader)]==reader
    for prefix in ['cn_','cn_vr_']:
        for suffix,type_ in [('hankaku_4x.bin',0),('kanji_4x.bin',1),('fontall.bin',4)]:
            path=args.fonts/(prefix+suffix)
            registrations.append({'file':path.name,**registration(exe,path.read_bytes(),type_)})
    result={'halfwidth':results,'translated_key_matching':matches,'runtime_registration':registrations,'runtime_playtest':False}
    args.out.write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))


if __name__=='__main__':main()
