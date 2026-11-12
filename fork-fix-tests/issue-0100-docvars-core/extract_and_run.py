#!/usr/bin/env python3
"""
#100 "Support variables", core side - w:docVars were dropped by every save.

Bug: a docx with document variables (settings.xml <w:docVars><w:docVar
w:name=".." w:val=".."/></w:docVars>, the values DOCVARIABLE fields show) lost
them as soon as it was saved from the editor. core parsed them into
CSettings::m_oDocVars, but BinarySettingsTableWriter::WriteSettings
(BinaryWriterD.cpp) never put them into the binary the editor opens, so the
docx written back from that binary had none; in Word every DOCVARIABLE field
then updates to "Error! No document variable supplied." (Checked with the
payload x2t: docx -> Editor.bin -> docx, settings.xml has no w:docVars.)
CDocVar::toXML also wrote name and value unescaped.

Fix: a DocVars settings item (c_oSer_SettingsType 100, kept clear of upstream
numbering) holding DocVar items with Name / Value strings; the reader
(Binary_SettingsTableReader::ReadDocVars / ReadDocVar) rebuilds m_oDocVars,
and CDocVar::toXML escapes both attributes. sdkjs keeps the item through the
editor (issue-0100-docvars-sdkjs-test.js).

What runs: the REAL DocVars block of WriteSettings, the DocVars branch of
ReadSettings, ReadDocVars, ReadDocVar, READ1_DEF, CDocVar::toXML,
CDocVars::toXML and the c_oSer_SettingsType / c_oSerDocVars enums are cut out
of core by brace matching and compiled with clang++ next to minimal stand-ins
(byte stream with the binary's item framing, nullable, XML escaper).
Checks: settings -> bin -> settings keeps names, values (incl. & < > " and
non-ASCII) and order; settings.xml escapes them; an item without a name is
dropped; no item is written when there are no variables.

NOT claimed: the full x2t is not built here (it was: docx -> bin -> docx with
x2t built from the fix keeps w:docVars; docbuilder with that x2t and the fixed
sdkjs keeps them through open/edit/save; the payload build drops them).

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read the sources at BASE_REF; must FAIL
  BASE_REF                  default: parent of the #100 core commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '48a2f86930^')
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


def find(text, pattern, what):
    m = re.search(pattern, text)
    if not m:
        print('FAIL: %s not found in source' % what)
        sys.exit(1)
    return m.start()


defines = read(D + 'BinWriter/BinReaderWriterDefines.h')
writer = read(D + 'BinWriter/BinaryWriterD.cpp')
reader = read(D + 'BinReader/BinaryReaderD.cpp')
settings = read('OOXML/DocxFormat/Settings/Settings.cpp')

enums = ''
for name in ('c_oSer_SettingsType', 'c_oSerDocVars'):
    at = find(defines, r'namespace %s\s*\{' % name, 'enum ' + name)
    enums += 'namespace %s%s\n' % (name, block(defines, defines.index('{', at)))
if not re.search(r'\bDocVars\s*=', enums):
    print('FAIL: c_oSer_SettingsType has no DocVars item - the binary cannot carry w:docVars')
    sys.exit(1)

w_at = find(writer, r'if \(oSettings\.m_oDocVars\.IsInit\(\)', 'the DocVars block of BinarySettingsTableWriter::WriteSettings')
write_block = block(writer, w_at)
r_at = find(reader, r'else if \(c_oSer_SettingsType::DocVars == type\)', 'the DocVars branch of Binary_SettingsTableReader::ReadSettings')
read_branch = block(reader, r_at)[len('else '):]
read_vars = block(reader, find(reader, r'int Binary_SettingsTableReader::ReadDocVars\s*\(', 'ReadDocVars'))
read_var = block(reader, find(reader, r'int Binary_SettingsTableReader::ReadDocVar\s*\(', 'ReadDocVar'))
read1 = re.search(r'#define READ1_DEF\(.*?\n(?:.*\\\n)*.*\n', reader).group(0)
var_xml = block(settings, find(settings, r'std::wstring CDocVar::toXML\(\) const', 'CDocVar::toXML'))
vars_xml = block(settings, find(settings, r'std::wstring CDocVars::toXML\(\) const', 'CDocVars::toXML'))

HARNESS = r'''
#include <cstdio>
#include <string>
#include <vector>
typedef unsigned char BYTE;
template<class T> class nullable {
	T* p = nullptr;
public:
	~nullable() { delete p; }
	bool IsInit() const { return p != nullptr; }
	void Init() { if (!p) p = new T(); }
	void reset() { delete p; p = nullptr; }
	T* operator->() { return p; }
	const T* operator->() const { return p; }
	T* GetPointer() { return p; }
};
namespace XmlUtils {
	std::wstring EncodeXmlString(const std::wstring& s) {
		std::wstring r;
		for (wchar_t c : s) switch (c) {
			case '&': r += L"&amp;"; break; case '<': r += L"&lt;"; break; case '>': r += L"&gt;"; break;
			case '"': r += L"&quot;"; break; case '\'': r += L"&apos;"; break; default: r += c; }
		return r;
	}
}
namespace OOX { namespace Settings {
	class CDocVar { public: std::wstring m_sName, m_sVal; std::wstring toXML() const; };
	class CDocVars { public: std::vector<CDocVar*> m_arrDocVar;
		~CDocVars() { for (auto* p : m_arrDocVar) delete p; } std::wstring toXML() const; };
	@VARXML@
	@VARSXML@
}}
struct CSettings { nullable<OOX::Settings::CDocVars> m_oDocVars; };
namespace BinDocxRW {
namespace c_oSerConstants { enum { ErrorFormat = -2, ErrorUnknown = -1, ReadOk = 0, ReadUnknown = 1, ErrorStream = 0x55 }; }
@ENUMS@
struct Stream {
	std::vector<BYTE> d; size_t pos = 0;
	void WriteBYTE(BYTE b) { d.push_back(b); }
	void WriteStringW3(const std::wstring& s) { for (wchar_t c : s) { d.push_back(c & 0xFF); d.push_back((c >> 8) & 0xFF); } }
	bool GetUCharWithResult(BYTE* b) { if (pos >= d.size()) return false; *b = d[pos++]; return true; }
	BYTE GetUChar() { return d[pos++]; }
	long GetLong() { long v = 0; for (int i = 0; i < 4; ++i) v |= (long)d[pos++] << (8 * i); return v; }
	BYTE* GetPointer(long n) { pos += n; return nullptr; }
	std::wstring GetString3(long n) { std::wstring s; for (long i = 0; i + 1 < n; i += 2) s += (wchar_t)(d[pos + i] | (d[pos + i + 1] << 8)); pos += n; return s; }
};
struct BinaryCommonWriter {
	Stream m_oStream;
	int WriteItemStart(BYTE type) { m_oStream.WriteBYTE(type); int p = (int)m_oStream.d.size(); for (int i = 0; i < 4; ++i) m_oStream.WriteBYTE(0); return p; }
	void WriteItemEnd(int p) { long len = (long)m_oStream.d.size() - p - 4; for (int i = 0; i < 4; ++i) m_oStream.d[p + i] = (len >> (8 * i)) & 0xFF; }
};
struct Writer {
	BinaryCommonWriter m_oBcw;
	void Write(CSettings& oSettings) { int nCurPos = 0; @WRITE@ }
};
@READ1@
class Binary_SettingsTableReader {
public:
	Stream m_oBufferedStream;
	int ReadSettings(BYTE type, long length, void* poResult) {
		CSettings* pSettings = static_cast<CSettings*>(poResult);
		int res = c_oSerConstants::ReadOk;
		if (false) {}
		else @READBRANCH@
		else res = c_oSerConstants::ReadUnknown;
		return res;
	}
	int ReadDocVars(BYTE type, long length, void* poResult);
	int ReadDocVar(BYTE type, long length, void* poResult);
	int ReadTable(long len, CSettings* s) { int res = 0; READ1_DEF(len, res, this->ReadSettings, s); return res; }
};
@READVARS@
@READVAR@
}
using namespace BinDocxRW;
static int fails = 0;
#define CHECK(c, ...) do { if (!(c)) { ++fails; printf("FAIL "); printf(__VA_ARGS__); printf("\n"); } } while (0)
static void add(CSettings& s, const std::wstring& n, const std::wstring& v) {
	s.m_oDocVars.Init(); auto* p = new OOX::Settings::CDocVar(); p->m_sName = n; p->m_sVal = v; s.m_oDocVars->m_arrDocVar.push_back(p); }
static std::vector<BYTE> write(CSettings& s) { Writer w; w.Write(s); return w.m_oBcw.m_oStream.d; }
static void read(const std::vector<BYTE>& b, CSettings& out) {
	Binary_SettingsTableReader r; r.m_oBufferedStream.d = b; r.ReadTable((long)b.size(), &out);
	CHECK(r.m_oBufferedStream.pos == b.size(), "reader did not consume the item"); }
int main() {
	CSettings s;
	add(s, L"ClientName", L"Acme & Sons");
	add(s, L"Contract<No>", L"K-42 \"x\" 'y'");
	add(s, L"Ort", L"Köln – 日本");
	add(s, L"Empty", L"");
	std::vector<BYTE> b = write(s);
	CHECK(!b.empty() && b[0] == c_oSer_SettingsType::DocVars, "no DocVars item written for 4 variables");
	CSettings back; read(b, back);
	CHECK(back.m_oDocVars.IsInit() && back.m_oDocVars->m_arrDocVar.size() == 4, "settings -> bin -> settings: variables lost");
	if (back.m_oDocVars.IsInit() && back.m_oDocVars->m_arrDocVar.size() == 4) {
		bool same = true;
		for (int i = 0; i < 4; ++i)
			same = same && back.m_oDocVars->m_arrDocVar[i]->m_sName == s.m_oDocVars->m_arrDocVar[i]->m_sName
			            && back.m_oDocVars->m_arrDocVar[i]->m_sVal == s.m_oDocVars->m_arrDocVar[i]->m_sVal;
		CHECK(same, "names/values/order changed on the way through the binary");
		if (same) printf("ok   4 variables (escapable, non-ASCII, empty value) survive settings -> bin -> settings\n");
		std::wstring xml = back.m_oDocVars->toXML();
		std::wstring want = L"<w:docVars><w:docVar w:name=\"ClientName\" w:val=\"Acme &amp; Sons\"/>"
			L"<w:docVar w:name=\"Contract&lt;No&gt;\" w:val=\"K-42 &quot;x&quot; &apos;y&apos;\"/>";
		CHECK(xml.compare(0, want.size(), want) == 0, "settings.xml w:docVars not escaped");
		if (xml.compare(0, want.size(), want) == 0) printf("ok   settings.xml escapes names and values\n");
	}
	/* no variables: no item */
	CSettings none; none.m_oDocVars.Init();
	CHECK(write(none).empty(), "an empty w:docVars wrote an item");
	CSettings none2; CHECK(write(none2).empty(), "no w:docVars wrote an item");
	/* a DocVar item without a name is dropped (w:name is required); the rest is read */
	CSettings bad; add(bad, L"", L"orphan"); add(bad, L"A", L"1");
	CSettings badBack; read(write(bad), badBack);
	CHECK(badBack.m_oDocVars.IsInit() && badBack.m_oDocVars->m_arrDocVar.size() == 1 && badBack.m_oDocVars->m_arrDocVar[0]->m_sName == L"A",
	      "nameless variable not dropped");
	printf(fails ? "FAIL %d check(s)\n" : "PASS #100 w:docVars kept through the binary (core)\n", fails);
	return fails ? 1 : 0;
}
'''

src = (HARNESS.replace('@ENUMS@', enums).replace('@WRITE@', write_block).replace('@READ1@', read1)
       .replace('@READBRANCH@', read_branch)
       .replace('@READVARS@', read_vars).replace('@READVAR@', read_var)
       .replace('@VARXML@', var_xml.replace('std::wstring CDocVar::', 'std::wstring CDocVar::'))
       .replace('@VARSXML@', vars_xml))
with tempfile.TemporaryDirectory() as tmp:
    cpp = os.path.join(tmp, 't.cpp')
    exe = os.path.join(tmp, 't')
    open(cpp, 'w').write(src)
    c = subprocess.run(['clang++', '-std=c++14', '-w', '-o', exe, cpp], capture_output=True, text=True)
    if c.returncode:
        print(c.stderr[-3000:])
        print('FAIL: harness did not compile')
        sys.exit(1)
    r = subprocess.run([exe], capture_output=True, text=True)
    print(r.stdout, end='')
    sys.exit(r.returncode)
