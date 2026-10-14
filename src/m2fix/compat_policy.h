#pragma once
#include <cstdint>
#include <string>
#include <vector>

// A range always belongs to one release and disc. Equal numeric offsets on
// another image must never inherit a translation's exclusions.
struct CompatibilityRule {
    unsigned title = 0, disk = 0;
    std::string version;
    std::uint64_t start = 0, end = 0;

    bool overlaps(std::uint64_t offset, std::uint64_t size = 1) const {
        return size != 0 && start < end && offset < end
            && (offset >= start || size > start - offset);
    }

    bool matches(unsigned currentTitle, const std::string &currentVersion,
        unsigned currentDisk, std::uint64_t offset, std::uint64_t size = 1) const {
        return title == currentTitle && version == currentVersion && disk == currentDisk
            && overlaps(offset, size);
    }
};

struct CompatibilityPolicy {
    std::vector<CompatibilityRule> ram, cd, font, texture;

    static bool blocks(const std::vector<CompatibilityRule> &rules,
        unsigned title, const std::string &version, unsigned disk,
        std::uint64_t offset, std::uint64_t size = 1) {
        for (const auto &rule : rules)
            if (rule.matches(title, version, disk, offset, size)) return true;
        return false;
    }
};
