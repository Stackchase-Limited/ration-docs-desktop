#!/usr/bin/env python3
"""
CFontFile::GetGIDByUnicode never retried symbolic fonts at their real codepoints.

Found while ruling core out of #2195 (the equation i/j glyph bug, which is a
hardcoded Cambria Math GID table in sdkjs/word/Math/mathText.js and needs no core
change).  This is a separate, genuine core defect on the way past.

A symbolic face - Wingdings, Symbol, Webdings - does not map 'a' to 'a'.  Its
cmap carries the characters in the 0xF000-0xF0FF private-use range, so a lookup
for the bare codepoint misses and has to be retried at code + 0xF000.
CFontFile::CacheGlyph does exactly that (FontFile.cpp:874-878).
CFontFile::GetGIDByUnicode is a copy of that same block with the offset left off:

    if (-1 != m_nSymbolic && code < 0xF000)
        unGID = SetCMapForCharCode(code, &nCMapIndex);     // no + 0xF000

which re-queries the identical code that had just returned 0, so it can only
return 0 again and the whole branch is dead.

It is not a harmless dead branch.  MetafileToRenderer::CommandDrawText
(core/DesktopEditor/graphics/MetafileToRenderer.cpp:122) uses GetGIDByUnicode as
its "does this font have this character?" test, and substitutes a different face
when it says no - so symbol text inside an EMF/WMF metafile was drawn in the
wrong font.

The two functions are otherwise character-identical, which is what makes this a
typo rather than a decision.  This test extracts BOTH out of FontFile.cpp by
brace matching and drives them over a stub charmap that behaves the way a
symbolic face does, asserting that the two now agree - CacheGlyph being the one
that was always right.

  BASELINE=1 re-reads FontFile.cpp from git HEAD, where it must FAIL.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
REL = 'DesktopEditor/fontengine/FontFile.cpp'
# Pinned to the parent of the commit that landed this fix. It must NOT default to
# HEAD: once the fix is committed HEAD carries it, the baseline stops differing,
# and the test passes forever while testing nothing.
BASE_REF = os.environ.get('BASE_REF', '1269b750a9^')

if os.environ.get('BASELINE'):
    src = subprocess.run(['git', '-C', CORE, 'show', '%s:%s' % (BASE_REF, REL)],
                         capture_output=True, text=True, check=True).stdout
else:
    src = open(os.path.join(CORE, REL), encoding='utf-8').read()


def block(text, start):
    ob = text.index('{', start)
    depth = 0
    for i in range(ob, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise SystemExit('unbalanced braces')


# The function under test.
m = re.search(r'^int CFontFile::GetGIDByUnicode\(int code\)\s*$', src, re.M)
if not m:
    raise SystemExit('CFontFile::GetGIDByUnicode not found - the extractor needs updating')
gid_fn = block(src, m.start()).replace('CFontFile::', 'Face::', 1)

# The reference: lift only CacheGlyph's symbolic-retry decision, which is the
# part being compared. Select it by what it does - it is the one occurrence that
# applies the 0xF000 offset - not by position.
mc = re.search(
    r'\tint unGID = m_bStringGID \? code : SetCMapForCharCode\(code, &nCMapIndex\);\n'
    r'\n?\tif \(unGID <= 0 && !m_bStringGID\)\n'
    r'\t\{\n'
    r'\t\tif \(-1 != m_nSymbolic && code < 0xF000\)\n'
    r'\t\t\tunGID = SetCMapForCharCode\(code \+ 0xF000, &nCMapIndex\);\n'
    r'\t\}', src)
if not mc:
    raise SystemExit('CacheGlyph\'s symbolic retry (code + 0xF000) not found - '
                     'the reference this is compared against is gone')
reference = mc.group(0)

harness = r'''
#include <stdio.h>

/* A stand-in for the face, behaving the way a symbolic font's cmap does: it
 * answers only in the 0xF000-0xF0FF private-use range, and 0 (meaning "no such
 * glyph") for the bare codepoint. */
struct Face {
    bool m_bStringGID;
    int  m_nSymbolic;
    int  nLookups;

    int SetCMapForCharCode(int code, int *pnCMapIndex)
    {
        nLookups++;
        *pnCMapIndex = 0;
        if (code >= 0xF020 && code <= 0xF0FF)
            return code - 0xF000 + 1000;   /* some non-zero glyph index */
        return 0;
    }

    int GetGIDByUnicode(int code);

    /* CacheGlyph's symbolic-retry decision, lifted verbatim. */
    int cacheGlyphGID(const int &code)
    {
        int nCMapIndex = 0;
%(reference)s
        return unGID;
    }
};

%(gid_fn)s

static int failures = 0;
static void check(bool ok, const char *what)
{
    printf("  %%-64s %%s\n", what, ok ? "ok" : "FAILED");
    if (!ok) failures++;
}

int main()
{
    printf("a symbolic face, characters living at code + 0xF000:\n");
    static const int codes[] = { 0x20, 0x41, 0x61, 0x7E, 0xFF };
    for (unsigned i = 0; i < sizeof(codes) / sizeof(codes[0]); ++i)
    {
        Face f; f.m_bStringGID = false; f.m_nSymbolic = 1; f.nLookups = 0;
        int got = f.GetGIDByUnicode(codes[i]);

        Face r; r.m_bStringGID = false; r.m_nSymbolic = 1; r.nLookups = 0;
        int want = r.cacheGlyphGID(codes[i]);

        char buf[160];
        snprintf(buf, sizeof buf,
                 "code 0x%%02X: GetGIDByUnicode=%%d, CacheGlyph=%%d",
                 codes[i], got, want);
        check(got == want && got != 0, buf);
    }

    printf("\nthings that must not change:\n");
    {
        /* A non-symbolic face must not be retried at all. */
        Face f; f.m_bStringGID = false; f.m_nSymbolic = -1; f.nLookups = 0;
        int got = f.GetGIDByUnicode(0x41);
        check(got == 0 && f.nLookups == 1,
              "a non-symbolic face is looked up once and not retried");
    }
    {
        /* A hit on the first lookup must not be retried either. */
        Face f; f.m_bStringGID = false; f.m_nSymbolic = 1; f.nLookups = 0;
        int got = f.GetGIDByUnicode(0xF041);
        check(got != 0 && f.nLookups == 1,
              "a codepoint already in the private-use range is not retried");
    }
    {
        /* StringGID mode passes the glyph index straight through. */
        Face f; f.m_bStringGID = true; f.m_nSymbolic = 1; f.nLookups = 0;
        int got = f.GetGIDByUnicode(2835);
        check(got == 2835 && f.nLookups == 0,
              "m_bStringGID passes the glyph index through untouched");
    }

    printf("\n%%s\n", failures
           ? "FAILED"
           : "ok - symbolic faces are retried at code + 0xF000, as CacheGlyph does");
    return failures ? 1 : 0;
}
''' % {'gid_fn': gid_fn, 'reference': reference}

with tempfile.TemporaryDirectory() as d:
    cpp = os.path.join(d, 'harness.cpp')
    exe = os.path.join(d, 'harness')
    open(cpp, 'w', encoding='utf-8').write(harness)
    c = subprocess.run(['clang++', '-std=c++14', '-Wall', '-o', exe, cpp],
                       capture_output=True, text=True)
    if c.returncode != 0:
        sys.stderr.write(c.stdout + c.stderr)
        raise SystemExit('harness did not compile')
    sys.exit(subprocess.run([exe]).returncode)
