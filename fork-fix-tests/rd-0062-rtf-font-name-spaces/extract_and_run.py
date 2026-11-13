#!/usr/bin/env python3
"""
RD-0062 - an RTF saved by the editors came back with its multi-word font names run together
(found while checking #2446: a numbered list in Times New Roman, saved as RTF and reopened, had
its numbers in a font called "TimesNewRoman").

Our RTF writer puts every font name out as \\uN escapes ({\\uc1\\u84*\\u105*...\\u32*...};).
The reader hands each \\uN to the destination as a piece of its own
(core RtfFile/Format/RtfReader.cpp, Keyword "u" -> ExecuteText), and
RtfFontTableReader::ExecuteText (RtfFile/Format/DestinationCommand.cpp) trimmed every piece
before appending it to the name - so each \\u32 (space) became "" and "Times New Roman" became
"TimesNewRoman", a font no system has: the text falls back to another face and is saved on with
the broken name. Fix: only the start of the name is trimmed while it is collected, and the end
when ';' completes it.

The REAL RtfFontTableReader::ExecuteText and RemoveLastUnchar are sliced from RD_REPO by brace
matching and compiled against minimal stubs (RtfFont, the font table, boost trim); the pieces are
fed exactly as the reader produces them for
  - our writer's form:   one piece per \\uN, then ";"            -> "Times New Roman"
  - Word's form:         "Times New Roman;" in one piece          -> "Times New Roman"
  - text before a group: "Arial " then ";" (after {\\*\\falt ..})   -> "Arial"
  - leading whitespace:  " ", "Calibri", ";"                      -> "Calibri"
Claimed: those names. NOT claimed here: the end-to-end x2t run (done by hand: RTF with
{\\uc1\\u84*\\u105*\\u109*\\u101*\\u115*\\u32*\\u78*\\u101*\\u119*} -> docx gave w:ascii="TimesNew" with
the old x2t and "Times New" with x2t relinked from the fix; an editor-saved list RTF reopened
with "Times New Roman" instead of "TimesNewRoman").

  python3 fork-fix-tests/rd-0062-rtf-font-name-spaces/extract_and_run.py
  RD_REPO=<core checkout> (default ../../core)   BASELINE=1 reads BASE_REF (must FAIL)
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '16b11bbdc0^')
BASELINE = bool(os.environ.get('BASELINE'))
SRC = 'RtfFile/Format/DestinationCommand.cpp'


def read(rel):
    if BASELINE:
        return subprocess.check_output(['git', '-C', REPO, 'show', BASE_REF + ':' + rel]).decode('utf-8')
    with open(os.path.join(REPO, rel), encoding='utf-8') as f:
        return f.read()


def braces(src, start):
    o = src.index('{', start)
    d = 0
    for i in range(o, len(src)):
        if src[i] == '{':
            d += 1
        elif src[i] == '}':
            d -= 1
            if d == 0:
                return src[start:i + 1]
    raise SystemExit('unbalanced braces')


STUBS = r'''
#include <string>
#include <vector>
#include <cstdio>
#include <cwctype>
namespace boost { namespace algorithm {
    inline void trim_left(std::wstring& s) { size_t i = 0; while (i < s.size() && std::iswspace(s[i])) ++i; s.erase(0, i); }
    inline void trim_right(std::wstring& s) { size_t n = s.size(); while (n > 0 && std::iswspace(s[n - 1])) --n; s.erase(n); }
    inline void trim(std::wstring& s) { trim_right(s); trim_left(s); }
} }
struct RtfFont { std::wstring m_sName, m_sPanose, m_sAltName; void SetDefaultRtf() { m_sName.clear(); m_sPanose.clear(); m_sAltName.clear(); } };
struct RtfFontTable { std::vector<std::wstring> names; void AddFont(const RtfFont& f) { names.push_back(f.m_sName); } };
struct RtfDocument { RtfFontTable m_oFontTable; };
struct RtfReader {};
class RtfFontTableReader {
public:
    enum _InternalState{ is_normal, is_panose, is_altname };
    RtfFont m_oFont; _InternalState m_eInternalState = is_normal;
    std::wstring RemoveLastUnchar(std::wstring str);
    void ExecuteText(RtfDocument& oDocument, RtfReader& oReader, std::wstring sText);
};
'''

MAIN = r'''
static std::string u8(const std::wstring& w) { std::string s; for (wchar_t c : w) s += (char)c; return s; }
int main()
{
    std::vector<std::vector<std::wstring>> cases = {
        {L"T", L"i", L"m", L"e", L"s", L" ", L"N", L"e", L"w", L" ", L"R", L"o", L"m", L"a", L"n", L";"},
        {L"Times New Roman;"},
        {L"Arial ", L";"},
        {L" ", L"Calibri", L";"},
    };
    for (auto& pieces : cases) {
        RtfDocument doc; RtfReader rd; RtfFontTableReader r;
        for (auto& p : pieces) r.ExecuteText(doc, rd, p);
        printf("[%s]\n", doc.m_oFontTable.names.empty() ? "<none>" : u8(doc.m_oFontTable.names[0]).c_str());
    }
    return 0;
}
'''


def main():
    src = read(SRC)
    funcs = []
    for sig in ('std::wstring RtfFontTableReader::RemoveLastUnchar(', 'void RtfFontTableReader::ExecuteText('):
        funcs.append(braces(src, src.index(sig)))
    assert 'm_oFontTable.AddFont' in funcs[1], 'sliced the wrong function'
    tmp = tempfile.mkdtemp(prefix='rd0062-')
    cpp = os.path.join(tmp, 't.cpp')
    with open(cpp, 'w') as f:
        f.write(STUBS + '\n'.join(funcs) + MAIN)
    exe = os.path.join(tmp, 't')
    r = subprocess.run(['c++', '-std=c++11', cpp, '-o', exe], capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stderr[-3000:])
        print('CANNOT RUN: compile failed')
        sys.exit(2)
    out = subprocess.check_output([exe]).decode().split('\n')
    want = ['[Times New Roman]', '[Times New Roman]', '[Arial]', '[Calibri]']
    names = ['name written as \\uN pieces (our RTF writer)', 'name in one piece (Word)',
             'trailing space before a group', 'leading whitespace piece']
    failures = 0
    for i, w in enumerate(want):
        ok = out[i] == w
        failures += not ok
        print(('PASS ' if ok else 'FAIL ') + names[i] + ': got ' + out[i] + ('' if ok else ', want ' + w))
    print('%s: %d failure(s)' % ('BASELINE' if BASELINE else 'FIX', failures))
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
