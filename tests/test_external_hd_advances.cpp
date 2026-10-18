#include "../src/m2fix/external_hd_font.h"
#include <cassert>

int main() {
    const auto dir = std::filesystem::temp_directory_path() / "mgsm2fix-hd-advances-test";
    std::filesystem::create_directories(dir);
    const auto path = dir / "advances.json";
    std::filesystem::remove(path);
    auto rules = ExternalHDAdvanceRules::Load(path);
    assert(rules.AdjustCode('e', 8, true) == 8);
    auto write = [&](const char *json) { std::ofstream(path) << json; };
    write(R"({"schema":1,"overrides":[{"glyph_index":69,"from":8,"to":7},{"glyph_index":80,"from":8,"to":7},{"glyph_index":33,"from":9,"to":6}]})");
    rules = ExternalHDAdvanceRules::Load(path);
    for (unsigned code = 32; code <= 128; ++code) {
        assert(rules.AdjustCode(code, 8, false) == 8);
        assert(rules.AdjustCode(code, 8, true) == ((code == 'e' || code == 'p') ? 7u : 8u));
    }
    assert(rules.AdjustCode('A', 9, true) == 6); // config-driven, not e/p-only
    assert(rules.AdjustCode('e', 6, true) == 6);
    assert(rules.AdjustCode('e', 7, true) == 7); // no double correction
    assert(rules.AdjustCode(0, 0, true) == 0);
    assert(rules.AdjustCode(255, 0, true) == 0);
    assert(rules.AdjustCode(135, 8, true) == 7); // guest's high-byte alias
    assert(rules.AdjustIndex(112, 8, true) == 8);
    ExternalHDAdvance::Register("INTEGRAL", rules);
    assert(ExternalHDAdvance::release == 1);
    ExternalHDAdvance::Register("VR-DISK", rules);
    assert(ExternalHDAdvance::release == 2);
    ExternalHDAdvance::Reset();
    assert(!ExternalHDAdvance::release);
    assert(ExternalHDAdvance::rules.AdjustCode('e', 8, true) == 8);
    for (const char *bad : {
        R"({"schema":2,"overrides":[]})",
        R"({"schema":1,"overrides":[{"glyph_index":112,"from":8,"to":7}]})",
        R"({"schema":1,"overrides":[{"glyph_index":69,"from":8,"to":0}]})",
        R"({"schema":1,"overrides":[{"glyph_index":69,"from":8,"to":16}]})",
        R"({"schema":1,"overrides":[{"glyph_index":-1,"from":8,"to":7}]})",
        R"({"schema":1,"overrides":[{"glyph_index":69,"from":8.5,"to":7}]})",
        R"({"schema":1,"overrides":[{"glyph_index":69,"from":8,"to":7},{"glyph_index":69,"from":8,"to":6}]})"
    }) {
        write(bad);
        bool rejected = false;
        try { ExternalHDAdvanceRules::Load(path); } catch (const std::exception &) { rejected = true; }
        assert(rejected);
    }
    std::filesystem::remove_all(dir);
}
