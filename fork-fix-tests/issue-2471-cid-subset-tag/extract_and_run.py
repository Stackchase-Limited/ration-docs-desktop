#!/usr/bin/env python3
r"""
#2471 - "PDF export from OnlyOffice causes garbled text display in Microsoft OneNote".

Every font we embed is a CIDFontType2 subset, Identity-H, whose codes (CIDs) are
handed out per document in order of first use: CID 1 is whatever character the
document draws first.  The subset tag in front of the name came from a counter,

    PdfFile/SrcWriter/Document.cpp   CDocument::GetTTFontTag   -> "BAAAAA+", "CAAAAA+", ...

so the first subset of EVERY PDF we write is "BAAAAA+<family>", whatever glyphs
it holds, and the editor (CDocument::EditPdf) restarts the counter at BAAAAA
next to subsets an earlier save already called BAAAAA - two different subsets
with one tag in one file, which ISO 32000-1 9.6.4 forbids.  Two of our exports
with different text, run through the real x2t, both carry "BAAAAA+Open Sans";
CIDs 1-6 mean "Arial:" in both, CID 7 is 'T' in one and 'L' in the other.

That is exactly the reporter's OneNote screenshot: OneNote renders several
printouts and caches embedded fonts by name, so a second printout is drawn
through the first one's code -> glyph map - the opening words (same first-use
order) come out right and the rest turns into wrong-but-real letters of the
right typeface.  Ghostscript without subsetting "fixes" it because full fonts
with CID = GID mean the same thing in every file.

The fix (FontCidTT.cpp, CFontCidTrueType::BeforeWrite) replaces the counter
tag, once the subset is known, with one hashed from the name and the code->GID
map: equal subsets keep equal names, different subsets get different names,
in the same file or across files.

This test extracts the REAL CDocument::GetTTFontTag, the REAL GetSubsetTag
helper and the REAL renaming block of BeforeWrite (by brace matching) and runs
them against stub dictionaries, as two documents with different text would.

  RD_REPO=<core checkout>   default ../../core relative to this file
  BASELINE=1                read sources via `git show $BASE_REF:<path>`; must FAIL

NOT claimed: that OneNote now renders correctly (no Windows/OneNote here); that
the font name tables inside the subsets (which still say e.g. "Carlito") play
no part in OneNote's cache.  The FontDescriptor metrics (FontBBox/Ascent/Descent/
CapHeight written in font units, not 1/1000 em) are a separate, untouched issue.
"""
import os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '2a38ea99f3^')


def read(rel):
    if os.environ.get('BASELINE'):
        return subprocess.run(['git', '-C', CORE, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, text=True, check=True).stdout
    return open(os.path.join(CORE, rel), encoding='utf-8').read()


def block(text, start):
    """text[start:] up to and including the brace that closes the first '{'."""
    depth, i = 0, text.index('{', start)
    for j in range(i, len(text)):
        if text[j] == '{':
            depth += 1
        elif text[j] == '}':
            depth -= 1
            if depth == 0:
                return text[start:j + 1]
    raise SystemExit('unbalanced braces')


doc = read('PdfFile/SrcWriter/Document.cpp')
cid = read('PdfFile/SrcWriter/FontCidTT.cpp')

m = re.search(r'char\* CDocument::GetTTFontTag\(\)', doc)
if not m:
    raise SystemExit('FAIL: CDocument::GetTTFontTag not found')
get_tag = block(doc, m.start()).replace('CDocument::', 'Document::')

m = re.search(r'static std::string GetSubsetTag\(', cid)
subset_tag = block(cid, m.start()) if m else ''

bw = re.search(r'void CFontCidTrueType::BeforeWrite\(\)', cid)
if not bw:
    raise SystemExit('FAIL: CFontCidTrueType::BeforeWrite not found')
bw_body = block(cid, bw.start())
m = re.search(r'CObjectBase\* pBaseFont = Get\("BaseFont"\);\s*', bw_body)
if m:
    retag = m.group(0) + block(bw_body, m.end())
else:
    retag = '/* BeforeWrite does not rename the subset */'
print('GetSubsetTag found: %s, renaming block in BeforeWrite found: %s' % (bool(subset_tag), bool(m)))

prog = r'''
#include <cstdio>
#include <cstring>
#include <map>
#include <string>
typedef unsigned char BYTE;
static void MemCpy(BYTE* d, const BYTE* s, unsigned int n) { memcpy(d, s, n); }
enum { object_type_NAME = 0x06 };
struct CObjectBase { std::string s; int GetType() const { return object_type_NAME; } };
struct CNameObject : CObjectBase { const char* Get() const { return s.c_str(); } };
struct Dict {
  std::map<std::string, CNameObject> m;
  CObjectBase* Get(const std::string& k) { return m.count(k) ? &m[k] : NULL; }
  void Add(const std::string& k, const char* v) { m[k].s = v; }
};
struct FontFile { std::string name; void SetName(const std::string& s) { name = s; } };
struct Document {
  char m_sTTFontTag[8];
  Document() { memset((void*)m_sTTFontTag, 0x00, 8); }
  char* GetTTFontTag();
};
char* Document::GET_TAG_BODY
SUBSET_TAG
struct Font : Dict {
  Dict desc, cidfont, *m_pFont, *m_pFontDescriptor; FontFile file, *m_pFontFile;
  int m_nGlyphsCount; unsigned short m_ushCodesCount;
  // what OpenFontFace does: counter tag + family into all three places
  Font(Document& d, const char* family, int nGlyphs) : m_pFont(&cidfont), m_pFontDescriptor(&desc), m_pFontFile(&file), m_nGlyphsCount(nGlyphs), m_ushCodesCount(0) {
    std::string n = d.GetTTFontTag(); n += family;
    Add("BaseFont", n.c_str()); m_pFont->Add("BaseFont", n.c_str()); m_pFontDescriptor->Add("FontName", n.c_str()); m_pFontFile->SetName(n);
  }
  std::string Write(const unsigned short* pCodeToGid, unsigned short n) {
    m_ushCodesCount = n;
    RETAG
    return Get("BaseFont")->s;
  }
  bool Consistent() { std::string b = Get("BaseFont")->s;
    return b == m_pFont->Get("BaseFont")->s && b == m_pFontDescriptor->Get("FontName")->s && b == m_pFontFile->name; }
};
static bool WellFormed(const std::string& s) {
  if (s.size() < 8 || s[6] != '+') return false;
  for (int i = 0; i < 6; ++i) if (s[i] < 'A' || s[i] > 'Z') return false;
  return true;
}
int main() {
  // code->GID maps of two texts that start alike ("Arial: ...") and then diverge, CIDs in order of first use
  const unsigned short a[] = {0, 36, 85, 76, 68, 79, 29, 55, 75, 72, 84, 88, 70, 78};
  const unsigned short b[] = {0, 36, 85, 76, 68, 79, 29, 47, 72, 86, 54, 17, 21, 75};
  int bad = 0;
  Document d1, d2, d3;
  Font f1(d1, "Open Sans", 938), f2(d2, "Open Sans", 938), f3(d3, "Open Sans", 938);
  std::string n1 = f1.Write(a, 14), n2 = f2.Write(b, 14), n3 = f3.Write(a, 14);
  printf("document 1 (text A): %s\n", n1.c_str());
  printf("document 2 (text B): %s\n", n2.c_str());
  printf("document 3 (text A): %s\n", n3.c_str());
  if (n1 == n2) { printf("BAD: different subsets in two documents share the name %s\n", n1.c_str()); ++bad; }
  if (n1 != n3) { printf("BAD: the same subset is named differently in two runs\n"); ++bad; }
  // one document, two subsets of the same family with the same codes (e.g. a font registered twice)
  Document d4; Font g1(d4, "Open Sans", 938), g2(d4, "Open Sans", 938);
  std::string m1 = g1.Write(a, 14), m2 = g2.Write(a, 14);
  printf("one document, two subsets: %s / %s\n", m1.c_str(), m2.c_str());
  if (m1 == m2) { printf("BAD: two subsets in one file share a tag\n"); ++bad; }
  Font* all[] = {&f1, &f2, &f3, &g1, &g2};
  for (Font* f : all) if (!f->Consistent() || !WellFormed(f->Get("BaseFont")->s)) { printf("BAD: inconsistent or malformed name %s\n", f->Get("BaseFont")->s.c_str()); ++bad; }
  return bad ? 1 : 0;
}
'''
prog = (prog.replace('GET_TAG_BODY', get_tag[len('char* Document::'):])
            .replace('SUBSET_TAG', subset_tag).replace('RETAG', retag))

with tempfile.TemporaryDirectory() as t:
    c, exe = os.path.join(t, 't.cpp'), os.path.join(t, 't')
    open(c, 'w').write(prog)
    r = subprocess.run(['c++', '-std=c++11', '-w', c, '-o', exe], capture_output=True, text=True)
    if r.returncode:
        print(r.stderr[-3000:]); print('FAIL: does not build'); sys.exit(1)
    r = subprocess.run([exe], capture_output=True, text=True)
    print(r.stdout, end='')
    print('PASS' if r.returncode == 0 else 'FAIL'); sys.exit(r.returncode)
