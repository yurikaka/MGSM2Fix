# External dynamic code overrides

The x64 MGS1 Fix can load platform-dependent text expansions and optional HD
and PS1 glyph banks from a JSON manifest. Nothing is named or assigned to
SELECT, START, Chinese, or a particular private glyph range in the runtime.

```ini
[Patches]
ExternalDynamicCodeOverride = true
ExternalDynamicCodeOverridePath = mods/dynamic-codes/manifest.json
```

The switch defaults to false. The path is relative to MGSM2Fix's directory
(or absolute). This feature is independent of ExternalHDFont and the official
RAM/CD/font disable switches. It does not write the game's files. Restart the
game after editing the manifest; manifests are cached for the process lifetime.
The earlier ExternalSelectLabels and ExternalStartLabels options are replaced
by this one switch and path; their packed BIN format is no longer loaded.

## Manifest

```json
{
  "schema": 1,
  "profiles": [{
    "title": 99,
    "version": "INTEGRAL",
    "codes": [{
      "code": "0x8182",
      "slot_bytes": 6,
      "labels": {
        "PS": ["0x8041"],
        "PS_SWAP": ["0x8042"],
        "NX": ["0x8043"],
        "XBOX": ["0x8044"],
        "STEAM": ["0x8045"],
        "PS5": ["0x8046"]
      }
    }]
  }]
}
```

This data-free example replaces an existing official code with the letters
A–F; it is an illustration, not the Chinese translation's configuration.
The six keys are the game's platform-style table: PS, swapped PS, Nintendo,
Xbox, Steam, and PS5. Values are game glyph codes, not Unicode. Integer fields
accept decimal JSON integers or hexadecimal strings. Profiles match both title
and version exactly (Integral uses title 99; its releases are INTEGRAL and
VR-DISK). One manifest may contain multiple profiles.

The native decoder accepts dynamic codes **8180–8192**. Any of these, including
an official code already in use, may be overridden. Codes absent from the
active profile retain the official decoder. This does not add arbitrary
16-bit dispatch codes. A label must contain static glyph codes in 8020–9FFF;
terminators, padding, and recursive dynamic codes are rejected.

`slot_bytes` is an even size from 2 to 254, including the two-byte marker.
Every use of a configured code must reserve the configured size. For example,
a six-byte slot is `81 82 80 00 80 00`; following text starts at byte 6.
The first glyph is returned to the decoder; only the remaining slot bytes are
rewritten. Labels are padded with zero-width 8000. The marker is preserved so
PEEK/GET and controller-style changes can repeat expansion. A slot is accepted
only if its tail is initial padding or exactly a configured expansion tail.
Malformed slots and unknown styles are logged and left untouched. This checks
slot contents, not allocation metadata: the translation author must allocate
space and rebuild text/dialogue structures correctly in the PPF. Existing
official text may use a different slot length; matching its code alone is not
sufficient. All uses of a code within a profile need the same slot size.

## Multiple optional glyph banks

Each profile can also contain:

```json
"guest_font_calls": ["0x4659c", "0x4679c"],
"glyph_banks": [
  {"first_code": "0x9e00", "count": 2,
   "hd": "bank-a.hd.bin", "low": "bank-a.low.bin"},
  {"first_code": "0x9f00", "count": 3,
   "hd": "bank-b.hd.bin", "low": "bank-b.low.bin"}
]
```

Multiple BIN pairs are supported; no combined file is required. Paths are
relative to the manifest. Each bank contains consecutive raw glyphs in code
order, with no header: HD glyphs are 48x48, 2 bits/pixel, 576 bytes each;
PS1 glyphs are 12x12, 2 bits/pixel, 36 bytes each. Pixels are row-major with
four pixels per byte, most significant pair first. Both files are required
and their sizes must match count exactly. The native dot-font path uses a
nearest-neighbour 4x copy of the low glyph. There is no font generation or
redrawing at load time.

Bank ranges must lie in 8100–9FFF, must not overlap each other or 8180–8192,
and must be reserved by the translation. At most 4096 glyphs per profile
are accepted. Labels can also reference original game glyphs with no custom
bank. Other glyphs continue through the original font reader. These banks
work in both original and high-resolution picture modes.

Custom banks require audited PS1 glyph-call addresses: Integral uses
4659C/4679C; VR-DISK uses 46664/46864. These are physical RAM offsets of
specific glyph JAL sites whose ABI uses s0 for the code and v0 for the bitmap
pointer (the delay slot stores v0 at sp+16). The loader supplies a read-only
virtual bitmap through both CPU and bus byte readers to the original PS1
rasterizer. The retail LB/LBU interpreter calls the bus directly after its
fast RAM lookup, bypassing the CPU byte reader; both paths must be intercepted.
Colour, placement and advance
remain its work. This field is not a general-purpose arbitrary hook address.
Other releases require verifying equivalent call sites. The native decoder
and font-reader hooks also require the supported x64 executable signatures.

Duplicate profiles/codes, overlapping banks, invalid styles, bad file sizes,
recursive labels, and oversized labels reject the manifest. Failure logs an
error and leaves official handling active. To stop overriding a code, remove
its rule; to disable all overrides, turn off the INI switch. Restore any
matching PPF text if it depends on the removed expansion.

## Verification

`tests/test_external_dynamic_codes.cpp` covers generic code assignments,
multiple slot lengths, arbitrary bank positions, repeat reads, style changes,
untouched suffixes, malformed input and HD/dot/low glyph lookup. It runs in
the existing Windows native-test workflow. The translation regression tool
`verify_select_labels.py --manifest ...` executes native PEEK/GET wrappers
with the actual configurable C++ expansion and the original Integral/VR PS1
rasterizers. Emulation and compilation do not replace an in-game Windows test.
