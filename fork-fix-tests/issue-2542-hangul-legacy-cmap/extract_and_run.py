#!/usr/bin/env python3
"""
#2542 - on macOS, Korean text in a spreadsheet drew as unrelated Chinese
characters (충 as 桐) while the cell text itself was right.

Two halves. (1) Font coverage: CheckSymbols recorded Heiti's legacy Mac Chinese
subtables as Unicode coverage, so Heiti won the Hangul fallback. That half was
fixed for #2433 (core 65a056a5f1) and our font caches now send Hangul to
AppleGothic; upstream ONLYOFFICE's cache on the same machine still sends 월/충
to Heiti SC. (2) Glyph lookup: asked for U+CDA9, a face that has a Unicode
subtable without the character still consulted its legacy subtable, where code
0xCDA9 is GB2312 for 桐. #2433 gated that in CFontFile::SetCMapForCharCode
(FontFile.cpp) only. The two copies of the same loop were left ungated:
  - js/cpp/text.cpp ASC_FT_SetCMapForCharCode - the wasm entry point the editor
    canvas calls (sdkjs/common/libfont/file.js GetGIDByUnicode / CacheGlyph); a
    non-zero answer there stops the fallback to a font that has the character,
  - TextShaper.cpp NSShaper::FT_SetCMapForCharCode - the native shaper.
So any run whose font resolves to Heiti (Heiti SC/TC set on the cell, or a
Chinese font name substituted to it) drew Hangul as Chinese.

This lifts BOTH real functions out of core by brace matching, compiles them
against real FreeType (pkg-config freetype2) and asks them about the real
macOS system fonts.

  RD_REPO    core checkout (default ../../core)
  BASELINE=1 reads the sources via `git show $BASE_REF:<path>`; the Hangul
             cases must FAIL there.

What is NOT claimed: this is the native compile of the wasm's source, not the
wasm binary itself (that was rebuilt and checked separately, see the commit);
a face with no Unicode subtable (still consulted) is not exercised because no
such font is on the machine; nothing was rendered in the editor. macOS only
(needs /System/Library/Fonts/STHeiti Light.ttc).
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
WASM = 'DesktopEditor/fontengine/js/cpp/text.cpp'
SHAPER = 'DesktopEditor/fontengine/TextShaper.cpp'
# Pinned to the parent of the commit that landed the fix, never HEAD.
BASE_REF = os.environ.get('BASE_REF', '49e0ac9b11^')
BASELINE = bool(os.environ.get('BASELINE'))

HEITI = '/System/Library/Fonts/STHeiti Light.ttc'   # face 0 Heiti TC, face 1 Heiti SC
GOTHIC = '/System/Library/Fonts/AppleSDGothicNeo.ttc'
WINGDINGS = '/System/Library/Fonts/Supplemental/Wingdings.ttf'


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, text=True, check=True).stdout
    return open(os.path.join(REPO, rel), encoding='utf-8').read()


def brace_match(text, start):
    ob = text.index('{', start)
    depth = 0
    for i in range(ob, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise SystemExit('unbalanced braces from offset %d' % start)


def extract(text, anchor, needles):
    at = text.find(anchor)
    if at == -1:
        raise SystemExit('%r not found - the extractor needs updating' % anchor)
    body = brace_match(text, at)
    for n in needles:
        if n not in body:
            raise SystemExit('extracted %r is missing %r - wrong block?' % (anchor, n))
    return body


wasm_fn = extract(read(WASM), 'WASM_EXPORT unsigned int ASC_FT_SetCMapForCharCode(',
                  ('FT_Set_Charmap', 'FT_Get_Char_Index'))
shaper_fn = extract(read(SHAPER), 'unsigned int FT_SetCMapForCharCode(void* face_pointer',
                    ('FT_Set_Charmap', 'FT_Get_Char_Index'))

DRIVER = r'''
#include <stdio.h>
#include <ft2build.h>
#include FT_FREETYPE_H
#define WASM_EXPORT
%(wasm)s
namespace NSShaper {
%(shaper)s
}
int main(int argc, char **argv)
{
	/* argv: font face_index codepoint(hex) ... ; prints "wasm shaper" GIDs per code point */
	FT_Library lib;
	FT_Face face;
	if (FT_Init_FreeType(&lib) || FT_New_Face(lib, argv[1], atoi(argv[2]), &face))
		return 2;
	for (int i = 3; i < argc; ++i)
	{
		unsigned int cp = (unsigned int)strtoul(argv[i], NULL, 16);
		unsigned int a = ASC_FT_SetCMapForCharCode(face, cp);
		unsigned int b = NSShaper::FT_SetCMapForCharCode(face, cp);
		printf("%%x %%u %%u\n", cp, a, b);
	}
	return 0;
}
''' % {'wasm': wasm_fn, 'shaper': shaper_fn}


def build():
    tmp = tempfile.mkdtemp(prefix='rd2542-')
    src, exe = os.path.join(tmp, 'drv.cpp'), os.path.join(tmp, 'drv')
    with open(src, 'w', encoding='utf-8') as f:
        f.write('#include <stdlib.h>\n' + DRIVER)
    flags = subprocess.run(['pkg-config', '--cflags', '--libs', 'freetype2'],
                           capture_output=True, text=True, check=True).stdout.split()
    subprocess.run(['c++', '-std=c++11', '-w', src, '-o', exe] + flags, check=True)
    return exe


def lookup(exe, font, index, cps):
    out = subprocess.run([exe, font, str(index)] + ['%x' % c for c in cps],
                         capture_output=True, text=True, check=True).stdout
    return {int(c, 16): (int(a), int(b)) for c, a, b in (l.split() for l in out.splitlines())}


def main():
    for f in (HEITI, GOTHIC, WINGDINGS):
        if not os.path.isfile(f):
            raise SystemExit('needs macOS system font %s' % f)
    exe = build()
    sc = lookup(exe, HEITI, 1, [0xCDA9, 0x6850, 0xC6D4])
    tc = lookup(exe, HEITI, 0, [0xD14C, 0x57D5])
    ko = lookup(exe, GOTHIC, 0, [0xCDA9, 0xD14C])
    wd = lookup(exe, WINGDINGS, 0, [0xF041])

    failed = 0

    def check(name, pair, ok):
        nonlocal failed
        for fn, gid in zip(('wasm  ', 'shaper'), pair):
            good = ok(gid)
            failed += not good
            print('%s %s %-58s gid=%d' % ('PASS' if good else 'FAIL', fn, name, gid))

    gid_tong = sc[0x6850]
    check('Heiti SC: 충 U+CDA9 is not drawn (0, so fallback runs)', sc[0xCDA9], lambda g: g == 0)
    check('Heiti SC: 충 U+CDA9 is not the glyph of 桐 U+6850', sc[0xCDA9], lambda g: g != gid_tong[0])
    check('Heiti SC: 월 U+C6D4 is not drawn', sc[0xC6D4], lambda g: g == 0)
    check('Heiti TC: 테 U+D14C is not drawn (Big5 0xD14C is 埕)', tc[0xD14C], lambda g: g == 0)
    check('Heiti SC: Chinese 桐 U+6850 still drawn', sc[0x6850], lambda g: g > 0)
    check('Heiti TC: Chinese 埕 U+57D5 still drawn', tc[0x57D5], lambda g: g > 0)
    check('Apple SD Gothic Neo: 충 U+CDA9 drawn', ko[0xCDA9], lambda g: g > 0)
    check('Apple SD Gothic Neo: 테 U+D14C drawn', ko[0xD14C], lambda g: g > 0)
    check('Wingdings: MS Symbol U+F041 still drawn', wd[0xF041], lambda g: g > 0)
    total = 18
    print('%s: %d passed / %d failed' % ('BASELINE ' + BASE_REF if BASELINE else 'fix',
                                         total - failed, failed))
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
