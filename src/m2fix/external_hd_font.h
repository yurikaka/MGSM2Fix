#pragma once
#include <array>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <string>
#include <vector>

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

struct ExternalHDFontSet {
    // Keep these buffers alive: native registration may retain their pointers.
    std::array<std::vector<std::uint8_t>, 3> files;
    // Optional expanded resident bank, used by translations with >441 slots.
    // Absent metadata preserves the retail EXE's original index table.
    std::uint32_t fixedBankBase = 0, fixedBankCount = 0;
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
