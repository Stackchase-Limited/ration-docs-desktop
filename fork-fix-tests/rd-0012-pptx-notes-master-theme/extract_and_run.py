#!/usr/bin/env python3
"""
RD-0012 (our corpus run, no upstream issue): saving a presentation whose editor
binary has notes (or a notes master) but no notes-master theme relation crashed
x2t (SIGSEGV), so the save failed.

Found with an AddressSanitizer x2t on LibreOffice's sd/qa/unit/data/odp/
tdf168109.fodp (and one more ODP): open -> Editor.bin worked, the save back
(Editor.bin -> PPTX -> ODP) stopped with SEGV on address 0 in
NSBinPptxRW::CPPTXWriter::OpenPPTY (OOXML/Binary/Presentation/PPTXWriter.cpp).

Cause: OpenPPTY fills m_arNotesMasters_Theme from the NotesMastersRels table and
then, whenever the binary has a notes master or any notes slide, calls
StartThemeNotesMaster(m_arNotesMasters_Theme[0]) / CreateDefaultNotesMasters(
m_arNotesMasters_Theme[0]). When that table is missing or empty the vector is
empty and [0] dereferences its null data pointer. The handout master had the
same unguarded [0]. Fix: an empty vector falls back to theme 0 (the first
theme, the one every presentation has).

What runs: the REAL "// noteMasters" section of CPPTXWriter::OpenPPTY (the
text between that comment and "// handoutMasters", git show BASE_REF:... with
BASELINE=1) is compiled with -fsanitize=address inside a stand-in object that
has the members it touches (the main-table map, a reader returning a notes
master count, the rels writer, NotesMaster/CPath/xml writer stand-ins that
record calls). Two cases: no notes master but one notes slide (default notes
master), and one notes master; both with an empty m_arNotesMasters_Theme.
Passes when ASan reports nothing and theme 0 was used in both.

NOT claimed: the handout-master half of the change is not run (same pattern,
one line); the produced PPTX/ODP was checked by hand with the rebuilt x2t only.

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read PPTXWriter.cpp at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0012 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '67a534fc58^')
BASELINE = bool(os.environ.get('BASELINE'))


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig', 'replace')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig', errors='replace').read()


DRIVER = r'''
#include <cstdio>
#include <map>
#include <string>
#include <vector>
typedef long LONG;
#define FILE_SEPARATOR_STR L"/"
namespace NSBinPptxRW { namespace NSMainTables { enum { NotesMasters = 1 }; } }
namespace NSDirectory { inline bool CreateDirectory(const std::wstring&) { return true; } }
namespace OOX { struct CPath { std::wstring p; CPath(const std::wstring& s) : p(s) {}
    CPath operator+(const std::wstring& s) const { return CPath(p + s); } std::wstring GetPath() const { return p; } };
    inline CPath operator+(const CPath& a, const CPath& b) { return CPath(a.p + b.p); } }
struct Rels { int theme = -1; void Clear() {} void StartThemeNotesMaster(int t) { theme = t; } void CloseRels() {}
    void SaveRels(const std::wstring&) {} };
struct Reader { LONG count = 0; Rels rels; Rels* m_pRels = &rels; void Seek(LONG) {} LONG GetLong() { return count; } };
struct XmlWriter { void ClearNoAttack() {} void SaveToFile(const std::wstring&) {} };
namespace PPTX { struct NotesMaster { NotesMaster(void*) {} void fromPPTY(Reader*) {} void toXmlWriter(XmlWriter*) {} }; }
struct Writer {
    std::map<int, LONG> m_mainTables;
    Reader m_oReader;
    std::wstring m_strDstFolder = L"/tmp/x";
    std::vector<int> m_arNotesSlides;
    std::vector<PPTX::NotesMaster> m_arNotesMasters;
    std::vector<unsigned int> m_arNotesMasters_Theme;
    int m_oDocument = 0;
    int defaultTheme = -1;
    void CreateDefaultNotesMasters(int t) { defaultTheme = t; }
    void run() {
        std::map<int, LONG>::iterator pPair;
        XmlWriter oXmlWriter;
        bool bNotesMasterPresent = false;
@@SECTION@@
        (void)bNotesMasterPresent;
    }
};
int main() {
    { Writer w; w.m_mainTables[1] = 0; w.m_oReader.count = 0; w.m_arNotesSlides.push_back(1);
      w.run(); printf("DEFAULT theme=%d\n", w.defaultTheme); }
    { Writer w; w.m_mainTables[1] = 0; w.m_oReader.count = 1;
      w.run(); printf("MASTER theme=%d\n", w.m_oReader.rels.theme); }
    return 0;
}
'''


def main():
    src = read('OOXML/Binary/Presentation/PPTXWriter.cpp')
    a = src.find('// noteMasters')
    b = src.find('// handoutMasters', a)
    if a < 0 or b < 0:
        sys.exit('notes master section not found - the extractor needs updating')
    section = src[a:b]
    work = tempfile.mkdtemp(prefix='rd0012-')
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write(DRIVER.replace('@@SECTION@@', section))
    exe = os.path.join(work, 'drv')
    r = subprocess.run(['c++', '-std=gnu++11', '-fsanitize=address', '-g', '-w', p, '-o', exe],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-3000:])
    r = subprocess.run([exe], capture_output=True, text=True, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
    out = r.stdout + r.stderr
    m = re.search(r'ERROR: AddressSanitizer: ([\w-]+)', out)
    ok = r.returncode == 0 and not m and 'DEFAULT theme=0' in out and 'MASTER theme=0' in out
    print(('ok   ' if ok else 'FAIL ') + 'notes master with no NotesMastersRels (%s): %s' % (
        'baseline ' + BASE_REF if BASELINE else 'working tree',
        ('ASan ' + m.group(1)) if m else ('theme 0 used' if ok else out.strip()[-300:])))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
