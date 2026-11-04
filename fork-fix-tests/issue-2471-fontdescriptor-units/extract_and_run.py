#!/usr/bin/env python3
r"""
#2471 (follow-up) - FontDescriptor metrics of embedded TrueType subsets were written
in font units instead of glyph space.

ISO 32000-1 9.8: FontBBox, Ascent, Descent and CapHeight are in glyph space,
1/1000 em.  CFontFileTrueType (PdfFile/SrcWriter/FontTTWriter.cpp, Parse/ReadOS2)
read head.xMin..yMax and OS/2 sTypoAscender/sTypoDescender/sCapHeight raw, and
CFontCidTrueType::CreateCIDFont (FontCidTT.cpp) wrote them as they are.  Every
CID font we export said e.g. for Open Sans (unitsPerEm 2048)

    /Ascent 1567 /Descent -492 /CapHeight 1462 /FontBBox [-1196 -578 2583 2148]

instead of 765 / -240 / 713 / [-583 -282 1261 1048] - text twice as tall as it
is for any reader that uses the descriptor (search highlight / selection boxes,
font substitution, cross-document font caches).  CFontTrueType (FontTT.cpp, the
form-field font) already scaled with 1000 / units_per_EM.

Fix: CFontFileTrueType reads unitsPerEm from 'head' and stores the metrics in
glyph space (ToGlyphSpace), so CreateCIDFont writes correct values; FontTT.cpp no
longer scales CapHeight a second time.  The 1000 / -500 / 800 defaults (no OS/2)
were already glyph-space numbers and stay as they are.

This test extracts the REAL SeekTable, the 'head' part of Parse, ReadOS2,
ToGlyphSpace, the metric getters, the descriptor block of CreateCIDFont and the
CapHeight line of CFontTrueType, and runs them on synthetic 'head' + 'OS/2'
tables (Open Sans numbers, unitsPerEm 2048, and a 1000-unit font).

  RD_REPO=<core checkout>   default ../../core relative to this file
  BASELINE=1                read sources via `git show $BASE_REF:<path>`; must FAIL

Our own reader, checked with the real binaries when this was written (not part
of this test): RendererOutputDev uses descriptor metrics only to pick a system
font for NON-embedded fonts and in the font cache key (ComputeFontHash); xpdf's
GfxFont feeds them to TextOutputDev (link detection in CPdfReader::GetLinks) and
AcroForm (only with NeedAppearances); Splash/PS output devices are not built.
x2t pdf->png of two docx exports, old vs new writer, through old and new reader:
0 differing bytes; pdf->docx: identical package; incremental edit of an old and
of a new export: identical renders.  The one visible change: the hit box of an
auto-detected URL in our PDFs shrinks to the glyph height (24pt Open Sans:
h 29.80 -> 22.87pt), because xpdf no longer sees an ascent above 1 em.

NOT claimed: OpenType-CFF fonts with unitsPerEm != 1000 are covered by the same
code path but were not exported in a real run; PDFs written before the fix keep
their wrong numbers (nothing compensates for them, nothing needs to).
"""
import os, re, struct, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', 'bf09d8ce1c^')


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


def method(text, sig):
    m = re.search(sig, text)
    return block(text, m.start()).replace('CFontFileTrueType::', 'Stub::') if m else ''


ttw = read('PdfFile/SrcWriter/FontTTWriter.cpp')
cid = read('PdfFile/SrcWriter/FontCidTT.cpp')
ftt = read('PdfFile/SrcWriter/FontTT.cpp')

seek = method(ttw, r'int\s+CFontFileTrueType::SeekTable\(')
os2 = method(ttw, r'void\s+CFontFileTrueType::ReadOS2\(\)')
to_gs = method(ttw, r'int\s+CFontFileTrueType::ToGlyphSpace\(')
getters = ''.join(method(ttw, r'%s\s+CFontFileTrueType::%s\(\)' % (r, n))
                  for r, n in [(r'int', 'GetAscent'), (r'int', 'GetDescent'), (r'int', 'GetCapHeight'), (r'int\*', 'GetBBox')])
m = re.search(r'nIndex = SeekTable\("head"\);.*?m_nLocaFormat = [^\n]*\n', ttw, re.S)
head = m.group(0) if m else ''
cc = re.search(r'void CFontCidTrueType::CreateCIDFont\(CDictObject\* pFont\)', cid)
cc_body = block(cid, cc.start()) if cc else ''
m = re.search(r'if \(m_pFontFile\)\s*\{\s*CArrayObject\* pBBox.*?Add\("CapHeight"[^\n]*\n', cc_body, re.S)
desc = m.group(0) if m else ''
m = re.search(r'm_pFontDescriptor->Add\("CapHeight",[^\n]*\n', ftt)
tt_cap = m.group(0) if m else ''
for name, v in [('SeekTable', seek), ('ReadOS2', os2), ('getters', getters), ("Parse 'head'", head), ('CreateCIDFont descriptor', desc), ('FontTT CapHeight', tt_cap)]:
    if not v:
        raise SystemExit('FAIL: %s not found' % name)
print('ToGlyphSpace found: %s' % bool(to_gs))


def font_tables(upem, bbox, asc, desc_, cap, os2_version=4):
    h = bytearray(54)
    struct.pack_into('>H', h, 18, upem)
    struct.pack_into('>hhhh', h, 36, *bbox)
    o = bytearray(96)
    struct.pack_into('>H', o, 0, os2_version)
    struct.pack_into('>H', o, 4, 400)
    struct.pack_into('>hh', o, 68, asc, desc_)
    struct.pack_into('>h', o, 88, cap)
    return bytes(h), bytes(o)


def c_bytes(b):
    return '{' + ','.join(str(x) for x in b) + '}'


cases = [  # name, upem, bbox, ascender, descender, capheight, os2 version, expected descriptor
    ('Open Sans (2048)', 2048, (-1196, -578, 2583, 2148), 1567, -492, 1462, 4, ([-583, -282, 1261, 1048], 765, -240, 713)),
    ('Carlito (2048)', 2048, (-1002, -529, 2351, 2078), 1536, -512, 1314, 4, ([-489, -258, 1147, 1014], 750, -250, 641)),
    ('1000-unit font', 1000, (-100, -250, 900, 950), 800, -200, 700, 4, ([-100, -250, 900, 950], 800, -200, 700)),
    ('OS/2 v1 (no sCapHeight)', 2048, (-1196, -578, 2583, 2148), 1567, -492, 1462, 1, ([-583, -282, 1261, 1048], 765, -240, 800)),
]
main = []
for i, (name, upem, bbox, asc, dsc, cap, ver, exp) in enumerate(cases):
    h, o = font_tables(upem, bbox, asc, dsc, cap, ver)
    main.append('  { const unsigned char h[] = %s, o[] = %s; bad += Run("%s", %d, h, sizeof(h), o, sizeof(o), %d, %d, %d, %d, %d, %d, %d); }'
                % (c_bytes(h), c_bytes(o), name, upem, exp[0][0], exp[0][1], exp[0][2], exp[0][3], exp[1], exp[2], exp[3]))

prog = r'''
#include <cstdio>
#include <map>
#include <string>
#include <vector>
struct TrueTypeTable { unsigned int unTag; unsigned int unChecksum; int nOffset; int nOrigOffset; int nLen; };
struct Stub {
  std::vector<unsigned char> d; TrueTypeTable m_pTables[2]; int m_nTablesCount = 2; bool m_bSuccess = true;
  int m_arrBBox[4]; int m_nLocaFormat = 0; unsigned int m_unUnitsPerEm = 0;
  int m_nAscent = 1000, m_nDescent = -500, m_nCapHeight = 800, m_nWeight = 400; // as in the constructor
  int GetU16BE(int p, bool* ok) { if (p < 0 || p + 2 > (int)d.size()) { *ok = false; return 0; } return (d[p] << 8) | d[p + 1]; }
  int GetS16BE(int p, bool* ok) { int v = GetU16BE(p, ok); return v & 0x8000 ? v - 0x10000 : v; }
  int SeekTable(const char* sTag); void ReadOS2(); int ToGlyphSpace(int nValue);
  int GetAscent(); int GetDescent(); int GetCapHeight(); int* GetBBox();
  void Head() { int nIndex;
    @@HEAD@@
  }
};
@@SEEK@@
@@OS2@@
@@TO_GS@@
@@GETTERS@@
struct CArrayObject { std::vector<int> v; void Add(int x) { v.push_back(x); } };
struct Desc { std::map<std::string, int> n; CArrayObject* bbox = NULL;
  void Add(const char* k, int x) { n[k] = x; } void Add(const char* k, CArrayObject* a) { bbox = a; } };
struct Cid { Stub* m_pFontFile; Desc d, *pFontDescriptor = &d; void Write() {
  @@DESC@@
} };
struct TT { Stub* m_pFontFile; Desc d, *m_pFontDescriptor = &d; void Write(unsigned int unUnitsPerEm) { double dKoef = 1000.0 / unUnitsPerEm;
  @@TT_CAP@@
} };
static unsigned int Tag(const char* s) { return ((s[0] & 0xff) << 24) | ((s[1] & 0xff) << 16) | ((s[2] & 0xff) << 8) | (s[3] & 0xff); }
static int Run(const char* name, unsigned int upem, const unsigned char* h, int hl, const unsigned char* o, int ol,
               int b0, int b1, int b2, int b3, int asc, int dsc, int cap) {
  Stub f; f.d.assign(h, h + hl); f.d.insert(f.d.end(), o, o + ol);
  f.m_pTables[0] = {Tag("head"), 0, 0, 0, hl}; f.m_pTables[1] = {Tag("OS/2"), 0, hl, hl, ol};
  f.Head(); f.ReadOS2();
  Cid c; c.m_pFontFile = &f; c.Write();
  TT t; t.m_pFontFile = &f; t.Write(upem);
  std::vector<int>& b = c.d.bbox->v;
  printf("%-24s CID descriptor: FontBBox [%d %d %d %d] Ascent %d Descent %d CapHeight %d; TrueType (form) CapHeight %d\n",
         name, b[0], b[1], b[2], b[3], c.d.n["Ascent"], c.d.n["Descent"], c.d.n["CapHeight"], t.d.n["CapHeight"]);
  int bad = 0;
  if (b[0] != b0 || b[1] != b1 || b[2] != b2 || b[3] != b3 || c.d.n["Ascent"] != asc || c.d.n["Descent"] != dsc || c.d.n["CapHeight"] != cap) {
    printf("BAD: expected FontBBox [%d %d %d %d] Ascent %d Descent %d CapHeight %d (1/1000 em)\n", b0, b1, b2, b3, asc, dsc, cap); ++bad; }
  if (t.d.n["CapHeight"] != cap) { printf("BAD: CFontTrueType CapHeight expected %d\n", cap); ++bad; }
  return bad;
}
int main() {
  int bad = 0;
@@MAIN@@
  return bad ? 1 : 0;
}
'''
for k, v in [('HEAD', head), ('SEEK', seek), ('OS2', os2), ('TO_GS', to_gs), ('GETTERS', getters),
             ('DESC', desc), ('TT_CAP', tt_cap), ('MAIN', '\n'.join(main))]:
    prog = prog.replace('@@%s@@' % k, v)

with tempfile.TemporaryDirectory() as t:
    c, exe = os.path.join(t, 't.cpp'), os.path.join(t, 't')
    open(c, 'w').write(prog)
    r = subprocess.run(['c++', '-std=c++11', '-w', c, '-o', exe], capture_output=True, text=True)
    if r.returncode:
        print(r.stderr[-3000:]); print('FAIL: does not build'); sys.exit(1)
    r = subprocess.run([exe], capture_output=True, text=True)
    print(r.stdout, end='')
    print('PASS' if r.returncode == 0 else 'FAIL'); sys.exit(r.returncode)
