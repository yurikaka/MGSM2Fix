#pragma once
#include <algorithm>
#include <array>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <limits>
#include <map>
#include <set>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>
#include <nlohmann/json.hpp>

// The retail text decoder dispatches this interval. Code assignments, label
// lengths, glyph codes and guest rasterizer call sites come from the manifest.
struct ExternalDynamicCodeProfile {
    struct Rule {
        unsigned code = 0, slotBytes = 0;
        std::array<std::vector<std::uint8_t>, 6> labels;
    };
    struct Glyph {
        unsigned code = 0;
        std::array<std::uint8_t, 576> high{}, dot{};
        std::array<std::uint8_t, 36> low{};
    };
    unsigned title = 0;
    std::string version;
    std::set<unsigned> guestFontCalls;
    std::map<unsigned, Rule> rules;
    std::vector<Glyph> glyphs;
    std::map<unsigned, unsigned> glyphIndices;

    static bool IsDynamic(unsigned code) { return code >= 0x8180 && code <= 0x8192; }
    const std::uint8_t *GlyphData(unsigned type, unsigned code, bool high = true) const {
        const auto found = glyphIndices.find(code & 0x9fff);
        if (type != 1 || found == glyphIndices.end()) return nullptr;
        const auto &glyph = glyphs[found->second];
        return high ? glyph.high.data() : glyph.dot.data();
    }
    bool LowGlyphIndex(unsigned code, unsigned &index) const {
        const auto found = glyphIndices.find(code & 0x9fff);
        if (found == glyphIndices.end()) return false;
        index = found->second;
        return true;
    }
    template<class Read, class Write>
    bool Expand(unsigned code, unsigned style, unsigned address, Read read, Write write, unsigned &first) const {
        const auto found = rules.find(code);
        if (found == rules.end() || style >= 6) return false;
        const auto &rule = found->second;
        if (address > std::numeric_limits<unsigned>::max() - (rule.slotBytes-1)) return false;
        std::vector<std::uint8_t> tail(rule.slotBytes-2);
        bool safe = true;
        for (unsigned i = 0; i < tail.size(); ++i) {
            tail[i] = read(address+2+i);
            safe = safe && tail[i] == (i%2 ? 0 : 0x80);
        }
        if (!safe) for (const auto &label : rule.labels)
            if (std::equal(tail.begin(), tail.end(), label.begin()+2)) { safe = true; break; }
        if (!safe) return false;
        const auto &label = rule.labels[style];
        for (unsigned i = 0; i < tail.size(); ++i) write(address+2+i, label[i+2]);
        first = (unsigned(label[0]) << 8) | label[1];
        return true;
    }
};

struct ExternalDynamicCodes {
    std::vector<ExternalDynamicCodeProfile> profiles;
    const ExternalDynamicCodeProfile *Find(unsigned title, const std::string &version) const {
        for (const auto &profile : profiles)
            if (profile.title == title && profile.version == version) return &profile;
        return nullptr;
    }
    static unsigned Number(const nlohmann::json &value) {
        if (value.is_number_unsigned()) {
            const auto n = value.get<std::uint64_t>();
            if (n <= std::numeric_limits<unsigned>::max()) return static_cast<unsigned>(n);
        } else if (value.is_number_integer()) {
            const auto n = value.get<std::int64_t>();
            if (n >= 0 && n <= std::numeric_limits<unsigned>::max()) return static_cast<unsigned>(n);
        } else if (value.is_string()) {
            const auto text = value.get<std::string>();
            if (text.size() > 2 && text[0] == '0' && (text[1] == 'x' || text[1] == 'X')
                && text.find_first_not_of("0123456789abcdefABCDEF",2) == std::string::npos) {
                std::size_t consumed = 0;
                const auto n = std::stoull(text, &consumed, 16);
                if (consumed == text.size() && n <= std::numeric_limits<unsigned>::max()) return static_cast<unsigned>(n);
            }
        }
        throw std::runtime_error("dynamic code fields must be unsigned integers or hexadecimal strings");
    }
    static std::vector<std::uint8_t> Read(const std::filesystem::path &path, std::size_t expected) {
        std::ifstream input(path, std::ios::binary | std::ios::ate);
        if (!input || input.tellg() != static_cast<std::streamoff>(expected))
            throw std::runtime_error("missing or incorrectly sized dynamic glyph bank");
        input.seekg(0);
        std::vector<std::uint8_t> result(expected);
        if (expected && !input.read(reinterpret_cast<char *>(result.data()), expected))
            throw std::runtime_error("cannot read dynamic glyph bank");
        return result;
    }
    static ExternalDynamicCodes Load(const std::filesystem::path &path) {
        std::ifstream input(path, std::ios::binary | std::ios::ate);
        if (!input || input.tellg() <= 0 || input.tellg() > 4*1024*1024)
            throw std::runtime_error("missing or oversized dynamic code manifest");
        input.seekg(0);
        const auto root = nlohmann::json::parse(input);
        if (Number(root.at("schema")) != 1 || !root.at("profiles").is_array() || root.at("profiles").size() > 64)
            throw std::runtime_error("invalid dynamic code manifest schema/profiles");
        ExternalDynamicCodes result;
        std::set<std::pair<unsigned,std::string>> keys;
        for (const auto &item : root.at("profiles")) {
            ExternalDynamicCodeProfile profile;
            profile.title = Number(item.at("title"));
            profile.version = item.at("version").get<std::string>();
            if (profile.version.empty() || !keys.emplace(profile.title,profile.version).second)
                throw std::runtime_error("empty or duplicate dynamic code profile");
            if (item.contains("guest_font_calls")) {
                if (!item.at("guest_font_calls").is_array()) throw std::runtime_error("guest_font_calls must be an array");
                for (const auto &call : item.at("guest_font_calls")) {
                    const unsigned address = Number(call);
                    if (address > 0x1fffff || address%4 || !profile.guestFontCalls.insert(address).second)
                        throw std::runtime_error("invalid or duplicate guest font call");
                }
            }
            if (item.contains("glyph_banks")) {
                if (!item.at("glyph_banks").is_array()) throw std::runtime_error("glyph_banks must be an array");
                for (const auto &bank : item.at("glyph_banks")) {
                    const auto first = Number(bank.at("first_code")), count = Number(bank.at("count"));
                    if (!count || count > 4096 || profile.glyphs.size()+count > 4096
                        || first < 0x8100 || first > 0x9fff || count-1 > 0x9fff-first)
                        throw std::runtime_error("invalid dynamic glyph bank range");
                    auto high = Read(path.parent_path()/std::filesystem::u8path(bank.at("hd").get<std::string>()), count*576);
                    auto low = Read(path.parent_path()/std::filesystem::u8path(bank.at("low").get<std::string>()), count*36);
                    for (unsigned g = 0; g < count; ++g) {
                        ExternalDynamicCodeProfile::Glyph glyph; glyph.code = first+g;
                        if (ExternalDynamicCodeProfile::IsDynamic(glyph.code)
                            || !profile.glyphIndices.emplace(glyph.code,static_cast<unsigned>(profile.glyphs.size())).second)
                            throw std::runtime_error("overlapping glyph bank or dynamic-code collision");
                        std::copy_n(high.begin()+g*576,576,glyph.high.begin());
                        std::copy_n(low.begin()+g*36,36,glyph.low.begin());
                        for (unsigned y = 0; y < 48; ++y) for (unsigned x = 0; x < 48; ++x) {
                            const auto pixel = (glyph.low[(y/4)*3+x/16] >> (6-2*((x/4)%4))) & 3;
                            glyph.dot[y*12+x/4] |= pixel << (6-2*(x%4));
                        }
                        profile.glyphs.push_back(glyph);
                    }
                }
                if (!profile.glyphs.empty() && profile.guestFontCalls.empty())
                    throw std::runtime_error("custom glyph banks require audited guest_font_calls for low-resolution rendering");
            }
            if (!item.at("codes").is_array() || item.at("codes").empty() || item.at("codes").size() > 19)
                throw std::runtime_error("invalid dynamic code rule list");
            static const char *styles[] = {"PS","PS_SWAP","NX","XBOX","STEAM","PS5"};
            for (const auto &entry : item.at("codes")) {
                ExternalDynamicCodeProfile::Rule rule;
                rule.code = Number(entry.at("code")); rule.slotBytes = Number(entry.at("slot_bytes"));
                if (!ExternalDynamicCodeProfile::IsDynamic(rule.code) || rule.slotBytes < 2 || rule.slotBytes > 254 || rule.slotBytes%2)
                    throw std::runtime_error("unsupported dynamic code or invalid slot_bytes");
                const auto &labels = entry.at("labels");
                if (!labels.is_object() || labels.size() != 6) throw std::runtime_error("exactly six platform labels are required");
                for (unsigned s = 0; s < 6; ++s) {
                    const auto &label = labels.at(styles[s]);
                    if (!label.is_array() || label.empty() || label.size()*2 > rule.slotBytes)
                        throw std::runtime_error("empty or oversized dynamic label");
                    auto &bytes = rule.labels[s];
                    for (const auto &token : label) {
                        const unsigned code = Number(token);
                        if (code < 0x8020 || code > 0x9fff || ExternalDynamicCodeProfile::IsDynamic(code))
                            throw std::runtime_error("labels require static glyph codes, without terminators or dynamic recursion");
                        bytes.push_back(code >> 8); bytes.push_back(code & 255);
                    }
                    while (bytes.size() < rule.slotBytes) { bytes.push_back(0x80); bytes.push_back(0); }
                }
                if (!profile.rules.emplace(rule.code,std::move(rule)).second)
                    throw std::runtime_error("duplicate dynamic code rule");
            }
            result.profiles.push_back(std::move(profile));
        }
        return result;
    }
};
