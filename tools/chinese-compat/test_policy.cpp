#include "../../src/m2fix/compat_policy.h"
#include <cassert>
#include <limits>

int main() {
    CompatibilityRule rule{99, 0, "INTEGRAL", 100, 120};
    assert(rule.matches(99, "INTEGRAL", 0, 100));
    assert(rule.matches(99, "INTEGRAL", 0, 119));
    assert(!rule.matches(99, "INTEGRAL", 0, 120));
    assert(!rule.matches(99, "INTEGRAL", 0, 99));
    assert(rule.matches(99, "INTEGRAL", 0, 99, 2));
    assert(!rule.matches(99, "INTEGRAL", 0, 98, 2));
    assert(!rule.matches(99, "VR-DISK", 0, 100));
    assert(!rule.matches(99, "INTEGRAL", 1, 100));
    assert(!rule.matches(980, "INTEGRAL", 0, 100));
    assert(!rule.matches(99, "INTEGRAL", 0, 100, 0));
    // No offset+size overflow: an extremely large address stays outside.
    assert(!rule.matches(99, "INTEGRAL", 0, std::numeric_limits<uint64_t>::max(), 8));
    // A write spanning the entire excluded interval must still be rejected.
    assert(rule.matches(99, "INTEGRAL", 0, 0, 121));
    CompatibilityPolicy policy;
    policy.cd.push_back(rule);
    assert(CompatibilityPolicy::blocks(policy.cd, 99, "INTEGRAL", 0, 105, 4));
    assert(!CompatibilityPolicy::blocks(policy.ram, 99, "INTEGRAL", 0, 105, 4));
}
