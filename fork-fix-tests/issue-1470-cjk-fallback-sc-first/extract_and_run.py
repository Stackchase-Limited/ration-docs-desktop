#!/usr/bin/env python3
"""
#1470 - on Linux a Chinese full stop (U+3002) typed after Chinese text in Times
New Roman (or Arial) was drawn in the middle of the line instead of at the
bottom left. Windows was fine.

The report's "period" is U+3002, not ASCII '.': Bug.docx has no '.' at all and
no w:hint, so the East Asian slot is used as it should be (ECMA-376 17.3.2.26).
Times New Roman / Arial (Liberation on Linux) have no glyph for it, so the
editor draws it with the font AllFonts.js assigns to the character's range
(window.__fonts_ranges, written by CApplicationFontsWorker in
core/DesktopEditor/fontengine/ApplicationFontsWorker.cpp). A range goes to the
covering family with the lowest priority: the fixed SET_FONT_PRIORITY list
first (SimSun on Windows, PingFang SC on macOS), any other family by file size,
then by name. No Linux CJK family was in the list, so for the faces of one
NotoSansCJK-Regular.ttc "Noto Sans CJK HK" won by name - its U+3002 is the
Traditional Chinese glyph, centered in the em box - and a smaller file (AR PL
UKai / UMing, also centered) won the ideographs. Measured with Ubuntu 24.04's
fonts-noto-cjk + fonts-arphic: U+3000-3004 -> "Noto Sans CJK HK", U+4E00.. ->
"AR PL UKai CN". The fix lists the Simplified Chinese Linux families after the
existing entries.

This test compiles the REAL ApplicationFontsWorker.cpp and AllFontsGen/main.cpp
(allfontsgen) against the graphics/kernel/UnicodeConverter libraries of a
built converter, runs it on synthetic fonts made with fontTools and reads the
range table of the AllFonts.js it writes:
  cjk.ttc   faces "Noto Sans CJK HK" and "Noto Sans CJK SC" (one file, so the
            same size), both covering U+3000-303F and U+4E00-4EFF
  small.ttf "AR PL UMing CN", same coverage, a smaller file
Expected: U+3002 and U+4F60 -> "Noto Sans CJK SC". Baseline gives "AR PL UMing
CN" (smallest file), and "Noto Sans CJK HK" without small.ttf.

  RD_REPO=<core checkout>     default ../../core relative to this file
  RD_FRAMEWORKS=<dir>         dir with graphics.framework etc. (macOS) or
                              libgraphics/libkernel/libUnicodeConverter (Linux);
                              default .rd-work/payload/converter
  BASELINE=1                  read the two worker sources via
                              `git show $BASE_REF:<path>`; must FAIL

What is NOT claimed: which glyph is drawn on screen (checked separately in a
headless editor: centered before, bottom left after); that the reporter had
exactly these fonts; Japanese/Korean users on Linux now get SC shapes for
ideographs not covered by a listed Korean font - the same order Windows uses
(SimSun before MS Gothic). Needs c++ and python fontTools.
"""
import os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
FW = os.environ.get('RD_FRAMEWORKS') or os.path.normpath(os.path.join(HERE, '..', '..', '..', '.rd-work', 'payload', 'converter'))
BASE_REF = os.environ.get('BASE_REF', '64f592dfbb^')
WORKER = 'DesktopEditor/fontengine/ApplicationFontsWorker'


def read(rel):
    if os.environ.get('BASELINE'):
        return subprocess.run(['git', '-C', CORE, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, text=True, check=True).stdout
    return open(os.path.join(CORE, rel), encoding='utf-8').read()


def make_font(family, cps, upem=1000):
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    names = ['.notdef'] + ['u%04X' % c for c in cps]
    fb = FontBuilder(upem, isTTF=True)
    fb.setupGlyphOrder(names)
    fb.setupCharacterMap({c: 'u%04X' % c for c in cps})
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


cps = list(range(0x3000, 0x3040)) + list(range(0x4E00, 0x4F00)) + [0x4F60, 0x597D]

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

    from fontTools.ttLib import TTCollection
    fonts = os.path.join(t, 'fonts')
    os.makedirs(fonts)
    coll = TTCollection()
    coll.fonts = [make_font('Noto Sans CJK HK', cps), make_font('Noto Sans CJK SC', cps)]
    coll.save(os.path.join(fonts, 'cjk.ttc'))
    small = os.path.join(t, 'small.ttf')
    make_font('AR PL UMing CN', cps).save(small)

    bad = 0
    for label, with_small in [('one .ttc with HK + SC faces', False), ('+ a smaller AR PL UMing CN file', True)]:
        if with_small:
            os.rename(small, os.path.join(fonts, 'small.ttf'))
        out = os.path.join(t, 'out-%d' % with_small)
        os.makedirs(out)
        r = subprocess.run([exe, '--input=' + fonts, '--allfonts=' + os.path.join(out, 'AllFonts.js'),
                            '--selection=' + os.path.join(out, 'font_selection.bin'), '--use-system=false'],
                           capture_output=True, text=True, env=env)
        if not os.path.exists(os.path.join(out, 'AllFonts.js')):
            print(r.stdout[-2000:], r.stderr[-2000:]); print('FAIL: allfontsgen wrote no AllFonts.js'); sys.exit(1)
        rng = ranges(os.path.join(out, 'AllFonts.js'))
        for cp in (0x3002, 0x4F60):
            got = font_for(rng, cp)
            ok = got == 'Noto Sans CJK SC'
            bad += not ok
            print('%-34s U+%04X -> %-18s %s' % (label, cp, got, 'ok' if ok else 'BAD: expected Noto Sans CJK SC'))

print('PASS' if not bad else 'FAIL')
sys.exit(1 if bad else 0)
