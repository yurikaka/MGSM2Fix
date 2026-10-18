# External HD font advances

`ExternalHDFont = true` can load optional layout rules alongside its existing
font binaries. Rules affect only the HD advance (horizontal spacing), never the
stored glyph, low-resolution raster stride, or a game file.

With the release-directory layout, use:

- `<ExternalHDFontDirectory>/INTEGRAL/advances.json`
- `<ExternalHDFontDirectory>/VR-DISK/advances.json`

The legacy flat layout uses `cn_advances.json` and `cn_vr_advances.json` instead.
The same directory selection as the font binaries applies. No additional INI
switch is needed. A missing file leaves every advance unchanged. Restart the
game after editing a file; the font set and metadata are cached together.

Example, reproducing the collection's narrow HD advances for lowercase e/p:

```json
{
  "schema": 1,
  "overrides": [
    {"glyph_index": 69, "from": 8, "to": 7},
    {"glyph_index": 80, "from": 8, "to": 7}
  ]
}
```

`glyph_index` is the index (0–111) in `hankaku_4x.bin`, not a Unicode code point.
For ordinary ASCII it is `code - 32`. `from` and `to` are widths in PS1 logical
pixels (1–15), not 4x bitmap pixels. A rule applies only when the original
returned width equals `from`. Other widths, other indices, and missing rules
retain the original result. Duplicate index/from pairs, invalid bounds, and
malformed metadata are rejected through the existing external-font fallback.
The runtime does not hard-code e/p or an 8-to-7 transformation.

The audited x64 Integral and Japanese VR modules gain two guest instruction
callbacks before native registration: one at the halfwidth drawing epilogue,
and one in the width-measurement caller after `get_hantable`. Both change only
register results. Drawing still consumes the untouched low-resolution bitmap
with its original row stride. The measure callback preserves the bearing and
bitmap-offset bits. Guest instructions at each callback are verified before
applying a rule.

Rules require all of:

- The matching external HD font set has registered successfully.
- The machine's live `HighP` flag is enabled.
- `DisableFont` is false and the halfwidth font callback is not partially blocked.

The current scope is these two audited game releases. RAM/CD disable switches
are independent of these runtime callbacks. Missing rules preserve default
behavior; disabling the HD font path or selecting Original prevents overrides.

For the RC21-derived translation, also remove the static e/p edits from PPF2.
An old PPF that changes the source stride to 7 cannot be repaired by this
advance-only feature. The companion data migration keeps PPF1 and all bitmap
bytes intact and recalculates PPF2 EDC/ECC against the actual PPF1 baseline.

Validation includes standalone C++ metadata tests and execution of the real
PPF-applied guest measurement/drawing routines over 95 ASCII characters, three
discs, and Original/HD/Original transitions. This is not a Windows in-game test.
