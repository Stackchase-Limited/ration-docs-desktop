#!/usr/bin/env python3
"""
RD-0083 (our crafted-input audit, no upstream issue): a .doc or .xls
encryption header whose salt or verifier runs past its stream/record made x2t
read past its buffer. ASan on crafted files: READ of 1024 bytes from a 20-byte
buffer (std::string ctor) in DocFile/EncryptionHeader.cpp on 47304.doc with
fEncrypted and saltSize 0x400; READ of 16 in RC4EncryptionHeader::load and of 2
in FilePass::readFields on SimpleWithColours.xls with a crafted FilePass.

Cause: DocFile/EncryptionHeader.cpp kept the claimed sizes after
VirtualStreamReader::ReadBytes (which stops at the end of the stream);
XlsFile RC4EncryptionHeader::load memcpy'd the verifier and its hash from the
record without a bounds check (and pos + saltSize could overflow);
FilePass::readFields read majorVer from a record that may end before it.
Fix: keep the bytes read / check against the record.

What runs (-fsanitize=address):
- the REAL .doc statements from "crypt_data_aes.saltSize = tStream.ReadUInt32();"
  up to "pos = tStream.GetPosition();" with the REAL VirtualStreamReader
  methods: salt 0x400 with 20 bytes left (salt 20), a complete header (16/16/20,
  unchanged);
- the REAL .xls statements from "record >> crypt_data_aes.saltSize;" up to
  "pos = record.getRdPtr();" and the REAL FilePass "majorVer = ..." statement,
  on a CFRecord with its REAL bounds-checking methods: record ending after a
  0-byte salt (verifier not read), salt size 0xFFFFFFF0 (no overflow), a
  complete one (16/16/32, unchanged), FilePass of 2 bytes (majorVer 0).

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read the sources at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0083 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', 'c148ca7643^')
BASELINE = bool(os.environ.get('BASELINE'))


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig', 'replace')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig', errors='replace').read()


def func(src, sig, frm=0):
    """sig ... its brace-matched body (the REAL code)."""
    a = src.find(sig, frm)
    if a < 0:
        sys.exit(repr(sig) + ' not found - the extractor needs updating')
    i = src.find('{', a); depth = 0
    while True:
        if src[i] == '{': depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0: return src[a:i + 1]
        i += 1


def span(src, start, end, frm=0):
    """The statements from `start` up to (not including) `end` (the REAL code)."""
    a = src.find(start, frm)
    b = src.find(end, a + len(start)) if a >= 0 else -1
    if a < 0 or b < 0:
        sys.exit(repr(start) + ' .. ' + repr(end) + ' not found - the extractor needs updating')
    return src[a:b]


def build_run(code, cases, tag):
    """Compile with ASan, run each (arg, label, expected stdout); print ok/FAIL; return #failures."""
    work = tempfile.mkdtemp(prefix=tag + '-')
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write(code)
    exe = p[:-4]
    r = subprocess.run(['c++', '-std=gnu++14', '-fsanitize=address', '-g', '-w', p, '-o', exe], capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-3000:])
    fails = 0
    for arg, label, want in cases:
        r = subprocess.run([exe, arg], capture_output=True, text=True,
                           env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0:alloc_dealloc_mismatch=0:allocator_may_return_null=1'))
        m = re.search(r'ERROR: AddressSanitizer: (out of memory|requested allocation size|[\w-]+)', r.stderr)
        ok = r.returncode == 0 and not m and r.stdout.strip() == want
        fails += not ok
        print(('ok   ' if ok else 'FAIL ') + '%s (%s): %s' % (label, 'baseline ' + BASE_REF if BASELINE else 'working tree',
              ('ASan ' + m.group(1)) if m else (r.stdout.strip() or r.stderr.strip()[-200:] or 'rc=%d' % r.returncode)))
    return fails


D = 'MsBinaryFile/DocFile/'

# touch() reads every byte a converter is told it may read (what GetWStringFromUTF16 /
# GetWStringFromBytes / BorderCode do), so ASan reports a read past a short buffer.
DOC_COMMON = r"""
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include <memory>
#include <algorithm>
#define RELEASEARRAYOBJECTS(p) { delete[] (p); (p) = NULL; }
#define RELEASEOBJECT(p) { delete (p); (p) = NULL; }
#define ENCODING_WINDOWS_1250 1250
typedef unsigned int _UINT32; typedef int _INT32; typedef unsigned long ULONG; typedef unsigned char BYTE;
typedef unsigned short UTF16;
namespace POLE { typedef unsigned long long uint64;
  struct Stream { std::vector<unsigned char> d; uint64 pos = 0;
    uint64 size() { return d.size(); } void seek(uint64 p) { pos = p; }
    uint64 read(unsigned char* o, uint64 n) { uint64 k = pos >= d.size() ? 0 : (n < d.size() - pos ? n : d.size() - pos);
      if (k) memcpy(o, &d[pos], (size_t)k); pos += k; return k; } }; }
static volatile unsigned sink;
static void touch(const unsigned char* b, long n) { for (long i = 0; i < n; i++) sink += b[i]; }
static int g_last = -1; // length of the last ANSI conversion
namespace NSFile { struct CUtf8Converter { static std::wstring GetWStringFromUTF16(const unsigned short* p, long n) {
  touch((const unsigned char*)p, n * 2); return std::wstring(n > 0 ? n : 0, L'x'); } }; }
static std::wstring convertUtf16ToWString(const UTF16* p, int n) { touch((const unsigned char*)p, n * 2); return std::wstring(n > 0 ? n : 0, L'x'); }
namespace DocFileFormat { struct FormatUtils {
  static bool BitmaskToBool(int v, int m) { return (v & m) == m; }
  static int BitmaskToInt(int v, int m) { int r = v & m; while (m && !(m & 1)) { m >>= 1; r >>= 1; } return r; }
  static bool GetWStringFromBytes(std::wstring& r, unsigned char* b, int n, int) { if (!b) return false; g_last = n; touch(b, n); r.assign(n > 0 ? n : 0, L'x'); return true; } }; }
class VirtualStreamReader { public:
  int nWordVersion; POLE::Stream* stream; POLE::uint64 position;
  VirtualStreamReader(POLE::Stream* s, ULONG p, int v) : nWordVersion(v), stream(s), position(p) {}
  unsigned short ReadUInt16(); short ReadInt16(); int ReadInt32(); unsigned int ReadUInt32(); unsigned char ReadByte();
  unsigned char* ReadBytes(unsigned int count, bool isResultNeeded);
  unsigned long GetPosition() const; unsigned long GetSize() const; int Seek(int offset, int origin);
  std::wstring ReadLengthPrefixedUnicodeString(); std::wstring ReadLengthPrefixedAnsiString(unsigned int max_size); };
@@READERS@@
using namespace DocFileFormat;
static POLE::Stream S(const std::string& hex) { POLE::Stream s; for (size_t i = 0; i + 1 < hex.size(); i += 2) s.d.push_back((unsigned char)strtol(hex.substr(i, 2).c_str(), 0, 16)); return s; }
"""


def readers(extra=()):
    vsr = read(D + 'VirtualStreamReader.cpp')
    sigs = ['unsigned short VirtualStreamReader::ReadUInt16', 'short VirtualStreamReader::ReadInt16',
            'int VirtualStreamReader::ReadInt32', 'unsigned int VirtualStreamReader::ReadUInt32',
            'unsigned char VirtualStreamReader::ReadByte', 'unsigned char* VirtualStreamReader::ReadBytes',
            'unsigned long VirtualStreamReader::GetPosition', 'unsigned long VirtualStreamReader::GetSize',
            'int VirtualStreamReader::Seek'] + list(extra)
    return '\n'.join(func(vsr, s) for s in sigs)


def doc_code(body, extra=()):
    return DOC_COMMON.replace('@@READERS@@', readers(extra)) + body


X = 'MsBinaryFile/XlsFile/Format/'

XLS_HEAD = r"""
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include <list>
#include <map>
#include <memory>
#include <algorithm>
typedef unsigned int _UINT32; typedef int _INT32; typedef unsigned short _UINT16; typedef unsigned char BYTE;
typedef unsigned short UTF16;
static volatile unsigned sink;
static void touch(const void* b, long n) { for (long i = 0; i < n; i++) sink += ((const unsigned char*)b)[i]; }
static std::wstring convertUtf16ToWString(const UTF16* p, long n) { touch(p, n * 2); return std::wstring(n > 0 ? n : 0, L'x'); }
namespace XLS {
struct GlobalWorkbookInfo { unsigned short Version = 0x0600; };
class CFRecord; typedef std::shared_ptr<CFRecord> CFRecordPtr;
class CFRecord { public:
  size_t rdPtr = 0, size_ = 0; char* data_ = NULL; std::shared_ptr<GlobalWorkbookInfo> global_info_; unsigned short type_id_ = 0;
  unsigned short getTypeId() const { return type_id_; }
  static char intData[16];
  static const size_t MAX_RECORD_SIZE = 8224; static const size_t MAX_RECORD_SIZE_XLSB = 0xFFFFFFF;
  CFRecord(const std::string& bytes, unsigned short type = 0) : type_id_(type), global_info_(new GlobalWorkbookInfo) { size_ = bytes.size(); data_ = new char[size_]; if (size_) memcpy(data_, bytes.data(), size_); }
  ~CFRecord() { delete[] data_; }
  const char* getData() const; const size_t getDataSize() const; const size_t getRdPtr() const;
  const bool checkFitReadSafe(const size_t size) const; const bool checkFitWriteSafe(const size_t size) const;
  bool checkFitRead(const size_t size) const; bool checkFitWrite(const size_t size) const;
  void skipNunBytes(const size_t n);
  void appendRawData(CFRecordPtr where_from); void appendRawData(const char* raw_data, const size_t size);
  @@TEMPLATES@@
  CFRecord& operator >> (unsigned char& val) { loadAnyData(val); return *this; }
  CFRecord& operator >> (unsigned short& val) { loadAnyData(val); return *this; }
  CFRecord& operator >> (unsigned int& val) { loadAnyData(val); return *this; }
  CFRecord& operator >> (int& val) { loadAnyData(val); return *this; }
  CFRecord& operator >> (short& val) { loadAnyData(val); return *this; }
  CFRecord& operator >> (char& val) { loadAnyData(val); return *this; }
};
char CFRecord::intData[16];
CFRecord& operator>>(CFRecord & record, std::string & str);
@@METHODS@@
}
using namespace XLS;
static std::string H(const std::string& hex) { std::string s; for (size_t i = 0; i + 1 < hex.size(); i += 2) s += (char)strtol(hex.substr(i, 2).c_str(), 0, 16); return s; }
"""


def xls_code(body):
    cpp = read(X + 'Binary/CFRecord.cpp'); h = read(X + 'Binary/CFRecord.h')
    tmpl = 'template<class T>\n' + func(h, 'const T* getCurData() const') + '\ntemplate<class T>\n' + func(h, 'bool loadAnyData(T& val)')
    sigs = ['const char* CFRecord::getData() const', 'const size_t CFRecord::getDataSize() const',
            'const size_t CFRecord::getRdPtr() const', 'const bool CFRecord::checkFitReadSafe',
            'const bool CFRecord::checkFitWriteSafe', 'bool CFRecord::checkFitRead(', 'bool CFRecord::checkFitWrite(',
            'void CFRecord::skipNunBytes', 'void CFRecord::appendRawData(CFRecordPtr where_from)',
            'void CFRecord::appendRawData(const char* raw_data', 'CFRecord& operator>>(CFRecord & record, std::string & str)']
    methods = '\n'.join(func(cpp, s) for s in sigs)
    return XLS_HEAD.replace('@@TEMPLATES@@', tmpl).replace('@@METHODS@@', methods) + body


DOC_DRV = r"""
struct CryptAes { _UINT32 saltSize = 0; std::string saltValue, encryptedVerifierInput, encryptedVerifierValue; _UINT32 hashSize = 0; };
int main(int argc, char** argv) {
  std::string m = argv[1]; POLE::Stream s; int ProviderType = 1;
  if (m == "salt") s = S("00040000" + std::string(40, '5'));
  if (m == "ok") s = S("10000000" + std::string(64, '1') + "14000000" + std::string(40, '2') + "00");
  VirtualStreamReader tStream(&s, 0, 0); unsigned char* pDataRead = NULL; CryptAes crypt_data_aes; int pos = 0;
@@SNIP@@
  printf("salt=%d verifier=%d hash=%d\n", (int)crypt_data_aes.saltValue.size(), (int)crypt_data_aes.encryptedVerifierInput.size(), (int)crypt_data_aes.encryptedVerifierValue.size()); return 0;
}
"""

XLS_DRV = r"""
struct CryptAes { _UINT32 saltSize = 0; std::string saltValue, encryptedVerifierInput, encryptedVerifierValue; _UINT32 hashSize = 0; };
static CryptAes crypt_data_aes; static _UINT32 ProviderType = 0x18;
static void verifier(CFRecord& record) {
@@SNIP@@
}
static unsigned short filepass(CFRecord& record) { unsigned short majorVer = 0xAAAA;
@@FP@@
  return majorVer; }
int main(int argc, char** argv) {
  std::string m = argv[1];
  if (m == "fp") { CFRecord r(H("0100")); unsigned short t; r >> t; printf("majorVer=%d\n", filepass(r)); return 0; }
  std::string b;
  if (m == "short") b = "00000000";
  if (m == "huge") b = "feffffff" + std::string(32, '3');
  if (m == "ok") b = "10000000" + std::string(64, '1') + "14000000" + std::string(64, '2');
  CFRecord r(H(b)); verifier(r);
  printf("salt=%d verifier=%d hash=%d\n", (int)crypt_data_aes.saltValue.size(), (int)crypt_data_aes.encryptedVerifierInput.size(), (int)crypt_data_aes.encryptedVerifierValue.size()); return 0;
}
"""


def main():
    fails = 0
    src = read(D + 'EncryptionHeader.cpp')
    snip = span(src, 'crypt_data_aes.saltSize = tStream.ReadUInt32();', 'pos = tStream.GetPosition();')
    fails += build_run(doc_code(DOC_DRV.replace('@@SNIP@@', snip)),
                       [('salt', '.doc saltSize 0x400 with 20 bytes left', 'salt=20 verifier=0 hash=0'),
                        ('ok', '.doc complete header (unchanged)', 'salt=16 verifier=16 hash=20')], 'rd0083d')
    xs = read(X + 'Logic/Biff_structures/RC4EncryptionHeader.cpp')
    snip = span(xs, 'record >> crypt_data_aes.saltSize;', 'pos = record.getRdPtr();')
    fp = read(X + 'Logic/Biff_records/FilePass.cpp')
    a = fp.find('majorVer ='); line = fp[a:fp.find(';', a) + 1]
    fails += build_run(xls_code(XLS_DRV.replace('@@SNIP@@', snip).replace('@@FP@@', line)),
                       [('short', '.xls record ends after a 0-byte salt', 'salt=0 verifier=0 hash=0'),
                        ('huge', '.xls saltSize 0xFFFFFFFE (pos + saltSize wraps)', 'salt=0 verifier=0 hash=0'),
                        ('ok', '.xls complete header (unchanged)', 'salt=16 verifier=16 hash=32'),
                        ('fp', '.xls FilePass of 2 bytes', 'majorVer=0')], 'rd0083x')
    sys.exit(1 if fails else 0)



if __name__ == '__main__':
    main()
