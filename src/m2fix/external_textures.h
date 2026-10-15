#pragma once
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <map>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>
#include "nlohmann/json.hpp"

// Buffers remain alive after native registration: the emulator command queue
// may consume them after the Squirrel call has returned.
class ExternalTextureSet {
public:
    using Key = std::tuple<unsigned, std::string, unsigned, int, int>;
    std::map<Key, std::vector<std::uint8_t>> files;

    static ExternalTextureSet Load(const std::filesystem::path &manifest) {
        std::ifstream input(manifest);
        if (!input) throw std::runtime_error("cannot open external texture manifest");
        nlohmann::json document;
        input >> document;
        if (document.at("schema").get<unsigned>() != 1)
            throw std::runtime_error("unsupported external texture schema");
        ExternalTextureSet result;
        std::size_t total = 0;
        for (const auto &entry : document.at("textures")) {
            const auto relative = std::filesystem::u8path(entry.at("file").get<std::string>());
            if (relative.empty() || relative.is_absolute() || relative.has_root_name())
                throw std::runtime_error("texture path must be relative to its manifest");
            for (const auto &part : relative) if (part == "..")
                throw std::runtime_error("texture path escapes its manifest directory");
            const Key key{entry.at("title").get<unsigned>(), entry.at("version").get<std::string>(),
                entry.at("id").get<unsigned>(), entry.value("data_type", 0), entry.value("vrstage", -1)};
            if (std::get<2>(key) > 65535 || std::get<3>(key) < 0 || std::get<3>(key) > 2)
                throw std::runtime_error("unsupported texture registration");
            std::ifstream file(manifest.parent_path() / relative, std::ios::binary | std::ios::ate);
            if (!file) throw std::runtime_error("missing external texture: " + relative.string());
            const auto position = file.tellg();
            if (position < 128 || position > 64 * 1024 * 1024)
                throw std::runtime_error("external texture exceeds size limits");
            const auto size = static_cast<std::size_t>(position);
            if (total + size > 256 * 1024 * 1024)
                throw std::runtime_error("external texture set exceeds size limits");
            std::vector<std::uint8_t> data(size);
            file.seekg(0);
            if (!file.read(reinterpret_cast<char *>(data.data()), static_cast<std::streamsize>(data.size())))
                throw std::runtime_error("cannot read external texture");
            if (data[0] != 0x0a || data[2] != 1 || (data[3] != 8 && data[3] != 4))
                throw std::runtime_error("external texture must be a PCX image");
            total += data.size();
            if (!result.files.emplace(key, std::move(data)).second)
                throw std::runtime_error("duplicate external texture registration");
        }
        return result;
    }

    const std::vector<std::uint8_t> *Find(unsigned title, const std::string &version,
        unsigned id, int type, int stage) const {
        auto found = files.find(Key{title, version, id, type, stage});
        return found == files.end() ? nullptr : &found->second;
    }
};
