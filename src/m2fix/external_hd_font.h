#pragma once
#include <array>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <string>
#include <vector>
#include <nlohmann/json.hpp>

// Audited x64 Binary layout. Borrow replacement data during registration;
// preserve the original allocation and restore both fields on scope exit.
class ScopedExternalFontBuffer {
public:
    ScopedExternalFontBuffer(void *binary, const std::vector<std::uint8_t> &data)
        : object(static_cast<std::uint8_t *>(binary)) {
        std::memcpy(&original, object + 0x50, sizeof(original));
        std::memcpy(&originalSize, object + 0x58, sizeof(originalSize));
        const auto *replacement = data.data();
        auto size = static_cast<std::uint32_t>(data.size());
        std::memcpy(object + 0x50, &replacement, sizeof(replacement));
        std::memcpy(object + 0x58, &size, sizeof(size));
    }
    ~ScopedExternalFontBuffer() {
        std::memcpy(object + 0x50, &original, sizeof(original));
        std::memcpy(object + 0x58, &originalSize, sizeof(originalSize));
    }
    ScopedExternalFontBuffer(const ScopedExternalFontBuffer &) = delete;
    ScopedExternalFontBuffer &operator=(const ScopedExternalFontBuffer &) = delete;
private:
    std::uint8_t *object;
    const std::uint8_t *original;
    std::uint32_t originalSize;
};

// Optional layout metadata; never changes the bitmap or font.res raster stride.
struct ExternalHDAdvanceRules {
    std::array<std::array<std::uint8_t, 16>, 112> overrides{};
    static ExternalHDAdvanceRules Load(const std::filesystem::path &path) {
        ExternalHDAdvanceRules result;
        if (!std::filesystem::exists(path)) return result;
        std::ifstream input(path, std::ios::binary | std::ios::ate);
        if (!input || input.tellg() <= 0 || input.tellg() > 65536)
            throw std::runtime_error("invalid external HD advances file");
        input.seekg(0);
        const auto doc = nlohmann::json::parse(input);
        if (!doc.is_object() || !doc.contains("schema") || !doc["schema"].is_number_integer() || doc["schema"] != 1
            || !doc.contains("overrides") || !doc["overrides"].is_array()
            || doc["overrides"].size() > 112 * 15)
            throw std::runtime_error("invalid external HD advances schema");
        for (const auto &rule : doc["overrides"]) {
            auto number = [&](const char *key, int lo, int hi) {
                if (!rule.is_object() || !rule.contains(key) || !rule[key].is_number_integer()
                    || rule[key] < lo || rule[key] > hi)
                    throw std::runtime_error("invalid external HD advance rule");
                return rule[key].get<unsigned>();
            };
            const unsigned index = number("glyph_index", 0, 111);
            const unsigned from = number("from", 1, 15);
            const unsigned to = number("to", 1, 15);
            if (result.overrides[index][from])
                throw std::runtime_error("duplicate external HD advance rule");
            result.overrides[index][from] = static_cast<std::uint8_t>(to);
        }
        return result;
    }
    unsigned AdjustIndex(unsigned index, unsigned original, bool hd) const {
        if (!hd || index >= overrides.size() || original >= 16) return original;
        const auto width = overrides[index][original];
        return width ? width : original;
    }
    unsigned AdjustCode(unsigned code, unsigned original, bool hd) const {
        // Same normalization as the guest's get_hantable; no language-specific
        // character or desired width is hard-coded in the runtime.
        if (code > 128) code -= 34;
        if (code > 0) code -= 32;
        return AdjustIndex(code, original, hd);
    }
};

struct ExternalHDAdvance {
    static inline unsigned release = 0; // 1: Integral, 2: Japanese VR
    static inline ExternalHDAdvanceRules rules{};
    static void Reset() { release = 0; rules = {}; }
    static void Register(const std::string &version, const ExternalHDAdvanceRules &loaded) {
        Reset();
        if (version == "INTEGRAL") release = 1;
        else if (version == "VR-DISK") release = 2;
        else return;
        rules = loaded;
    }
};

struct ExternalHDFontSet {
    // Keep these buffers alive: native registration may retain their pointers.
    std::array<std::vector<std::uint8_t>, 3> files;
    // Optional expanded resident bank, used by translations with >441 slots.
    // Absent metadata preserves the retail EXE's original index table.
    std::uint32_t fixedBankBase = 0, fixedBankCount = 0;
    ExternalHDAdvanceRules advances;
    static ExternalHDFontSet Load(const std::filesystem::path &directory, const std::string &version) {
        if (version != "INTEGRAL" && version != "VR-DISK")
            throw std::runtime_error("unsupported external font release");
        // Language-neutral layout: <directory>/<release>/<resource>.bin.
        // Retain compatibility with previously generated translation packs.
        const bool releaseDirectory = std::filesystem::is_directory(directory / version);
        const auto fontDirectory = releaseDirectory ? directory / version : directory;
        const std::string prefix = releaseDirectory ? "" : (version == "VR-DISK" ? "cn_vr_" : "cn_");
        const char *names[] = {"hankaku_4x.bin", "kanji_4x.bin", "fontall.bin"};
        ExternalHDFontSet result;
        result.advances = ExternalHDAdvanceRules::Load(fontDirectory / (prefix + "advances.json"));
        for (unsigned i = 0; i < 3; ++i) {
            std::ifstream input(fontDirectory / (prefix + names[i]), std::ios::binary | std::ios::ate);
            if (!input) throw std::runtime_error("missing External HD font: " + prefix + names[i]);
            auto size = input.tellg();
            if (size <= 0 || size > 64 * 1024 * 1024)
                throw std::runtime_error("invalid External HD font size");
            auto &data = result.files[i];
            data.resize(static_cast<std::size_t>(size));
            input.seekg(0);
            if (!input.read(reinterpret_cast<char *>(data.data()), static_cast<std::streamsize>(data.size())))
                throw std::runtime_error("cannot read External HD font");
        }
        if (result.files[0].size() != 112 * 578 || result.files[2].size() % 36 != 0
            || result.files[2].size() / 36 >= 65535
            || result.files[1].size() != result.files[2].size() / 36 * 576)
            throw std::runtime_error("External HD font dimensions disagree");
        std::ifstream mapping(fontDirectory / (prefix + "bank0.bin"), std::ios::binary | std::ios::ate);
        if (mapping) {
            if (mapping.tellg() != 8) throw std::runtime_error("invalid fixed-bank metadata");
            mapping.seekg(0);
            std::array<std::uint8_t, 8> raw{};
            mapping.read(reinterpret_cast<char *>(raw.data()), raw.size());
            auto le32 = [&](unsigned i) { return std::uint32_t(raw[i]) | (std::uint32_t(raw[i+1]) << 8)
                | (std::uint32_t(raw[i+2]) << 16) | (std::uint32_t(raw[i+3]) << 24); };
            result.fixedBankBase = le32(0);
            result.fixedBankCount = le32(4);
            const auto count = result.files[2].size()/36;
            if (!result.fixedBankCount || result.fixedBankBase >= count
                || result.fixedBankCount > count-result.fixedBankBase)
                throw std::runtime_error("fixed-bank mapping exceeds native glyph table");
        }
        return result;
    }
    const std::vector<std::uint8_t> *ForType(unsigned type) const {
        if (type == 0) return &files[0];
        if (type == 1) return &files[1];
        if (type == 4) return &files[2];
        return nullptr;
    }
};
