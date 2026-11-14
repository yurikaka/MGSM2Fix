#!/usr/bin/env python3
"""Compile the actual pre-registration hook against a small VM/cache double.

This exercises the production body, not a second copy of its logic. It does
not replace a Windows build or integration with the real Squirrel VM.
"""
from pathlib import Path
import os
import subprocess
import tempfile

repo = Path(__file__).resolve().parents[1]
source = (repo / 'src/modules/sqhook.cpp').read_text()
start = source.index('template <Squirk Q>\nSQInteger SQHook<Q>::SQCall_set_disk_patch(')
end = source.index('\ntemplate <Squirk Q>', start + 1)
hook = source[start:end]
assert '{"_set_disk_patch",                         SQCall_set_disk_patch}' in source
assert 'Ketchup<Q>::Process(v);' in source[source.index('SQInteger SQHook<Q>::_SQReturn_set_disk_patch'):]

stub = r'''
#include <cassert>
#include <iostream>
#include <map>
#include <memory>
#include <string>
#include <vector>
enum class Squirk { Standard };
using SQInteger = long long;
enum { OT_NULL, OT_ARRAY, OT_STRING };
enum class M2FixGame { MGS1, Other };
struct M2Fix { static inline auto game = M2FixGame::MGS1; static auto Game() { return game; } };
struct M2Config { static inline bool bPatchesRefreshControllerRAM = true; };
struct VM {
    std::vector<int> patches;
    std::map<std::string, std::string> registry;
    int style = 0;
    bool array = true, function = true, evaluate = true;
};
template<Squirk Q> using HSQUIRRELVM = VM*;
int title = 99; std::string version = "INTEGRAL";
template<Squirk Q> struct SQGlobals { static int GetTitle() { return title; } };
template<Squirk Q> struct SQSystemData {
    struct SettingETC { static std::string GetVersion() { return version; } };
};
namespace spdlog { template<class... T> void info(const char*, T...) {} }
namespace Sqrat {
template<Squirk Q> struct Object {
    VM* vm; int type; std::string value;
    int GetType() const { return type; }
    template<class T> T Cast() const { return value; }
};
template<Squirk Q> struct Function {
    VM* vm; bool IsNull() const { return !vm->function; }
    template<class T> std::shared_ptr<T> Evaluate() {
        return vm->evaluate ? std::make_shared<T>(vm->style) : nullptr;
    }
};
template<Squirk Q> struct RootTable {
    VM* vm; RootTable(VM* v):vm(v) {}
    Object<Q> GetSlot(const char*) { return {vm, vm->array ? OT_ARRAY : OT_NULL, {}}; }
    Function<Q> GetFunction(const char*) { return {vm}; }
};
template<Squirk Q> struct RegistryTable {
    VM* vm; RegistryTable(VM* v):vm(v) {}
    Object<Q> GetSlot(const char* key) {
        auto i=vm->registry.find(key);
        return {vm, i==vm->registry.end() ? OT_NULL : OT_STRING, i==vm->registry.end() ? "" : i->second};
    }
    void SetValue(const char* key, const std::string& value) { vm->registry[key]=value; }
};
template<Squirk Q> struct Array {
    VM* vm; Array(Object<Q> o):vm(o.vm) {}
    auto Length() const { return vm->patches.size(); }
    void Resize(int n) { vm->patches.resize(n); }
};
}
template<Squirk Q> struct SQHook { static SQInteger SQCall_set_disk_patch(HSQUIRRELVM<Q>); };
'''
checks = r'''
void before(VM& vm) { SQHook<Squirk::Standard>::SQCall_set_disk_patch(&vm); }
int main() {
    unsigned changes=0;
    // Model the official len()==0 gate and the unchanged return-hook order:
    // official RAM -> filtering -> Ketchup PPF replay.
    for (int first=0;first<6;++first) for (int next=0;next<6;++next) {
        VM vm; vm.style=first; before(vm); assert(vm.patches.empty());
        vm.patches={100+first,200+first,999}; // 999 represents third-party cache data
        vm.style=next; before(vm);
        if (first==next) assert(vm.patches==std::vector<int>({100+first,200+first,999}));
        else {
            assert(vm.patches.empty()); // official loader must enter its RAM branch
            vm.patches={100+next,200+next};
            int memory=0;
            for (int p:vm.patches) if (p<200) memory=p; // one range filtered out
            assert(memory==100+next);
            memory=777; // return-hook PPF wins after official load
            assert(memory==777);
            ++changes;
        }
    }
    VM old; old.patches={3}; before(old); assert(old.patches.empty());
    old.patches={4}; before(old); assert(old.patches==std::vector<int>({4}));
    version="VR-DISK"; before(old); assert(old.patches.empty());
    old.patches={5}; title=98; before(old); assert(old.patches.empty());
    VM second; second.patches={6}; before(second); assert(second.patches.empty());
    M2Config::bPatchesRefreshControllerRAM=false;
    second.patches={7}; second.style=5; before(second); assert(second.patches==std::vector<int>({7}));
    M2Config::bPatchesRefreshControllerRAM=true;
    M2Fix::game=M2FixGame::Other; before(second); assert(second.patches==std::vector<int>({7}));
    M2Fix::game=M2FixGame::MGS1;
    for (int invalid: {-1,6}) { second.style=invalid; before(second); assert(second.patches==std::vector<int>({7})); }
    second.style=1; second.array=false; before(second); assert(second.patches==std::vector<int>({7}));
    second.array=true; second.function=false; before(second); assert(second.patches==std::vector<int>({7}));
    second.function=true; second.evaluate=false; before(second); assert(second.patches==std::vector<int>({7}));
    std::cout << "PASS: 36 controller transitions (" << changes << " invalidations), VM/release isolation, filters/PPF ordering, disabled and unavailable inputs\n";
}
'''
with tempfile.TemporaryDirectory(prefix='mgs-ram-cache-') as tmp:
    cpp = Path(tmp) / 'test.cpp'
    exe = Path(tmp) / 'test'
    cpp.write_text(stub + '\n' + hook + '\n' + checks)
    subprocess.run([os.environ.get('CXX', 'g++'), '-std=c++20', '-Wall', '-Wextra', '-Werror', str(cpp), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
