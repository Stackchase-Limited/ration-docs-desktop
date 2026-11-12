#!/usr/bin/env python3
"""
RD-0054 (UPSTREAM_TRIAGE.md "Latent problems": "ApplicationFontsWorker.cpp:1123
is off by one"): the last range of the font ranges table
(window["__fonts_ranges"] in AllFonts.js, and the same range in the range
builder) ended at nMaxSymbol - 1 (U+10FFFE) although the loop that builds it
runs through nMaxSymbol (U+10FFFF). Every other range is written inclusive
(start, i - 1). Effect: U+10FFFF lost its font, and a last range that starts
at U+10FFFF came out inverted (start 0x10FFFF, end 0x10FFFE). Small - U+10FFFF
is a noncharacter - but the table was wrong. Fix: the last range ends at
nMaxSymbol.

What runs: the REAL range-writing code - everything between
`window["__fonts_ranges"] = [` and the trailing-comma trim in
ApplicationFontsWorker.cpp, extracted as text (git show BASE_REF:... with
BASELINE=1) - compiled against small stubs for the JS writer, the range
builder and the font tables, over a symbol map with font 0 at U+0041..U+005A
and font 1 from U+100000 to the end. Passes when the table is exactly
65,90,0, 1048576,1114111,1 and the range builder got the same.

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read ApplicationFontsWorker.cpp at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0054 commit
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', 'c7561e4bb0^')
BASELINE = bool(os.environ.get('BASELINE'))


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig', 'replace')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig', errors='replace').read()


def main():
    src = read('DesktopEditor/fontengine/ApplicationFontsWorker.cpp')
    start_marker = 'oWriterJS += L"window[\\"__fonts_ranges\\"] = [\\n";'
    end_marker = 'oWriterJS.SetCurSize(oWriterJS.GetCurSize() - 1);'
    a = src.find(start_marker)
    b = src.find(end_marker, a)
    if a < 0 or b < 0:
        sys.exit('range writer not found - the extractor needs updating')
    body = src[a + len(start_marker):b]
    drv = r'''
#include <cstdio>
#include <string>
#include <vector>
#include <map>
struct JS { std::string s; void AddInt(int v) { s += std::to_string(v); } void AddCharSafe(char c) { s += c; } };
struct RB { std::string s; void WriteStringUTF8(const std::wstring&) { s += "|"; } void WriteInt(int v) { s += std::to_string(v) + ","; } };
struct FP { std::wstring name; };
int main() {
    int nMaxSymbol = 0x10FFFF;
    static int arSymbolsAll[0x10FFFF + 1];
    for (int u = 0x41; u <= 0x5A; ++u) arSymbolsAll[u] = 1;
    for (int u = 0x100000; u <= 0x10FFFF; ++u) arSymbolsAll[u] = 2;
    int nSumPriority = 1000;
    int nRangeBuilderCount = 0;
    JS oWriterJS;
    RB oRB; RB* pRangeBuilder = &oRB;
    std::vector<FP> arrFontsPriority(2); arrFontsPriority[0].name = L"A"; arrFontsPriority[1].name = L"B";
    std::map<std::wstring, int> mapFontIndexes; mapFontIndexes[L"A"] = 0; mapFontIndexes[L"B"] = 1;
''' + body + r'''
    printf("JS=%s\nRB=%s\nN=%d\n", oWriterJS.s.c_str(), oRB.s.c_str(), nRangeBuilderCount);
    return 0;
}
'''
    work = tempfile.mkdtemp(prefix='rd0054-')
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write(drv)
    exe = os.path.join(work, 'drv')
    r = subprocess.run(['c++', '-std=gnu++11', '-w', '-O0', p, '-o', exe], capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-2000:])
    r = subprocess.run([exe], capture_output=True, text=True)
    out = r.stdout.strip()
    ok = r.returncode == 0 and 'JS=65,90,0,1048576,1114111,1,\n' in out + '\n' and 'RB=|65,90,|1048576,1114111,' in out
    print(('ok   ' if ok else 'FAIL ') + 'font ranges last range end (%s): %s' % (
        'baseline ' + BASE_REF if BASELINE else 'working tree', out.replace('\n', '; ') or 'rc=%d' % r.returncode))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
