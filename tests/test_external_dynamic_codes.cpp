#include "../src/m2fix/external_dynamic_codes.h"
#include <cassert>

int main() {
    using Json = nlohmann::json;
    const auto dir = std::filesystem::temp_directory_path()/"m2fix-dynamic-code-test";
    std::filesystem::create_directories(dir);
    const auto path = dir/"manifest.json";
    auto write = [](const auto &p, const auto &bytes) {
        std::ofstream out(p, std::ios::binary); out.write(reinterpret_cast<const char *>(bytes.data()), bytes.size());
    };
    write(dir/"hd.bin",std::vector<unsigned char>(2*576,0xa5));
    write(dir/"low.bin",std::vector<unsigned char>(2*36,0x1b));
    Json labels = Json::object();
    for (const auto *style : {"PS","PS_SWAP","NX","XBOX","STEAM","PS5"}) labels[style] = {"0x9e00","0x8041"};
    labels["STEAM"] = {"0x8042","0x9e01","0x8043"};
    Json profile = {{"title",99},{"version","TEST"},{"guest_font_calls",{"0x1000"}},
        {"glyph_banks", {{{"first_code","0x9e00"},{"count",2},{"hd","hd.bin"},{"low","low.bin"}}}},
        {"codes", {{{"code","0x8182"},{"slot_bytes",6},{"labels",labels}}}}};
    Json valid = {{"schema",1},{"profiles",{profile}}};
    auto load = [&](const Json &j) { std::ofstream(path) << j; return ExternalDynamicCodes::Load(path); };
    auto reject = [&](const Json &j) { bool bad = false; try { load(j); } catch (const std::exception &) { bad=true; } assert(bad); };
    const auto config = load(valid);
    const auto *p = config.Find(99,"TEST");
    assert(p && !config.Find(100,"TEST") && !config.Find(99,"OTHER"));
    // Absent remapping is a strict no-op; configured remaps affect only the
    // exact native decoder code/result pair and never alter the native tail.
    assert(p->RemapNativeFirst(0x8190,0x8151)==0x8151);
    auto withRemaps=valid;
    withRemaps["profiles"][0]["native_first_remaps"]={{{"code","0x8190"},{"from","0x8151"},{"to","0x9e00"}}};
    const auto remapped=load(withRemaps);const auto &rp=remapped.profiles[0];
    assert(rp.RemapNativeFirst(0x8190,0x8151)==0x9e00);
    assert(rp.RemapNativeFirst(0x8191,0x8151)==0x8151);
    assert(rp.RemapNativeFirst(0x8190,0x8150)==0x8150);
    auto withTail=valid;
    withTail["profiles"][0]["native_tail_remaps"]={{{"code","0x8185"},{"from","0x823c"},{"to","0x9e00"}}};
    const auto tailConfig=load(withTail);const auto &tp=tailConfig.profiles[0];
    std::array<unsigned char,16> t{{0x81,0x85,0x82,0x3c,0x82,0x1f,0x82,0x53,0x80,0,0x80,0,0x80,0,0x91,0x2a}};
    unsigned tailWrites=0;
    tp.RemapNativeTail(0x8185,0,[&](unsigned i){return t.at(i);},[&](unsigned i,unsigned char v){assert(i==2||i==3);t.at(i)=v;++tailWrites;});
    assert(tailWrites==2 && t[2]==0x9e && t[3]==0 && t[4]==0x82 && t[5]==0x1f && t[14]==0x91 && t[15]==0x2a);
    tp.RemapNativeTail(0x8185,0,[&](unsigned i){return t.at(i);},[&](unsigned,unsigned char){assert(false);});
    tp.RemapNativeTail(0x8184,0,[&](unsigned i){return t.at(i);},[&](unsigned,unsigned char){assert(false);});
    std::array<unsigned char,10> memory{{0x81,0x82,0x80,0,0x80,0,0x91,0x2a,0,0xff}};
    const auto suffix = memory;
    unsigned first = 0, writes = 0;
    auto read = [&](unsigned at) { return memory.at(at); };
    auto put = [&](unsigned at, unsigned char value) { assert(at>=2 && at<6); ++writes; memory.at(at)=value; };
    for (unsigned repeat=0; repeat<5; ++repeat) for (unsigned style=0; style<6; ++style) {
        writes=0; assert(p->Expand(0x8182,style,0,read,put,first)); assert(writes==4);
        assert(first == (style==4 ? 0x8042u : 0x9e00u));
        assert(memory[0]==0x81 && memory[1]==0x82);
        for (unsigned i=6;i<memory.size();++i) assert(memory[i]==suffix[i]);
    }
    const auto saved=memory;
    assert(!p->Expand(0x8186,0,0,read,put,first));
    assert(!p->Expand(0x8182,6,0,read,put,first));
    assert(!p->Expand(0x8182,0,0xfffffffbu,read,put,first));
    assert(memory==saved);
    // An explicitly opted-in retail nine-byte placeholder is normalized
    // without overwriting the following text; later expansions use the usual
    // eight-byte layout and preserve the separator.
    {
        auto j=valid; auto &rule=j["profiles"][0]["codes"][0];
        rule["slot_bytes"]=8; rule["accept_native_nine_byte_slot"]=true;
        auto c=load(j);auto &r=c.profiles[0];
        std::array<unsigned char,12> native{{0x81,0x82,0x20,0x80,0,0x80,0,0x80,0,0x91,0x2a,0xff}};
        const auto original=native;
        for (unsigned repeat=0;repeat<3;++repeat) for (unsigned style=0;style<6;++style) {
            unsigned n=0;
            assert(r.Expand(0x8182,style,0,[&](unsigned at){return native.at(at);},
                [&](unsigned at,unsigned char x){assert(at>=2&&at<=8);native.at(at)=x;++n;},first));
            assert(n==(repeat==0&&style==0?7u:6u));
            assert(native[8]==0x20 && native[9]==original[9] && native[10]==original[10] && native[11]==original[11]);
        }
        for (unsigned at=2;at<=8;++at) {
            auto bad=original;bad[at]^=0x40;const auto before=bad;unsigned n=0;
            assert(!r.Expand(0x8182,0,0,[&](unsigned i){return bad.at(i);},[&](unsigned,unsigned char){++n;},first));
            assert(!n && bad==before);
        }
    }
    for (unsigned i=2;i<6;++i) {
        memory=saved; memory[i]=0x7f; const auto before=memory; writes=0;
        assert(!p->Expand(0x8182,0,0,read,put,first) && writes==0 && memory==before);
    }
    for (unsigned g=0;g<2;++g) {
        unsigned index=99;
        assert(p->LowGlyphIndex(0x9e00+g,index) && index==g);
        assert(p->GlyphData(1,0xde00+g)==p->glyphs[g].high.data());
        assert(p->glyphs[g].high[0]==0xa5 && p->glyphs[g].low[0]==0x1b);
        for (unsigned y=0;y<48;++y) for (unsigned x=0;x<48;++x)
            assert(((p->glyphs[g].dot[y*12+x/4]>>(6-2*(x%4)))&3)==(x/4)%4);
    }
    unsigned char byte=0;
    assert(p->ReadLowGlyph(0,byte) && byte==0x1b);
    assert(p->ReadLowGlyph(71,byte) && byte==0x1b);
    assert(!p->ReadLowGlyph(72,byte) && !p->ReadLowGlyph(0xffffffffu,byte));
    assert(!p->GlyphData(0,0x9e00) && !p->GlyphData(1,0x9e02));
    // Different slot sizes, including a single glyph needing no writable tail.
    for (unsigned slot : {2u,14u,254u}) {
        auto j=valid; auto &r=j["profiles"][0]["codes"][0]; r["slot_bytes"]=slot;
        for (auto &row:r["labels"]) row=Json::array({"0x8041"});
        auto c=load(j); std::vector<unsigned char> b(slot+2,0); b[0]=0x81;b[1]=0x82;
        for (unsigned i=2;i<slot;i+=2) b[i]=0x80;
        b[slot]=0x92;
        assert(c.profiles[0].Expand(0x8182,0,0,[&](unsigned at){return b.at(at);},
            [&](unsigned at,unsigned char v){assert(at<slot);b.at(at)=v;},first));
        assert(first==0x8041 && b[slot]==0x92);
    }
    auto j=valid; j["profiles"].push_back(profile); reject(j);
    j=withRemaps; j["profiles"][0]["native_first_remaps"].push_back(j["profiles"][0]["native_first_remaps"][0]); reject(j);
    j=withRemaps; j["profiles"][0]["native_first_remaps"][0]["code"]="0x8193"; reject(j);
    j=withRemaps; j["profiles"][0]["native_first_remaps"][0]["to"]="0x8186"; reject(j);
    j=withTail; j["profiles"][0]["native_tail_remaps"].push_back(j["profiles"][0]["native_tail_remaps"][0]); reject(j);
    j=withTail; j["profiles"][0]["native_tail_remaps"][0]["from"]="0x8186"; reject(j);
    j=valid; j["profiles"][0]["codes"][0]["accept_native_nine_byte_slot"]=true; reject(j);
    j=valid; j["profiles"][0]["codes"][0]["slot_bytes"]=8; j["profiles"][0]["codes"][0]["accept_native_nine_byte_slot"]="true"; reject(j);
    j=valid; j["profiles"][0]["codes"].push_back(profile["codes"][0]); reject(j);
    j=valid; j["profiles"][0]["glyph_banks"].push_back(profile["glyph_banks"][0]); reject(j);
    j=valid; j["profiles"][0]["guest_font_calls"]=Json::array(); reject(j);
    j=valid; j["profiles"][0]["guest_font_calls"]={"0x1001"}; reject(j);
    j=valid; j["profiles"][0]["codes"][0]["labels"].erase("PS5"); reject(j);
    for (const auto &bad : {Json(0),Json(3),Json(256),Json(-1),Json("0x6xyz")}) {
        j=valid; j["profiles"][0]["codes"][0]["slot_bytes"]=bad; reject(j);
    }
    for (const auto &bad : {Json("0x8186"),Json("0x8000"),Json(0),Json(-1)}) {
        j=valid; j["profiles"][0]["codes"][0]["labels"]["PS"][0]=bad; reject(j);
    }
    j=valid; j["profiles"][0]["glyph_banks"][0]["first_code"]="0x8182"; reject(j);
    j=valid; j["profiles"][0]["codes"][0]["code"]="0x8193"; reject(j);
    j=valid; j["schema"]=2; reject(j);
    write(dir/"low.bin",std::vector<unsigned char>(71)); reject(valid);
    std::filesystem::remove_all(dir);
}
