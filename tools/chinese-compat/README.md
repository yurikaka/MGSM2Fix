# Runtime MGS1 compatibility and external HD fonts

No game archive, original script, executable or installed ASI is modified by this
implementation. RAM/CD filtering occurs in the existing native-call hooks.
The original font script is left intact. `entryMGSFontData` borrows external
font buffers for the native registration call, then restores the original
Binary object's pointer and size. Persistent caches keep replacement buffers
alive for any asynchronous native use. Original Binary allocations retain their
ownership. Original font resources may still be read into temporary memory;
this hook replaces the data registered for rendering, not filesystem reads.

## Opt-in settings

```ini
[Patches]
PartialDisableRAM = true
PartialDisableCDROM = true
PartialDisableFont = true
CompatibilityManifest = mods/cn-compat/manifest.json
ExternalHDFont = true
ExternalHDFontDirectory = mods/hd-fonts
```

Partial exclusions do not change language selection or the existing EnglishText behavior.

All four boolean fields default to false. The manifest is ignored when all
partial fields are false; external fonts are ignored when ExternalHDFont is false.

The external font loader is language-neutral. Its audited runtime support remains
limited to MGS1 INTEGRAL and VR-DISK on x64. Place each release's resources in
`<ExternalHDFontDirectory>/INTEGRAL/` or
`<ExternalHDFontDirectory>/VR-DISK/`, using these filenames:
`hankaku_4x.bin`, `kanji_4x.bin`, `fontall.bin`, and optional `bank0.bin`.
The formats and glyph-matching rules are unchanged. The translation-specific
tools below still generate Chinese resources, which are one use of this loader.

Existing packs with flat `cn_` / `cn_vr_` filenames remain supported when the
corresponding release subdirectory is absent. Existing `ChineseHDFont` and
`ChineseHDFontDirectory` configuration keys also remain readable; the new keys
take precedence when both are supplied. Existing packs can keep their directory
by setting `ExternalHDFontDirectory` to that location.
Keep existing full Disable* options false when using partial exclusions and HD
fonts. Full disables take precedence. Missing/invalid partial manifests fail
closed to full disable for the requested categories.

This requires a new build of the fix source; existing ASIs do not implement
these options. No existing ASI is replaced or patched by these tools. Runtime
font substitution supports the audited x64 native Binary reader only. Its code
signature is checked before accessing native fields. Other layouts or missing
font data fall back to guest low-resolution font rendering for the selected
external font profile. Other titles/releases retain original fonts. The C++ hook has
not been built/tested in Windows; portable buffer lifetime tests and native-code
emulation are distinct from an in-game test.

## Prepare external data

Generated proprietary game-derived resources stay outside this repository.
From `/home/yurikaka/dev`, prepare a NEW directory:

```sh
python3 mgs/MGSM2Fix/tools/chinese-compat/stage.py --audit mgs/analysis/cn-compat/audit --fonts mgs/analysis/cn-compat/build/fonts --out mgs/analysis/cn-compat/build/runtime-profile
```

This only copies six validated font files, scoped manifests, license and
attribution. It does not edit archives, INI, scripts or ASIs, or activate PPFs.
Use the output as the external directory referenced by the config. Choose the
fallback manifest (8 font callbacks excluded per release) when using the
translation without rebuilt HD fonts.

`hd_fonts.py` produces official-format 48x48 MSB-first 2bpp glyphs, keeps exact
36-byte guest lookup keys, repairs fixed bank-0 indices, and preserves Japanese
keys. INTEGRAL and VR have separate sets. Halfwidth records have two separate
metadata bytes, width-dependent packed images and trailing padding. Source Han
Serif SC Regular (SIL OFL 1.1) provides 2044 reviewed CJK shapes; 30 special
shapes retain antialiased source contours. Ruby/platform symbols stay official.

Rebuild order: `audit.py`, `resources.py`, `stream_resources.py`,
`glyph_mapping.py apply`, `policy.py`, `hd_fonts.py` for INTEGRAL and VR,
`text_export.py`, `conflict_report.py`, `font_conflicts.py`, `texture_audit.py`,
`nontext_report.py`, `native_font_verify.py`, `stage.py`.
Use each tool's `--help`. The existing `tools/integral-english` parsers are used.
Python requirements: Pillow, NumPy, OpenCV; Unicorn for native emulation.
Reviewed glyph identities are stored by SHA-256; unknown shapes require review.

## Verification

```sh
g++ -std=c++20 -Wall -Wextra -Werror tools/chinese-compat/test_policy.cpp -o /tmp/mgs-cn-policy-test
/tmp/mgs-cn-policy-test
g++ -std=c++20 -Wall -Wextra -Werror tools/chinese-compat/test_font_runtime.cpp -o /tmp/mgs-cn-font-test
/tmp/mgs-cn-font-test /home/yurikaka/dev/mgs/analysis/cn-compat/build/fonts
```

The former archive-overlay approach was withdrawn and its local installation
restored. Its installer, script writer and archive repacker are no longer part
of this feature. The local backup journal remains available as restore evidence.
