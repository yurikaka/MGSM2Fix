#include "../../src/m2fix/external_hd_font.h"
#include <cassert>

int main(int argc, char **argv) {
    assert(argc == 2);
    auto integral = ExternalHDFontSet::Load(argv[1], "INTEGRAL");
    auto vr = ExternalHDFontSet::Load(argv[1], "VR-DISK");
    assert(integral.files[2] != vr.files[2]); // Separate fixed-bank mappings.
    assert(!integral.ForType(2) && !integral.ForType(3));
    std::array<std::uint8_t, 0x80> object{};
    std::array<std::uint8_t, 4> original{1, 2, 3, 4};
    const auto *ptr = original.data();
    std::uint32_t size = original.size();
    std::memcpy(object.data() + 0x50, &ptr, sizeof(ptr));
    std::memcpy(object.data() + 0x58, &size, sizeof(size));
    const auto saved = object;
    for (auto *set : {&integral, &vr}) {
        for (unsigned type : {0, 1, 4}) {
            try {
                ScopedExternalFontBuffer replacement(object.data(), *set->ForType(type));
                const std::uint8_t *registered = nullptr;
                std::uint32_t registeredSize = 0;
                std::memcpy(&registered, object.data() + 0x50, sizeof(registered));
                std::memcpy(&registeredSize, object.data() + 0x58, sizeof(registeredSize));
                assert(registered == set->ForType(type)->data());
                assert(registeredSize == set->ForType(type)->size());
                throw std::runtime_error("native registration failure");
            } catch (const std::runtime_error &) {}
            assert(object == saved); // Unwind must preserve native ownership.
        }
    }
    bool failed = false;
    try { ExternalHDFontSet::Load("/nonexistent-cn-fonts", "INTEGRAL"); }
    catch (const std::runtime_error &) { failed = true; }
    assert(failed);
}
