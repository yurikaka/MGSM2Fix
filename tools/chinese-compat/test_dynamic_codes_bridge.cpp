// Regression bridge for executing configurable C++ expansion in native emulation.
#include "../../src/m2fix/external_dynamic_codes.h"
#include <optional>
static std::optional<ExternalDynamicCodes> config;
extern "C" int select_load(const char *path) {
    try { config = ExternalDynamicCodes::Load(path); return config->Find(99,"INTEGRAL") != nullptr; }
    catch (...) { config.reset(); return 0; }
}
extern "C" int select_expand(unsigned style, unsigned char *bytes, unsigned length, unsigned *first) {
    try {
        if (!config || length < 2) return 0;
        const auto *profile=config->Find(99,"INTEGRAL");
        auto read=[&](unsigned at){if(at>=length)throw std::runtime_error("read bounds");return bytes[at];};
        auto write=[&](unsigned at,unsigned char v){if(at>=length)throw std::runtime_error("write bounds");bytes[at]=v;};
        return profile->Expand((unsigned(bytes[0])<<8)|bytes[1],style,0,read,write,*first);
    } catch (...) { return 0; }
}

extern "C" int dynamic_read_low(unsigned offset, unsigned char *value) {
    const auto *p=config ? config->Find(99,"INTEGRAL") : nullptr;
    return p && p->ReadLowGlyph(offset,*value);
}
