#!/usr/bin/env python3
"""
#2433 - a charmap that lacks the character erased the hit an earlier charmap had
already found, so a lookup returned 0 for a character the face can actually draw.

BACK-FILLED. The fix was committed earlier with no test; see the verification
status section of UPSTREAM_TRIAGE.md.

SetCMapForCharCode walks a face's charmaps looking for one that can render the
character. The old line was

    if ( nCharIndex = FT_Get_Char_Index( m_pFace, lUnicode ) )

- an assignment inside the condition. Every charmap it tries writes to nCharIndex,
so a later one that returns 0 wipes out an earlier hit. The face can draw the
character, the function says it cannot, and the glyph is dropped or substituted.

The whole of SetCMapForCharCode cannot be compiled here - it needs FreeType and a
real face. What decides the bug is the assignment discipline in the loop, and that
is what this lifts out and drives, against a stand-in FT_Get_Char_Index whose
per-charmap answers the test controls.

NOTE ON THE BASELINE: a back-filled test cannot baseline against HEAD, which
already contains the fix. The default below is the commit before it landed.

  ./extract_and_run.py              -> passes
  BASELINE=1 ./extract_and_run.py   -> fails, at ee2677f68d^
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(HERE, '..', '..', 'core')
REL = 'DesktopEditor/fontengine/FontFile.cpp'
BASE_REF = os.environ.get('BASE_REF', 'ee2677f68d^')

if os.environ.get('BASELINE'):
    source = subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, REL)],
                            capture_output=True, text=True, check=True).stdout
else:
    source = open(os.path.join(REPO, REL), encoding='utf-8').read()

# The body that records a hit, lifted verbatim: either the guarded form (fixed) or
# the assign-in-condition form (broken).
# SetCMapForCharCode has two of these. The first is the Unicode branch, which
# returns as soon as it finds a glyph - a later charmap cannot erase anything there.
# The defect is in the *legacy* branch, which records and keeps looping; it is the
# one that sets pFoundCharMap and does not return. Pick by that, not by position.
def pick(pattern):
    for m in re.finditer(pattern, source):
        if 'pFoundCharMap' in m.group(0) and 'return' not in m.group(0):
            return m
    return None

fixed = pick(r'FT_UInt nFoundIndex = FT_Get_Char_Index\( m_pFace, lUnicode \);\s*\n'
             r'\s*if \( nFoundIndex \)\s*\n\s*\{(?:[^{}]*)\}')
broken = pick(r'if \( nCharIndex = FT_Get_Char_Index\( m_pFace, lUnicode \) \)\s*\n'
              r'\s*\{(?:[^{}]*)\}')
body = (fixed or broken)
if body is None:
    sys.stderr.write('the charmap-hit block was not found in %s\n' % REL)
    sys.exit(2)
snippet = body.group(0)

harness = r'''
#include <stdio.h>

typedef unsigned int FT_UInt;

/* A face with three charmaps. Only the one named below can draw the character;
   the others answer 0, which is what used to erase the hit. */
static int  g_current = 0;
static int  g_hasItAt  = -1;
static void *m_pFace = 0;
static FT_UInt FT_Get_Char_Index(void *, long) {
    return (g_current == g_hasItAt) ? 77u : 0u;
}

static int  nCharIndex;
static int  cmapIndexOut;
static void *pFoundCharMap;

static int lookup(int nCharmaps, int hasItAt) {
    nCharIndex = 0; cmapIndexOut = -1; pFoundCharMap = 0;
    g_hasItAt = hasItAt;
    long lUnicode = 0xAC00;
    int *pnCMapIndex = &cmapIndexOut;

    for (int nIndex = 0; nIndex < nCharmaps; ++nIndex) {
        g_current = nIndex;
        void *pCharMap = (void *)(long)(nIndex + 1);
        (void)pCharMap;
%(snippet)s
    }
    return nCharIndex;
}

static int failures = 0;
static void check(int nCharmaps, int hasItAt, int want, const char *why) {
    int got = lookup(nCharmaps, hasItAt);
    printf("  %%-56s glyph=%%-4d %%s\n", why, got, got == want ? "ok" : "FAILED");
    if (got != want) failures++;
}

int main() {
    check(3, 0, 77, "first charmap has it, two later ones do not");
    check(3, 1, 77, "middle charmap has it, a later one does not");
    check(3, 2, 77, "last charmap has it");
    check(3, -1, 0, "no charmap has it - must still report nothing");
    check(1, 0, 77, "single charmap, has it");

    printf("\n%%s\n", failures ? "FAILED"
        : "ok - a charmap without the character cannot erase one that has it");
    return failures ? 1 : 0;
}
''' % {'snippet': snippet}

with tempfile.TemporaryDirectory() as d:
    src = os.path.join(d, 'harness.cpp')
    exe = os.path.join(d, 'harness')
    open(src, 'w').write(harness)
    c = subprocess.run(['clang++', '-std=c++14', '-w', '-o', exe, src],
                       capture_output=True, text=True)
    if c.returncode != 0:
        sys.stderr.write(c.stdout + c.stderr)
        raise SystemExit('harness did not compile')
    sys.exit(subprocess.run([exe]).returncode)
