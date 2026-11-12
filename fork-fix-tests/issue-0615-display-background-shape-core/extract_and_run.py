#!/usr/bin/env python3
"""
#615 (part 1), core side - docx w:background without w:displayBackgroundShape.

Bug: the reporter's file has <w:background w:color="00B8FF"/> and no
<w:displayBackgroundShape/> in settings.xml. Word shows a white page
(ECMA-376 17.15.1.25: without the flag the background is not displayed).
The binary passed to the editor had no room for the flag, so the editor
always painted the background, and Binary_DocumentTableReader::Read_Background
(BinaryReaderD.cpp) called m_oDisplayBackgroundShape.Init() for every
background on save: the saved file then showed blue in Word as well (data
changed by a plain open/save).

Fix: BinaryDocumentTableWriter::WriteBackground (BinaryWriterD.cpp) adds a
DisplayShape item (c_oSerBackgroundType 100, Byte: 0 absent, 1 on, 2 off) from
settings.xml; the reader restores the flag from that byte (absent stays absent,
w:val="0" stays off) and, for a binary without the item (older editor), still
turns it on as before.

What runs: the REAL WriteBackground, Read_Background, the Background item
branch of the document-table reader, the READ2_DEF macro, the Background class
and its constructor, and the c_oSerBackgroundType / c_oSerPropLenType enums are
cut out of core by brace matching and compiled with clang++ next to minimal
stand-ins (byte stream, settings with a nullable COnOff2, colour writer).
Checks: writer output per settings state; reader -> settings per byte; legacy
binary without the item; docx settings -> bin -> settings round trip for
absent / on / off.

NOT claimed: the full x2t is not built here (it was: docx -> bin -> docx with
x2t built from the fix keeps both <w:background w:color="00B8FF"/> and the
absent flag; the payload x2t adds <w:displayBackgroundShape w:val="true"/>).
The editor side is issue-0615-display-background-shape-test.js.

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read the sources at BASE_REF; must FAIL
  BASE_REF                  default: parent of the #615 core commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '4dc21d337a^')
BASELINE = bool(os.environ.get('BASELINE'))
D = 'OOXML/Binary/Document/'


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig').read()


def block(text, start):
    i = text.index('{', start)
    depth = 0
    for j in range(i, len(text)):
        if text[j] == '{':
            depth += 1
        elif text[j] == '}':
            depth -= 1
            if depth == 0:
                return text[start:j + 1]
    raise ValueError('unbalanced')


def find(text, pattern):
    m = re.search(pattern, text)
    if not m:
        sys.exit('FAIL: pattern not found in source: %s' % pattern)
    return m.start()


defines = read(D + 'BinWriter/BinReaderWriterDefines.h')
writer = read(D + 'BinWriter/BinaryWriterD.cpp')
reader = read(D + 'BinReader/BinaryReaderD.cpp')
rclasses_h = read(D + 'BinReader/ReaderClasses.h')
rclasses_cpp = read(D + 'BinReader/ReaderClasses.cpp')

enums = ''
for name in ('c_oSerPropLenType', 'c_oSerBackgroundType', 'c_oSerDisplayBackgroundShape'):
    m = re.search(r'namespace %s\s*\{' % name, defines)
    if m:  # c_oSerDisplayBackgroundShape exists only with the fix
        body = block(defines, m.end() - 1)          # "{enum ... {...};}" through the namespace's close
        enums += 'namespace %s%s\n' % (name, body)

write_bg = block(writer, find(writer, r'void BinaryDocumentTableWriter::WriteBackground\s*\('))
read_bg = block(reader, find(reader, r'int Binary_DocumentTableReader::Read_Background\s*\('))
item_at = find(reader, r'else if\s*\(\s*c_oSerParType::Background == type\s*\)')
item = block(reader, item_at)
item = item[item.index('{'):]
m = re.search(r'#define READ2_DEF\(.*?\n(?:.*\\\n)*.*\n', reader)
read2 = m.group(0)
bg_class = block(rclasses_h, find(rclasses_h, r'class Background\s*\n'))
ctor = re.search(r'Background::Background\(\)[^{]*\{\s*\}', rclasses_cpp).group(0)

HARNESS = r'''
#include <cstdio>
#include <string>
#include <vector>
typedef unsigned char BYTE;
namespace SimpleTypes {
	enum EOnOff { onoffFalse = 0, onoffTrue = 1 };
	class COnOff { public: EOnOff v = onoffTrue; COnOff() {} COnOff(EOnOff e) : v(e) {}
		bool ToBool() const { return v == onoffTrue; } void FromBool(bool b) { v = b ? onoffTrue : onoffFalse; } };
	struct CHexColor { BYTE r, g, b; };
}
template<class T> class nullable {
	T* p = nullptr;
public:
	~nullable() { delete p; }
	bool IsInit() const { return p != nullptr; }
	void Init() { if (!p) p = new T(); }
	void reset() { delete p; p = nullptr; }
	T* operator->() { return p; }
	const T* operator->() const { return p; }
	T& get() { return *p; }
	T* GetPointer() { return p; }
};
namespace ComplexTypes { namespace Word { struct COnOff2 { SimpleTypes::COnOff m_oVal = SimpleTypes::onoffTrue; }; } }
struct CSettings { nullable<ComplexTypes::Word::COnOff2> m_oDisplayBackgroundShape; };
namespace OOX {
	struct WritingElement { virtual ~WritingElement() {} };
	struct CXml { std::wstring toXML() const { return L""; } };
	namespace Logic {
		struct CBackground : WritingElement { nullable<CXml> m_oBackground; nullable<SimpleTypes::CHexColor> m_oColor; nullable<int> m_oThemeColor, m_oThemeTint, m_oThemeShade; };
		struct CBgPict : WritingElement { nullable<CXml> m_oBackground; nullable<SimpleTypes::CHexColor> m_oColor; };
	}
}
#define XMLWRITER_DOC_TYPE_DOCX 1
#define XMLWRITER_DOC_TYPE_DOCX_GLOSSARY 2
namespace BinDocxRW {
namespace c_oSerConstants { enum { ErrorFormat = -2, ErrorUnknown = -1, ReadOk = 0, ReadUnknown = 1, ErrorStream = 0x55 }; }
@ENUMS@
struct docRGB { BYTE R = 0, G = 0, B = 0; std::wstring ToString() { return L""; } };
struct CThemeColor { bool IsNoEmpty() { return false; } };
@BGCLASS@
@CTOR@
std::wstring Background::Write() { return L"<w:background/>"; }

struct OutStream { std::vector<BYTE> d; void WriteBYTE(BYTE b) { d.push_back(b); } };
struct BinaryCommonWriter {
	OutStream m_oStream;
	void WriteColor(BYTE type, const SimpleTypes::CHexColor& c) {
		m_oStream.WriteBYTE(type); m_oStream.WriteBYTE(c_oSerPropLenType::Three);
		m_oStream.WriteBYTE(c.r); m_oStream.WriteBYTE(c.g); m_oStream.WriteBYTE(c.b); }
	template<class... A> void WriteThemeColor(BYTE, A&...) {}
	int WriteItemWithLengthStart() { return 0; }
	void WriteItemEnd(int) {}
};
struct ParamsWriter { CSettings* m_pSettings = nullptr; };
class BinaryDocumentTableWriter {
public:
	ParamsWriter& m_oParamsWriter;
	BinaryCommonWriter m_oBcw;
	BinaryDocumentTableWriter(ParamsWriter& p) : m_oParamsWriter(p) {}
	void WriteDrawing(std::wstring*, void*, void*) {}
	void WriteBackground(OOX::WritingElement* pElement);
};
@WRITEBG@

struct InStream {
	std::vector<BYTE> d; size_t pos = 0;
	bool GetUCharWithResult(BYTE* b) { if (pos >= d.size()) return false; *b = d[pos++]; return true; }
	BYTE GetUChar() { return d[pos++]; }
	long GetLong() { long v = 0; for (int i = 0; i < 4; ++i) v |= (long)d[pos++] << (8 * i); return v; }
	BYTE* GetPointer(long n) { pos += n; return nullptr; }
	long GetPos() { return (long)pos; }
	void Seek(long p) { pos = p; }
};
struct CDrawingProperty { bool bDataPos = false, bDataLength = false; long DataPos = 0, DataLength = 0; CDrawingProperty(int) {} };
struct BinReaderStub { int m_nDocumentType = 0; };
struct DrawingConverter { BinReaderStub* m_pBinaryReader; std::wstring SaveObjectBackground(long, long) { return L""; } };
struct FileWriter { CSettings* m_pCurrentSettings = nullptr; DrawingConverter* m_pDrawingConverter = nullptr; bool m_bGlossaryMode = false; int getNextDocPr() { return 0; } };
struct CommonReader2 { InStream* s; docRGB ReadColor() { docRGB c; c.R = s->GetUChar(); c.G = s->GetUChar(); c.B = s->GetUChar(); return c; } void ReadThemeColor(long, CThemeColor&) {} };
struct StringWriter { std::wstring s; void WriteString(const std::wstring& x) { s += x; } };
struct DocumentWriter { StringWriter m_oBackground; };
@READ2@
class Binary_DocumentTableReader {
public:
	InStream m_oBufferedStream;
	FileWriter& m_oFileWriter;
	CommonReader2 oBinary_CommonReader2;
	DocumentWriter m_oDocumentWriter;
	Binary_DocumentTableReader(FileWriter& f) : m_oFileWriter(f) { oBinary_CommonReader2.s = &m_oBufferedStream; }
	int ReadPptxDrawing(BYTE, long, void*) { return c_oSerConstants::ReadUnknown; }
	int Read_Background(BYTE type, long length, void* poResult);
	int ReadBackgroundItem(long length) { int res = c_oSerConstants::ReadOk; @ITEM@ return res; }
};
@READBG@
}
using namespace BinDocxRW;

/* settings state: 0 absent, 1 on, 2 off (w:val="0") */
static int state(CSettings& s) { return !s.m_oDisplayBackgroundShape.IsInit() ? 0 : s.m_oDisplayBackgroundShape->m_oVal.ToBool() ? 1 : 2; }
static void set(CSettings& s, int st) { if (st) { s.m_oDisplayBackgroundShape.Init(); s.m_oDisplayBackgroundShape->m_oVal.FromBool(st == 1); } }
static const char* N[] = { "absent", "on", "w:val=0" };
static int fails = 0;
#define CHECK(c, ...) do { if (c) {} else { ++fails; printf("FAIL "); printf(__VA_ARGS__); printf("\n"); } } while (0)

static std::vector<BYTE> write(int st) {
	CSettings s; set(s, st);
	ParamsWriter p; p.m_pSettings = &s;
	BinaryDocumentTableWriter w(p);
	OOX::Logic::CBackground bg; bg.m_oColor.Init(); bg.m_oColor->r = 0x00; bg.m_oColor->g = 0xB8; bg.m_oColor->b = 0xFF;
	w.WriteBackground(&bg);
	return w.m_oBcw.m_oStream.d;
}
static int read(const std::vector<BYTE>& item) {
	CSettings s; FileWriter f; f.m_pCurrentSettings = &s;
	Binary_DocumentTableReader r(f); r.m_oBufferedStream.d = item;
	r.ReadBackgroundItem((long)item.size());
	CHECK(r.m_oBufferedStream.pos == item.size(), "reader did not consume the Background item");
	return state(s);
}
int main() {
	for (int st = 0; st < 3; ++st) {
		std::vector<BYTE> b = write(st);
		bool has = false;
		for (size_t i = 0; i + 2 < b.size(); i += (b[i + 1] == c_oSerPropLenType::Three ? 5 : 3))
			if (b[i] == 100 && b[i + 1] == c_oSerPropLenType::Byte) { has = true; CHECK(b[i + 2] == st, "settings %s written as byte %d", N[st], b[i + 2]); }
		CHECK(has, "settings %s: the Background item has no DisplayShape byte, the editor cannot know Word hides the page colour", N[st]);
		int back = read(b);
		CHECK(back == st, "docx settings %s -> bin -> docx settings %s", N[st], N[back]);
		if (has && back == st) printf("ok   %s survives docx -> bin -> docx\n", N[st]);
	}
	/* bin written by an editor that does not send the byte (older build, or this build before the fix) */
	std::vector<BYTE> legacy = { 0 /*Color*/, c_oSerPropLenType::Three, 0, 0xB8, 0xFF };
	int l = read(legacy);
	CHECK(l == 1, "binary without the byte: flag %s, expected on (old behaviour kept)", N[l]);
	if (l == 1) printf("ok   binary without the byte still turns the flag on\n");
	printf(fails ? "FAIL %d check(s)\n" : "PASS #615 display background flag (core)\n", fails);
	return fails ? 1 : 0;
}
'''

src = (HARNESS.replace('@ENUMS@', enums).replace('@BGCLASS@', bg_class + ';')
       .replace('@CTOR@', ctor).replace('@WRITEBG@', write_bg).replace('@READ2@', read2)
       .replace('@ITEM@', item).replace('@READBG@', read_bg))
with tempfile.TemporaryDirectory() as tmp:
    cpp = os.path.join(tmp, 't.cpp')
    exe = os.path.join(tmp, 't')
    open(cpp, 'w').write(src)
    c = subprocess.run(['clang++', '-std=c++14', '-w', '-o', exe, cpp], capture_output=True, text=True)
    if c.returncode:
        print(c.stderr[-3000:])
        sys.exit('FAIL: harness did not compile')
    r = subprocess.run([exe], capture_output=True, text=True)
    print(r.stdout, end='')
    sys.exit(r.returncode)
