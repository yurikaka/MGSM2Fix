#!/usr/bin/env python3
"""Execute retail x64 PS1 LB/LBU handlers with the external C++ glyph reader.

Reproduces the CPU-only hook bypass and verifies bus reads plus normal RAM.
The hook boundary is simulated; Windows gameplay is not tested.
"""
import argparse,ctypes,hashlib,json,struct
from pathlib import Path
from unicorn import Uc,UC_ARCH_X86,UC_MODE_64,UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_RCX,UC_X86_REG_RDX,UC_X86_REG_R8,UC_X86_REG_RSP,UC_X86_REG_RAX

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('exe','bridge','manifest','out'):ap.add_argument('--'+name,type=Path,required=True)
    a=ap.parse_args();exe=a.exe.read_bytes()
    assert hashlib.sha256(exe).hexdigest()=='e320062847ec71a52292e9931bcf2ee33ea6586429ecb2a38e567ab37b66c373'
    bridge=ctypes.CDLL(str(a.bridge.resolve()));bridge.select_load.argtypes=[ctypes.c_char_p]
    bridge.dynamic_read_low.argtypes=[ctypes.c_uint,ctypes.POINTER(ctypes.c_ubyte)]
    assert bridge.select_load(str(a.manifest.resolve()).encode())==1
    config=json.loads(a.manifest.read_text());p=next(p for p in config['profiles'] if p['title']==99 and p['version']=='INTEGRAL')
    expected=b''.join((a.manifest.parent/b['low']).read_bytes() for b in p['glyph_banks'])
    code=0x140133000;cpu=0x1000000;bus=0x1010000;machine=0x1020000;stack=0x1030000;stub=0x1040000;ram=0x1050000
    virtual=0x1f700000;stop=code+0xff0
    u=Uc(UC_ARCH_X86,UC_MODE_64);u.mem_map(code,0x1000);u.mem_write(code,exe[0x132400:0x133400])
    for at in (cpu,bus,machine,stack,stub,ram):u.mem_map(at,0x10000)
    for offset in (0x100,0x200,0x300):u.mem_write(stub+offset,b'\xc3')
    u.mem_write(cpu+0x10,struct.pack('<Q',bus));u.mem_write(bus,struct.pack('<Q',stub+0x200))
    u.mem_write(bus+0x40,struct.pack('<Q',machine));u.mem_write(cpu+0x38,struct.pack('<Q',stub+0x100));u.mem_write(cpu+0x70,struct.pack('<Q',stub+0x300))
    counters={'cpu':0,'bus':0};enabled=False
    def hook(m,address,size,context):
        if address in (stub+0x100,stub+0x200):
            is_bus=address==stub+0x200;counters['bus' if is_bus else 'cpu']+=1
            assert m.reg_read(UC_X86_REG_RCX)==(machine if is_bus else cpu)
            at=m.reg_read(UC_X86_REG_RDX)&0xffffffff;value=ctypes.c_ubyte()
            matched=bridge.dynamic_read_low((at-virtual)&0xffffffff,ctypes.byref(value))
            m.reg_write(UC_X86_REG_RAX,value.value if matched and (enabled or not is_bus) else 255)
    u.hook_add(UC_HOOK_CODE,hook)
    def run(op,address,bus_hook):
        nonlocal enabled;enabled=bus_hook
        u.mem_write(cpu+0x84,struct.pack('<I',(op<<26)|(5<<21)|(2<<16)))
        u.mem_write(cpu+0x9c+5*4,struct.pack('<I',address))
        sp=stack+0x8000;u.mem_write(sp,struct.pack('<Q',stop))
        for r,v in ((UC_X86_REG_RCX,cpu),(UC_X86_REG_RDX,0),(UC_X86_REG_R8,0x80045124),(UC_X86_REG_RSP,sp)):u.reg_write(r,v)
        u.emu_start(code+(0x8a0 if op==32 else 0x940),stop,count=200)
        return struct.unpack('<I',u.mem_read(cpu+0x9c+2*4,4))[0]
    bad_offset=expected.index(0)
    assert run(36,virtual+bad_offset,False)==255
    assert counters=={'cpu':0,'bus':1},counters
    cases=0
    for op in (32,36):
        for offset,byte in enumerate(expected):
            want=byte if op==36 or byte<128 else byte|0xffffff00
            assert run(op,virtual+offset,True)==want,(op,offset,byte)
            cases+=1
        for address in (virtual-1,virtual+len(expected),0x1f800100):
            assert run(op,address,True)==(255 if op==36 else 0xffffffff);cases+=1
    assert counters['cpu']==0
    bus_count=counters['bus'];u.mem_write(cpu+0x138,struct.pack('<Q',ram));u.mem_write(ram+0x100,b'\x39')
    for op in (32,36):assert run(op,0x80000100,True)==0x39
    assert counters['bus']==bus_count
    report=dict(cpu_only_hook_bypassed=True,old_read_value=255,patched_lb_lbu_cases=cases,
        cpu_read_calls=counters['cpu'],bus_read_calls=counters['bus'],normal_ram_fast_path_unchanged=True,
        boundary='Retail native LB/LBU handlers executed with actual C++ glyph lookup; hook boundary simulated, Windows gameplay not tested.')
    a.out.write_text(json.dumps(report,indent=2));print(json.dumps(report))
if __name__=='__main__':main()
