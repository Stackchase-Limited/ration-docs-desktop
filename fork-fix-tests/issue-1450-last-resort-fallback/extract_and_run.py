#!/usr/bin/env python3
"""
#1450 - "CJK characters unwanted fallback to Unicode Consortium's Last Resort font". With
unicode-org's LastResort-Regular.ttf in ~/.local/share/fonts, CJK typed in Arial was drawn
with Last Resort's placeholder boxes instead of Noto Sans CJK TC.

Characters missing from the run's font are drawn with the family AllFonts.js assigns to the
character's range (window.__fonts_ranges, written by CApplicationFontsWorker in
core/DesktopEditor/fontengine/ApplicationFontsWorker.cpp; the converter reads the same table).
A family outside the SET_FONT_PRIORITY list ranks by file size, smallest first. Last Resort
maps EVERY code point (one placeholder per block) and is smaller than any CJK family, so it
took every range. Reproduced with the real fonts and the main tree's allfontsgen: with
LastResort-Regular.ttf next to Hiragino Sans GB the table shrank from 345 ranges to 3, all
"Last Resort" (U+4E2D, U+3042, U+0627, U+0E01). The fix leaves families named "Last Resort*"
/ "LastResort*" out of the range table.

This test compiles the REAL ApplicationFontsWorker.cpp and AllFontsGen/main.cpp (allfontsgen)
against the graphics/kernel/UnicodeConverter libraries of a built converter, runs it on
synthetic fonts made with fontTools, and reads the range table of the AllFonts.js it writes:
  cjk.ttf   "Noto Sans CJK TC" (not in the priority list, as on the reporter's Arch), one
            glyph per code point for U+3000-303F, U+4E00-4EFF
  lr*.ttf   "Last Resort" / "Last Resort High-Efficiency" / "LastResort", each mapping
            Latin, Thai and those CJK blocks to ONE glyph - a much smaller file, like the real thing
Expected: U+3002 and U+4E2D -> "Noto Sans CJK TC" with each Last Resort variant installed,
and an uncovered code point (U+0E01 Thai) maps to no family rather than to Last Resort.
Baseline gives the Last Resort family everywhere.

  RD_REPO=<core checkout>     default ../../core relative to this file
  RD_FRAMEWORKS=<dir>         dir with graphics.framework etc. (macOS) or
                              libgraphics/libkernel/libUnicodeConverter (Linux);
                              default .rd-work/payload/converter
  BASELINE=1                  read the worker sources via `git show $BASE_REF:<path>`; must FAIL

What is NOT claimed: how the editor draws a character no font covers (as before: the run
font's .notdef); that macOS's own /System/Library/Fonts/LastResort.otf ever reached the list
(it does not in our app's AllFonts.js today); a GUI check on Linux. Needs c++ and fontTools.
"""
import os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
FW = os.environ.get('RD_FRAMEWORKS') or os.path.normpath(os.path.join(HERE, '..', '..', '..', '.rd-work', 'payload', 'converter'))
# Pinned to the parent of the commit that landed this fix, never HEAD.
BASE_REF = os.environ.get('BASE_REF', 'dc5f520a6a^')
WORKER = 'DesktopEditor/fontengine/ApplicationFontsWorker'


def read(rel):
    if os.environ.get('BASELINE'):
        return subprocess.run(['git', '-C', CORE, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, text=True, check=True).stdout
    return open(os.path.join(CORE, rel), encoding='utf-8').read()


def make_font(family, cps, upem=1000, one_glyph=False):
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    names = ['.notdef'] + (['box'] if one_glyph else ['u%04X' % c for c in cps])
    fb = FontBuilder(upem, isTTF=True)
    fb.setupGlyphOrder(names)
    fb.setupCharacterMap({c: ('box' if one_glyph else 'u%04X' % c) for c in cps})
    pen = TTGlyphPen(None)
    pen.moveTo((100, 0)); pen.lineTo((100, 500)); pen.lineTo((500, 500)); pen.lineTo((500, 0)); pen.closePath()
    box = pen.glyph()
    fb.setupGlyf({n: box for n in names})
    fb.setupHorizontalMetrics({n: (upem, 100) for n in names})
    fb.setupHorizontalHeader(ascent=880, descent=-120)
    fb.setupNameTable({'familyName': family, 'styleName': 'Regular'})
    fb.setupOS2(sTypoAscender=880, sTypoDescender=-120, usWinAscent=880, usWinDescent=120,
                ulCodePageRange1=(1 << 18) | (1 << 20))
    fb.setupPost()
    return fb.font


def ranges(allfonts):
    s = open(allfonts, encoding='utf-8').read()
    infos = re.search(r'window\["__fonts_infos"\] = \[(.*?)\n\];', s, re.S).group(1)
    names = re.findall(r'^\["([^"]*)"', infos, re.M)
    nums = [int(x) for x in re.findall(r'-?\d+', re.search(r'window\["__fonts_ranges"\] = \[(.*?)\];', s, re.S).group(1))]
    return [(nums[i], nums[i + 1], names[nums[i + 2]]) for i in range(0, len(nums), 3)]


def font_for(rng, cp):
    return next((n for a, b, n in rng if a <= cp <= b), None)


cps = list(range(0x3000, 0x3040)) + list(range(0x4E00, 0x4F00))
# Last Resort's coverage, cut to what a format-4 cmap holds: Latin, Thai and the CJK blocks above
lr_cps = list(range(0x20, 0x7F)) + list(range(0x0E00, 0x0E80)) + list(range(0x3000, 0x3040)) + list(range(0x4E00, 0x5000))
LAST_RESORT = ['Last Resort', 'Last Resort High-Efficiency', 'LastResort']

with tempfile.TemporaryDirectory() as t:
    src = os.path.join(t, 'DesktopEditor')
    for rel in [WORKER + '.cpp', WORKER + '.h', 'DesktopEditor/AllFontsGen/main.cpp']:
        p = os.path.join(t, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, 'w', encoding='utf-8').write(read(rel) if 'ApplicationFontsWorker' in rel else
                                             open(os.path.join(CORE, rel), encoding='utf-8').read())
    exe = os.path.join(t, 'allfontsgen')
    inc = ['-I' + os.path.join(CORE, 'DesktopEditor', d) for d in ('fontengine', 'AllFontsGen')] + ['-I' + os.path.join(CORE, 'DesktopEditor')]
    if os.path.isdir(os.path.join(FW, 'graphics.framework')):
        link = ['-F' + FW, '-framework', 'graphics', '-framework', 'kernel', '-framework', 'UnicodeConverter']
        env = dict(os.environ, DYLD_FRAMEWORK_PATH=FW)
        plat = ['-D_MAC', '-DMAC']
    else:
        link = ['-L' + FW, '-lgraphics', '-lkernel', '-lUnicodeConverter', '-Wl,-rpath,' + FW]
        env = dict(os.environ, LD_LIBRARY_PATH=FW)
        plat = ['-D_LINUX', '-DLINUX']
    r = subprocess.run(['c++', '-std=c++14', '-w'] + plat + ['-DKERNEL_USE_DYNAMIC_LIBRARY', '-DGRAPHICS_USE_DYNAMIC_LIBRARY',
                        '-DUNICODE', '-D_UNICODE'] + inc +
                       ['-o', exe, os.path.join(t, 'DesktopEditor/AllFontsGen/main.cpp'), os.path.join(t, WORKER + '.cpp')] + link,
                       capture_output=True, text=True)
    if r.returncode:
        print(r.stderr[-3000:]); print('FAIL: allfontsgen does not build'); sys.exit(1)

    fonts = os.path.join(t, 'fonts')
    os.makedirs(fonts)
    make_font('Noto Sans CJK TC', cps).save(os.path.join(fonts, 'cjk.ttf'))

    bad = 0
    for n, family in enumerate(LAST_RESORT):
        lr = os.path.join(fonts, 'lr.ttf')
        make_font(family, lr_cps, one_glyph=True).save(lr)
        assert os.path.getsize(lr) < os.path.getsize(os.path.join(fonts, 'cjk.ttf'))
        out = os.path.join(t, 'out-%d' % n)
        os.makedirs(out)
        r = subprocess.run([exe, '--input=' + fonts, '--allfonts=' + os.path.join(out, 'AllFonts.js'),
                            '--selection=' + os.path.join(out, 'font_selection.bin'), '--use-system=false'],
                           capture_output=True, text=True, env=env)
        if not os.path.exists(os.path.join(out, 'AllFonts.js')):
            print(r.stdout[-2000:], r.stderr[-2000:]); print('FAIL: allfontsgen wrote no AllFonts.js'); sys.exit(1)
        rng = ranges(os.path.join(out, 'AllFonts.js'))
        for cp, want in ((0x3002, 'Noto Sans CJK TC'), (0x4E2D, 'Noto Sans CJK TC'), (0x0E01, None)):
            got = font_for(rng, cp)
            ok = got == want
            bad += not ok
            print('with "%-27s U+%04X -> %-28s %s' % (family + '"', cp, got, 'ok' if ok else 'BAD: expected %s' % want))

print('PASS' if not bad else 'FAIL')
sys.exit(1 if bad else 0)
