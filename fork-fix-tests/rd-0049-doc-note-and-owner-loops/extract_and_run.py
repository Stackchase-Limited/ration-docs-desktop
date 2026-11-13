#!/usr/bin/env python3
"""
RD-0049 (our corpus run, no upstream issue): two loops never ended on damaged
.doc files, and x2t wrote/allocated until it was killed:

- LibreOffice's sw/qa/core/data/ww6/pass/hang-1.doc: FootnotesMapping::Apply
  (MsBinaryFile/DocFile/FootnotesMapping.cpp) loops while cp <= ccpText +
  ccpFtn - 2; for each footnote the inner loop advances cp to the next CP of
  IndividualFootnotesPlex. Past the plex's last entry operator[] returns -1, the
  inner loop does not run, cp stays put, and an empty <w:footnote> was appended
  forever (a 350 MB string when ASan stopped it). EndnotesMapping::Apply has the
  same loop. Fix: both stop when the plex has no further entry.
- LibreOffice's ww6/pass/crash-3.doc: AnnotationOwnerList (AnnotationOwnerList.
  cpp) read Xsts while the position was below fc + lcbGrpXstAtnOwners; at the end
  of the stream nothing is read, the position stops moving, and empty names
  were pushed until memory ran out. Fix: it also stops at the end of the stream.

What runs (git show BASE_REF:... with BASELINE=1):
- the REAL note loops of FootnotesMapping::Apply and EndnotesMapping::Apply,
  from "int cp =" to the end of the outer while, inside a stand-in mapping
  (writer that counts notes and gives up at 100,000; FindFileCharPos = cp;
  writeParagraph = next cp; no tables). Cases: a FIB note count running past the
  plex (2 notes in the plex, ccp 50: 2 notes, then stop), and a plex that ends
  with the story (ccp 22, CPs 0/10/21: 2 notes, unchanged);
- the REAL AnnotationOwnerList constructor with a stand-in reader whose Xsts are
  3 bytes, lcbGrpXstAtnOwners 1,000,000 over a 12-byte stream (4 names, then
  stop; the stand-in gives up at 100,000), and lcb 12 (4 names, unchanged).

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read the sources at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0049 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '92fd47c76c^')
BASELINE = bool(os.environ.get('BASELINE'))
D = 'MsBinaryFile/DocFile/'


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig', 'replace')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig', errors='replace').read()


def func(src, sig):
    a = src.find(sig)
    if a < 0:
        sys.exit(sig + ' not found - the extractor needs updating')
    i = src.find('{', a); depth = 0
    while True:
        if src[i] == '{': depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0: return src[a:i + 1]
        i += 1


def note_loop(src, rel):
    a = src.find('int cp =')
    w = src.find('while', a)
    if a < 0 or w < 0:
        sys.exit('note loop not found in %s - the extractor needs updating' % rel)
    return src[a:w] + func(src[w:], 'while')


NOTES = r'''
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>
#define TRUE true
#define FALSE false
struct RgLw97 { int ccpText, ccpFtn, ccpHdr, ccpAtn, ccpEdn; }; struct FIB_ { RgLw97 m_RgLw97; };
struct PlexStub { std::vector<int> cps; int operator[](unsigned int i) const { return i < cps.size() ? cps[i] : -1; } };
struct Doc { FIB_* FIB; PlexStub* IndividualFootnotesPlex; PlexStub* IndividualEndnotesPlex; int nWordVersion; int FindFileCharPos(int cp) { return cp; } };
struct Writer { int notes; void WriteNodeBegin(const wchar_t* n, bool) { if (std::wstring(n) == L"w:footnote" || std::wstring(n) == L"w:endnote")
    if (++notes > 100000) { printf("notes>100000\n"); exit(0); } }
  void WriteAttribute(const wchar_t*, const std::wstring&) {} void WriteNodeEnd(const wchar_t*, bool = true, bool = true) {} };
struct FormatUtils { static std::wstring IntToWideString(int) { return L""; } };
struct ParagraphPropertyExceptions {};
struct TableInfo { bool fInTable; int iTap; TableInfo(ParagraphPropertyExceptions*, int) : fInTable(false), iTap(0) {} };
struct Mapping;
struct Table { Table(Mapping*, int, int) {} void Convert(Mapping*) {} int GetCPEnd() { return 0; } };
struct Mapping { Doc* m_document; Writer* m_pXmlWriter;
  ParagraphPropertyExceptions* findValidPapx(int) { return NULL; } int writeParagraph(int cp, int) { return cp + 1; }
  void Run() { int id = @@ID@@; int index = 0;
@@LOOP@@
  } };
int main(int argc, char** argv) {
  bool past = argv[1][0] == 'p';
  FIB_ fib = {}; fib.m_RgLw97.ccpText = 100; fib.m_RgLw97.ccpFtn = 0; fib.m_RgLw97.ccpEdn = 0;
  PlexStub plex; int c[] = {0, 10, past ? 20 : 21}; plex.cps.assign(c, c + 3);
  if (@@FOOT@@) fib.m_RgLw97.ccpFtn = past ? 50 : 22; else fib.m_RgLw97.ccpEdn = past ? 50 : 22;
  Doc d = { &fib, &plex, &plex, 0 }; Writer w = { 0 }; Mapping m = { &d, &w }; m.Run();
  printf("notes=%d\n", w.notes); return 0;
}
'''

OWNERS = r'''
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>
namespace POLE { struct Stream {}; }
namespace DocFileFormat {
struct FibWord97 { unsigned int fcGrpXstAtnOwners, lcbGrpXstAtnOwners; }; struct FileInformationBlock { FibWord97 m_FibWord97; int m_nWordVersion; };
struct VirtualStreamReader { unsigned long position; VirtualStreamReader(POLE::Stream*, unsigned int p, int) : position(p) {}
  unsigned long GetSize() const { return 12; } unsigned long GetPosition() const { return position; }
  std::wstring ReadXst() { if (position < 12) position += 3; return L"x"; } };   // 3-byte Xsts; nothing is read past the end
struct AnnotationOwnerList : std::vector<std::wstring> { AnnotationOwnerList(FileInformationBlock* fib, POLE::Stream* tableStream);
  void push_back(const std::wstring& s) { if (size() >= 100000) { printf("names>=100000\n"); exit(0); } std::vector<std::wstring>::push_back(s); } };
@@CTOR@@
}
using namespace DocFileFormat;
int main(int argc, char** argv) {
  FileInformationBlock fib = {}; fib.m_FibWord97.fcGrpXstAtnOwners = 0; fib.m_FibWord97.lcbGrpXstAtnOwners = argv[1][0] == 'p' ? 1000000 : 12;
  POLE::Stream s; AnnotationOwnerList l(&fib, &s); printf("names=%zu\n", l.size()); return 0;
}
'''


def build_run(work, name, code, cases):
    p = os.path.join(work, name + '.cpp')
    open(p, 'w').write(code)
    exe = p[:-4]
    r = subprocess.run(['c++', '-std=gnu++11', '-w', p, '-o', exe], capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed (%s):\n%s' % (name, r.stderr[-3000:]))
    fails = 0
    for arg, label, want in cases:
        r = subprocess.run([exe, arg], capture_output=True, text=True, timeout=120)
        out = r.stdout.strip()
        ok = r.returncode == 0 and out == want
        fails += not ok
        print(('ok   ' if ok else 'FAIL ') + '%s (%s): %s' % (label, 'baseline ' + BASE_REF if BASELINE else 'working tree',
              out or 'rc=%d' % r.returncode))
    return fails


def main():
    work = tempfile.mkdtemp(prefix='rd0049-')
    fails = 0
    for rel, foot, idv, kind in (('FootnotesMapping.cpp', 'true', '1', 'Footnotes'), ('EndnotesMapping.cpp', 'false', '0', 'Endnotes')):
        loop = note_loop(read(D + rel), rel)
        code = NOTES.replace('@@LOOP@@', loop).replace('@@FOOT@@', foot).replace('@@ID@@', idv)
        fails += build_run(work, kind, code, [('p', '%s: FIB count runs past the plex' % kind, 'notes=2'),
                                              ('n', '%s: plex ends with the story (unchanged)' % kind, 'notes=2')])
    ctor = func(read(D + 'AnnotationOwnerList.cpp'), 'AnnotationOwnerList::AnnotationOwnerList(')
    fails += build_run(work, 'owners', OWNERS.replace('@@CTOR@@', ctor),
                       [('p', 'comment owners: lcb 1,000,000 over a 12-byte stream', 'names=4'),
                        ('n', 'comment owners: lcb 12 (unchanged)', 'names=4')])
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
