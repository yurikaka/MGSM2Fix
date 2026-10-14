# Scoped MGS1 patch exclusions

The new `[Patches]` settings `PartialDisableRAM`, `PartialDisableCDROM` and
`PartialDisableFont` default to `false`. With all three unset, no compatibility
manifest is loaded and the existing patch/font behavior is preserved.
`CompatibilityManifest` defaults to `mods/cn-compat/manifest.json` and is read
only when at least one partial option is enabled.

Schema-1 exclusions use half-open ranges and are scoped by title, release and
disc. RAM addresses are physical offsets; CD addresses are raw 2352-byte disc
offsets. Font ranges identify intercepted guest font callback addresses;
texture ranges optionally identify independent texture replacement IDs.
Full `Disable*` flags take precedence. Invalid/missing manifests fall back to
full disable for the requested partial categories.

`audit.py` compares original data, official targets and supplied PPF writes.
`resources.py` inventories guest resource/font banks. `stream_resources.py`
includes external subtitle banks. `policy.py` emits exhaustive decisions and a
fallback manifest, excluding entire conflicting records. `conflict_report.py`
adds exact payloads and decoded text windows. `texture_audit.py` and
`nontext_report.py` check whether translated image differences exist; they do
not replace images when no differences are found.

No game data or generated fonts are included. These scripts use the existing
`tools/integral-english` parsers and, where applicable, Pillow. Run the portable
policy test with:

```sh
g++ -std=c++20 -Wall -Wextra -Werror tools/chinese-compat/test_policy.cpp -o /tmp/mgs-cn-policy-test
/tmp/mgs-cn-policy-test
```

Partial patch exclusions do not change language selection or the existing
EnglishText behavior.
