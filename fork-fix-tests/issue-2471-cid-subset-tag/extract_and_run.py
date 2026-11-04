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

Fix, part 1 (FontCidTT.cpp, CFontCidTrueType::BeforeWrite): once the subset is
known, the counter tag is replaced by one hashed from the name and the
code->GID map, so different subsets get different names across files.

Fix, part 2 (uniqueness inside one file is a guarantee, not a probability):
CDocument keeps the set of tags used in the document (CDocument::AddSubsetTag).
When an existing PDF is opened for editing, CPdfEditor::AddSubsetTags seeds it
with the FontName / BaseFont tags of every object already in the file
(IncrementalUpdates after EditPdf, WriteNew, Split/Merge, Print), and
BeforeWrite rehashes with a salt until the tag is unused.  The 2a38ea99f3 hash
alone gave an edited file a second "MKIUOE+Open Sans" next to the one an earlier
save wrote (same text, same face, the counter restarted), and nothing stopped a
new subset from taking the tag of an unrelated subset already in the file.

This test extracts the REAL CDocument::GetTTFontTag, CDocument::AddSubsetTag,
the GetSubsetTag helper, the renaming block of BeforeWrite and
CPdfEditor::AddSubsetTags (by brace matching) and runs them against stub
dictionaries and a stub xpdf XRef, as two documents with different text, one
document with two equal subsets, a forced collision and an edited PDF would.

  RD_REPO=<core checkout>   default ../../core relative to this file
  BASELINE=1                read sources via `git show $BASE_REF:<path>`; must FAIL

Real-binary check done when this was written (driver linking the worktree
PdfFile framework, not part of this test): a PDF exported with "Hello" in Open
Sans, edited (incremental and WriteNew) to add "Hello" in Open Sans, had two
font objects both tagged MKIUOE before, MKIUOE + JLJZHB after; a PDF whose
Carlito subset was renamed to MKIUOE got "MKIUOE+Open Sans" next to
"MKIUOE+Carlito" before, JLJZHB after.  Plain exports keep their tags.

NOT claimed: that OneNote now renders correctly (no Windows/OneNote here); that
the font name tables inside the subsets play no part in OneNote's cache; that
fonts reachable only as direct (non-indirect) objects in a malformed file are
seen by the seeding (a FontDescriptor must be indirect).
"""
import os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '8aca22e449^')


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


def method(text, signature, cls_from, cls_to):
    m = re.search(signature, text)
    return block(text, m.start()).replace(cls_from, cls_to) if m else ''


doc = read('PdfFile/SrcWriter/Document.cpp')
cid = read('PdfFile/SrcWriter/FontCidTT.cpp')
edt = read('PdfFile/PdfEditor.cpp')

get_tag = method(doc, r'char\* CDocument::GetTTFontTag\(\)', 'CDocument::', 'Document::')
if not get_tag:
    raise SystemExit('FAIL: CDocument::GetTTFontTag not found')
add_tag = method(doc, r'bool CDocument::AddSubsetTag\(', 'CDocument::', 'Document::')
seed = method(edt, r'void CPdfEditor::AddSubsetTags\(', 'CPdfEditor::', 'Editor::')

m = re.search(r'static std::string GetSubsetTag\(', cid)
subset_tag = block(cid, m.start()) if m else ''

bw = re.search(r'void CFontCidTrueType::BeforeWrite\(\)', cid)
if not bw:
    raise SystemExit('FAIL: CFontCidTrueType::BeforeWrite not found')
bw_body = block(cid, bw.start())
m = re.search(r'CObjectBase\* pBaseFont = Get\("BaseFont"\);\s*', bw_body)
retag = m.group(0) + block(bw_body, m.end()) if m else '/* BeforeWrite does not rename the subset */'

# where the editor seeds the set: after EditPdf in IncrementalUpdates, and on the other paths that copy objects
def body_of(sig):
    mm = re.search(sig, edt)
    return block(edt, mm.start()) if mm else ''
inc = body_of(r'bool CPdfEditor::IncrementalUpdates\(\)')
seeded_after_editpdf = bool(re.search(r'pDoc->EditPdf\(.*?AddSubsetTags\(pPDFDocument\)', inc, re.S))
seeded_paths = {
    'SetMode(WriteNew)': 'AddSubsetTags(' in body_of(r'void CPdfEditor::SetMode\('),
    'SplitPages(doc)': 'AddSubsetTags(' in body_of(r'bool CPdfEditor::SplitPages\(const int\* arrPageIndex, unsigned int unLength, PDFDoc\*'),
    'PrintPages': 'AddSubsetTags(' in body_of(r'bool CPdfEditor::PrintPages\('),
}
print('GetSubsetTag: %s, renaming block: %s, CDocument::AddSubsetTag: %s, CPdfEditor::AddSubsetTags: %s'
      % (bool(subset_tag), bool(m), bool(add_tag), bool(seed)))
print('seeded after EditPdf in IncrementalUpdates: %s, %s' % (seeded_after_editpdf, seeded_paths))

prog = r'''
#include <cstdio>
#include <cstring>
#include <map>
#include <set>
#include <string>
#include <vector>
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
  std::set<std::string> m_setSubsetTags;
  Document() { memset((void*)m_sTTFontTag, 0x00, 8); }
  char* GetTTFontTag();
  bool AddSubsetTag(const std::string& sFontName);
};
char* Document::GET_TAG_BODY
ADD_TAG
SUBSET_TAG
// --- xpdf stubs for CPdfEditor::AddSubsetTags
enum XRefEntryType { xrefEntryFree, xrefEntryUncompressed, xrefEntryCompressed };
struct XRefEntry { long long offset; int gen; XRefEntryType type; };
struct Object {
  int t = 0; std::string name; std::map<std::string, Object> d; // t: 0 null, 1 name, 2 dict, 3 stream
  bool isDict() const { return t == 2; } bool isName() const { return t == 1; }
  char* getName() { return (char*)name.c_str(); }
  Object* dictLookupNF(const char* k, Object* o) { *o = d.count(k) ? d[k] : Object(); return o; }
  void free() {}
};
static Object Name(const char* s) { Object o; o.t = 1; o.name = s; return o; }
struct XRef {
  std::vector<XRefEntry> e; std::vector<Object> o;
  int getNumObjects() { return (int)e.size(); } int getSize() { return (int)e.size(); }
  XRefEntry* getEntry(int i) { return &e[i]; }
  Object* fetch(int n, int, Object* r) { *r = e[n].type == xrefEntryFree ? Object() : o[n]; return r; }
  void add(XRefEntryType t, const Object& ob) { e.push_back({0, 0, t}); o.push_back(ob); }
};
struct PDFDoc { XRef x; XRef* getXRef() { return &x; } };
namespace PdfWriter { typedef ::Document CDocument; }
struct Writer { Document* d; Document* GetDocument() { return d; } };
struct Editor { Writer* m_pWriter; void AddSubsetTags(PDFDoc* pPDFDocument); };
SEED
struct Font : Dict {
  Dict desc, cidfont, *m_pFont, *m_pFontDescriptor; FontFile file, *m_pFontFile; Document* m_pDocument;
  int m_nGlyphsCount; unsigned short m_ushCodesCount;
  // what OpenFontFace does: counter tag + family into all three places
  Font(Document& d, const char* family, int nGlyphs) : m_pFont(&cidfont), m_pFontDescriptor(&desc), m_pFontFile(&file), m_pDocument(&d), m_nGlyphsCount(nGlyphs), m_ushCodesCount(0) {
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
  std::vector<Font*> all;
  Document d1, d2, d3;
  Font f1(d1, "Open Sans", 938), f2(d2, "Open Sans", 938), f3(d3, "Open Sans", 938);
  std::string n1 = f1.Write(a, 14), n2 = f2.Write(b, 14), n3 = f3.Write(a, 14);
  all.push_back(&f1); all.push_back(&f2); all.push_back(&f3);
  printf("document 1 (text A): %s\n", n1.c_str());
  printf("document 2 (text B): %s\n", n2.c_str());
  printf("document 3 (text A): %s\n", n3.c_str());
  if (n1 == n2) { printf("BAD: different subsets in two documents share the name %s\n", n1.c_str()); ++bad; }
  if (n1 != n3) { printf("BAD: the same subset is named differently in two documents\n"); ++bad; }

  // one document, two subsets of the same family with the same codes (e.g. a font registered twice)
  Document d4; Font g1(d4, "Open Sans", 938), g2(d4, "Open Sans", 938);
  std::string m1 = g1.Write(a, 14), m2 = g2.Write(a, 14);
  all.push_back(&g1); all.push_back(&g2);
  printf("one document, two subsets: %s / %s\n", m1.c_str(), m2.c_str());
  if (m1.substr(0, 6) == m2.substr(0, 6)) { printf("BAD: two subsets in one file share a tag\n"); ++bad; }

  // forced collision: the tag the hash picks for text B is already used in the document (by another family)
  Document d5; std::string taken = n2.substr(0, 7) + "Carlito";
  d5.AddSubsetTag(taken);
  Font h1(d5, "Open Sans", 938); std::string k1 = h1.Write(b, 14); all.push_back(&h1);
  Document d6; d6.AddSubsetTag(taken);
  Font h2(d6, "Open Sans", 938); std::string k2 = h2.Write(b, 14); all.push_back(&h2);
  printf("forced collision with %s: %s (again: %s)\n", taken.c_str(), k1.c_str(), k2.c_str());
  if (k1.substr(0, 6) == taken.substr(0, 6)) { printf("BAD: the new subset took a tag already used in the document\n"); ++bad; }
  if (k1 != k2) { printf("BAD: collision resolution is not deterministic\n"); ++bad; }

  // edited PDF: the file already holds a subset with the tag an earlier save gave text A (same face, same codes),
  // an unrelated subset, a standard font, a free entry and a font file stream
  PDFDoc pdf;
  { Object fd; fd.t = 2; fd.d["Type"] = Name("FontDescriptor"); fd.d["FontName"] = Name(n1.c_str()); pdf.x.add(xrefEntryUncompressed, fd); }
  { Object f;  f.t = 2;  f.d["Type"] = Name("Font"); f.d["BaseFont"] = Name(n1.c_str()); pdf.x.add(xrefEntryCompressed, f); }
  pdf.x.add(xrefEntryFree, Object());
  { Object f;  f.t = 2;  f.d["Type"] = Name("Font"); f.d["BaseFont"] = Name("Helvetica"); pdf.x.add(xrefEntryUncompressed, f); }
  { Object fd; fd.t = 2; fd.d["FontName"] = Name("QWERTY+Carlito"); pdf.x.add(xrefEntryCompressed, fd); }
  { Object s;  s.t = 3; pdf.x.add(xrefEntryUncompressed, s); }
  Document d7; Writer w = {&d7}; Editor ed = {&w};
  ed.AddSubsetTags(&pdf);
  Font e1(d7, "Open Sans", 938); std::string x1 = e1.Write(a, 14); all.push_back(&e1);
  Font e2(d7, "Open Sans", 938); std::string x2 = e2.Write(b, 14); all.push_back(&e2);
  printf("edited PDF holding %s and QWERTY+Carlito, new subsets: %s, %s\n", n1.c_str(), x1.c_str(), x2.c_str());
  if (x1.substr(0, 6) == n1.substr(0, 6) || x2.substr(0, 6) == n1.substr(0, 6) || x1.substr(0, 6) == "QWERTY" || x2.substr(0, 6) == "QWERTY") {
    printf("BAD: a subset written into the edited PDF repeats a tag already in the file\n"); ++bad; }
  if (d7.AddSubsetTag("QWERTY+X") || d7.AddSubsetTag("Helvetica")) { printf("BAD: seeding read the wrong names\n"); ++bad; }

  for (Font* f : all) if (!f->Consistent() || !WellFormed(f->Get("BaseFont")->s)) { printf("BAD: inconsistent or malformed name %s\n", f->Get("BaseFont")->s.c_str()); ++bad; }
  return bad ? 1 : 0;
}
'''
prog = (prog.replace('GET_TAG_BODY', get_tag[len('char* Document::'):])
            .replace('ADD_TAG', add_tag or 'bool Document::AddSubsetTag(const std::string&) { return true; } // not in this source')
            .replace('SEED', seed or 'void Editor::AddSubsetTags(PDFDoc*) {} // not in this source')
            .replace('SUBSET_TAG', subset_tag).replace('RETAG', retag))

with tempfile.TemporaryDirectory() as t:
    c, exe = os.path.join(t, 't.cpp'), os.path.join(t, 't')
    open(c, 'w').write(prog)
    r = subprocess.run(['c++', '-std=c++11', '-w', c, '-o', exe], capture_output=True, text=True)
    if r.returncode:
        print(r.stderr[-3000:]); print('FAIL: does not build'); sys.exit(1)
    r = subprocess.run([exe], capture_output=True, text=True)
    print(r.stdout, end='')
    ok = r.returncode == 0 and seeded_after_editpdf and all(seeded_paths.values())
    if r.returncode == 0 and not ok:
        print('BAD: the editor does not seed the subset tags on every path that writes next to existing objects')
    print('PASS' if ok else 'FAIL'); sys.exit(0 if ok else 1)
