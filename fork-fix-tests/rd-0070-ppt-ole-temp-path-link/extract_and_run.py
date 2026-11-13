#!/usr/bin/env python3
"""
RD-0070 (our corpus run, no upstream issue): converting a .ppt with embedded
OLE objects (a Word document, an Excel sheet) to .pptx left the objects out of
the package and wrote each one as an EXTERNAL oleObject relationship whose
Target was x2t's temp file, e.g.
  Target="/Users/<name>/.../run.J4Y8bt/ascjuJVAh/bin_2IDddt" TargetMode="External"
That leaks a local path (user name, folders) into the saved file, and the link
is dead as soon as the conversion's temp folder is removed: the object can no
longer be opened or edited. Seen on POI's ole2-embedding-2003.ppt, 41246-1.ppt,
41246-2.ppt whenever the temp folder path has a dot in it (the app's data
folder com.stackchase.rationdocs, ~/.something, run.XXXX, ...).

Cause (MsBinaryFile/PptFile/PPTXWriter/ImageManager.cpp):
CMediaManager::GenerateEmbedding takes the extension from the last '.' of the
WHOLE path. The OLE storage is saved as a temp file without an extension
(bin_XXXXXX), so the "extension" became e.g. ".J4Y8bt/ascjuJVAh/bin_2IDddt",
the copy to ppt/embeddings/oleObject1<that> failed, GenerateEmbedding returned
"" and CRelsGenerator::WriteOleObject fell back to an external link to the
temp file. GenerateMedia had the same extension parsing.
Fix: the extension is looked for in the file name only (FileExtIndex), and
WriteOleObject never links the temp file externally - with no rel the shape
writer keeps the object's picture alone.

What runs: the REAL CMediaManager::GenerateEmbedding and
CRelsGenerator::WriteOleObject (and FileExtIndex when the source has it) are
lifted out of ImageManager.cpp by brace matching (git show BASE_REF:... with
BASELINE=1) and compiled with small stand-ins for OOX::CPath (directory part
of a path), NSDirectory/NSFile (real mkdir/copy) and the rels writer. A real
temp file <work>/x.y/run.Ab12/ascQ/bin_XYZ is embedded with the temp folder
<work>/x.y/run.Ab12/ascQ, as the converter does.
Passes when the rel is "../embeddings/oleObject1.bin", that file exists with
the object's bytes, and, when GenerateOleObject fails, WriteOleObject writes
no external rel. NOT claimed: PowerPoint opening the object (checked by hand:
the fixed x2t puts oleObject1.bin/oleObject2.bin in ppt/embeddings with
internal rels for ole2-embedding-2003.ppt).

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read ImageManager.cpp at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0070 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '73091a378a^')
BASELINE = bool(os.environ.get('BASELINE'))
REL = 'MsBinaryFile/PptFile/PPTXWriter/ImageManager.cpp'


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig', 'replace')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig', errors='replace').read()


def block(text, start, required=True):
    a = text.find(start)
    if a < 0:
        if required:
            sys.exit('%r not found - the extractor needs updating' % start)
        return ''
    b = text.find('{', a)
    depth = 0
    for i in range(b, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[a:i + 1]
    sys.exit('unbalanced braces after %r' % start)


DRIVER = r'''
#include <cstdio>
#include <string>
#include <map>
#include <fstream>
#include <sys/stat.h>
namespace OOX { struct CPath { std::wstring p; CPath(const std::wstring& s) : p(s) {}
    std::wstring GetPath() { size_t k = p.find_last_of(L"/"); return k == std::wstring::npos ? L"" : p.substr(0, k); } }; }
static std::string N(const std::wstring& w) { return std::string(w.begin(), w.end()); }
namespace NSDirectory { inline bool CreateDirectory(const std::wstring& d) { mkdir(N(d).c_str(), 0755); return true; } }
namespace NSFile { struct CFileBinary { static bool Copy(const std::wstring& a, const std::wstring& b) {
    std::ifstream i(N(a), std::ios::binary); if (!i) return false; std::ofstream o(N(b), std::ios::binary); if (!o) return false;
    o << i.rdbuf(); return (bool)o; } }; }
std::wstring CorrectXmlString3(const std::wstring& s) { return s; }
struct CMediaManager {
    std::map<std::wstring, std::wstring> m_mapMedia; std::wstring m_strTempMedia, m_strDstEmbeddings; long m_lIndexNextOleObject = 0;
    bool m_bFail = false;
    std::wstring GenerateEmbedding(const std::wstring &strInput, const std::wstring &Template, long &Indexer, const std::wstring &strDefaultExt);
    std::wstring GenerateOleObject(const std::wstring& s) { return m_bFail ? L"" : GenerateEmbedding(s, L"oleObject", m_lIndexNextOleObject, L".bin"); }
};
struct CRelsGenerator { CMediaManager* m_pManager; std::wstring m_sRels;
    std::wstring WriteHyperlinkOleObject(const std::wstring& t, bool bExternal) {
        m_sRels += L"<Relationship Id=\"rId1\" Target=\"" + t + L"\"" + (bExternal ? L" TargetMode=\"External\"" : L"") + L"/>"; return L"rId1"; }
    std::wstring WriteOleObject(const std::wstring& strOleObjectPath);
};
@@EXT@@
@@GEN@@
@@WRITE@@
int main(int argc, char** argv) {
    std::string w = argv[1];
    std::wstring W(w.begin(), w.end());
    std::wstring tmp = W + L"/x.y/run.Ab12/ascQ";              /* converter temp folder: dots in the path */
    std::wstring bin = tmp + L"/bin_XYZ";                       /* CreateTempFileWithUniqueName(tempPath, "bin") */
    std::wstring dst = W + L"/out/ppt/embeddings/";
    CMediaManager m; m.m_strTempMedia = OOX::CPath(tmp).GetPath(); m.m_strDstEmbeddings = dst;  /* as SetTempMedia */
    CRelsGenerator r; r.m_pManager = &m;
    std::wstring rid = r.WriteOleObject(bin);
    std::ifstream f(N(dst + L"oleObject1.bin"), std::ios::binary); std::string got((std::istreambuf_iterator<char>(f)), {});
    printf("RELS1=%s\nCOPIED=%s\n", N(r.m_sRels).c_str(), got == "OLE2" ? "yes" : "no");
    CMediaManager m2 = m; m2.m_bFail = true; m2.m_mapMedia.clear();
    CRelsGenerator r2; r2.m_pManager = &m2;
    std::wstring rid2 = r2.WriteOleObject(bin);
    printf("RELS2=%s RID2=%s\n", N(r2.m_sRels).c_str(), N(rid2).c_str());
    return 0;
}
'''


def main():
    src = read(REL)
    ext = block(src, 'static int FileExtIndex(', required=False)
    gen = block(src, 'std::wstring CMediaManager::GenerateEmbedding(')
    write = block(src, 'std::wstring  CRelsGenerator::WriteOleObject(')
    work = tempfile.mkdtemp(prefix='rd0070-')
    os.makedirs(os.path.join(work, 'x.y', 'run.Ab12', 'ascQ'))
    os.makedirs(os.path.join(work, 'out', 'ppt'))
    open(os.path.join(work, 'x.y', 'run.Ab12', 'ascQ', 'bin_XYZ'), 'w').write('OLE2')
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write(DRIVER.replace('@@EXT@@', ext).replace('@@GEN@@', gen).replace('@@WRITE@@', write))
    exe = os.path.join(work, 'drv')
    r = subprocess.run(['c++', '-std=gnu++11', '-w', p, '-o', exe], capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-3000:])
    r = subprocess.run([exe, work], capture_output=True, text=True)
    out = r.stdout + r.stderr
    rels1 = (re.search(r'RELS1=(.*)', out) or [None, ''])[1]
    rels2 = (re.search(r'RELS2=(.*) RID2=', out) or [None, ''])[1]
    who = 'baseline ' + BASE_REF if BASELINE else 'working tree'
    ok1 = 'Target="../embeddings/oleObject1.bin"' in rels1 and 'External' not in rels1 and 'COPIED=yes' in out
    ok2 = rels2 == '' and r.returncode == 0
    print(('ok   ' if ok1 else 'FAIL ') + 'OLE temp file under a dotted temp folder is embedded (%s): %s' % (who, rels1 or out.strip()[-300:]))
    print(('ok   ' if ok2 else 'FAIL ') + 'failed embedding writes no external link to the temp file (%s): %s' % (who, rels2 or 'no rel'))
    sys.exit(0 if ok1 and ok2 else 1)


if __name__ == '__main__':
    main()
