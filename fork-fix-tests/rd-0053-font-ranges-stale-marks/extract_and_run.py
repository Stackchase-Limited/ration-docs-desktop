#!/usr/bin/env python3
"""
RD-0053 (found while checking the ApplicationFontsWorker off-by-one listed in
UPSTREAM_TRIAGE.md "Latent problems"): building the font ranges table
(window["__fonts_ranges"] in AllFonts.js, which picks the fallback font per
code point) could credit a font with characters it does not have.

Cause (core/DesktopEditor/fontengine/ApplicationFontsWorker.cpp,
CSymbolSimpleChecker2::Apply1 and Apply2): the per-font scratch marks are
cleared with `memset(m_pTmpSymbols, 0, m_nMax - m_nMin)` - from index 0, not
from m_nMin, and one short. Every mark in [m_nMax - m_nMin, m_nMax] survived
into the next font (for a font whose characters all sit high - emoji, CJK
extension, PUA - none were cleared at all). A character present in only some
styles of font A (so A was not credited) then counted for font B if B's own
characters spanned it: B was entered in the table for a character it lacks,
which renders as a missing glyph instead of falling back. Fix: clear exactly
[m_nMin, m_nMax].

What runs: the REAL class CSymbolSimpleChecker2 is lifted out by brace matching
(git show BASE_REF:... with BASELINE=1) and driven like the worker does: font A
has U+1F600 in its regular face only (regular + bold, mask 3), font B (regular
only) has U+1F5FF and U+1F601 but not U+1F600; then a font C with no glyphs is
applied to show the scratch buffer is clean. Passes when U+1F600 is credited to
nobody and B keeps its own two characters.

Real fonts (checked once, not by this test): allfontsgen linked with the old
and the fixed ApplicationFontsWorker.cpp over this Mac's system fonts gave
ranges differing at 84 code points; with fontTools, the old table assigned
all 84 to a font whose cmap lacks them (e.g. U+FB06 to Muna instead of Big
Caslon, U+11660 to Noto Sans Mro instead of Noto Sans Mongolian), the fixed
one none. Other machines' font sets will differ.

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read ApplicationFontsWorker.cpp at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0053 commit
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '66e4c6ed0d^')
BASELINE = bool(os.environ.get('BASELINE'))


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig', 'replace')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig', errors='replace').read()


def block(text, start):
    a = text.find(start)
    if a < 0:
        sys.exit('%r not found - the extractor needs updating' % start)
    b = text.find('{', a)
    depth = 0
    for i in range(b, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[a:i + 1] + ';'
    sys.exit('unbalanced braces after %r' % start)


def main():
    cls = block(read('DesktopEditor/fontengine/ApplicationFontsWorker.cpp'),
                'class CSymbolSimpleChecker2 : public NSFonts::CApplicationFontsSymbolsChecker')
    drv = r'''
#include <cstdio>
#include <cstring>
typedef unsigned char BYTE;
#define RELEASEARRAYOBJECTS(p) do { delete[] (p); (p) = 0; } while (0)
namespace NSFonts { class CApplicationFontsSymbolsChecker { public: virtual ~CApplicationFontsSymbolsChecker() {}
    virtual void Check(const int& nCode, const unsigned int& nIndex) = 0; }; }
''' + cls + r'''
int main() {
    const int nMax = 0x10FFFF;
    static int all[0x10FFFF + 1];
    CSymbolSimpleChecker2 c(all, nMax);
    // font A, priority 1: regular has U+1F600..U+1F602, bold only U+1F601..U+1F602
    c.m_nPriority = 1;
    c.m_nStyle = 1; for (int u = 0x1F600; u <= 0x1F602; ++u) c.Check(u, 0);
    c.m_nStyle = 2; for (int u = 0x1F601; u <= 0x1F602; ++u) c.Check(u, 0);
    c.Apply1(3);
    // font B, priority 2, regular only: U+1F5FF and U+1F601, NOT U+1F600
    c.m_nPriority = 2;
    c.m_nStyle = 1; c.Check(0x1F5FF, 0); c.Check(0x1F601, 0);
    c.Apply1(1);
    printf("U+1F5FF=%d U+1F600=%d U+1F601=%d U+1F602=%d\n", all[0x1F5FF], all[0x1F600], all[0x1F601], all[0x1F602]);
    int dirty = 0;
    for (int i = 0; i <= nMax; ++i) if (c.m_pTmpSymbols[i]) ++dirty;
    printf("DIRTY=%d\n", dirty);
    return 0;
}
'''
    work = tempfile.mkdtemp(prefix='rd0053-')
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write(drv)
    exe = os.path.join(work, 'drv')
    r = subprocess.run(['c++', '-std=gnu++11', '-w', '-O0', p, '-o', exe], capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-2000:])
    r = subprocess.run([exe], capture_output=True, text=True)
    out = r.stdout.strip()
    ok = r.returncode == 0 and 'U+1F5FF=2 U+1F600=0 U+1F601=1 U+1F602=1' in out and 'DIRTY=0' in out
    print(('ok   ' if ok else 'FAIL ') + 'font ranges scratch marks (%s): %s' % (
        'baseline ' + BASE_REF if BASELINE else 'working tree', out.replace('\n', '; ') or 'rc=%d' % r.returncode))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
