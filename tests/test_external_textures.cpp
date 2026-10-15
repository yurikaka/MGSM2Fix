#include "../src/m2fix/external_textures.h"
#include "../src/m2fix/external_hd_font.h"
#include <cassert>

int main() {
    const auto folder = std::filesystem::temp_directory_path() / "mgsm2fix-external-texture-test";
    std::filesystem::create_directories(folder);
    std::vector<unsigned char> data(128, 0);
    data[0] = 10; data[2] = 1; data[3] = 8;
    { std::ofstream file(folder / "image.pcx", std::ios::binary); file.write(reinterpret_cast<const char *>(data.data()), data.size()); }
    auto write = [&](const std::string &path) {
        nlohmann::json doc = {{"schema", 1}, {"textures", {{{"title",99},{"version","INTEGRAL"},
            {"id",0xe981},{"file",path},{"data_type",0},{"vrstage",-1}}}}};
        std::ofstream(folder / "textures.json") << doc;
    };
    write("image.pcx");
    auto loaded = ExternalTextureSet::Load(folder / "textures.json");
    const auto *image = loaded.Find(99, "INTEGRAL", 0xe981, 0, -1);
    assert(image && *image == data);
    assert(!loaded.Find(99, "VR-DISK", 0xe981, 0, -1));
    assert(!loaded.Find(99, "INTEGRAL", 0xe981, 1, -1));
    assert(!loaded.Find(99, "INTEGRAL", 0xe981, 0, 0));
    std::array<std::uint8_t, 0x80> binary{};
    const auto original = binary;
    { ScopedExternalFontBuffer scope(binary.data(), *image); }
    assert(binary == original);
    write("../image.pcx");
    bool rejected = false;
    try { ExternalTextureSet::Load(folder / "textures.json"); }
    catch (const std::runtime_error &) { rejected = true; }
    assert(rejected);
    std::filesystem::remove_all(folder);
}
