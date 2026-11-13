#!/usr/bin/env python3
"""
RD-0087 (our crafted-input audit, no upstream issue): an .xls hyperlink
moniker or ActiveX picture key whose length runs past its record made x2t read
past the record buffer - ASan heap-buffer-overflow in ConvertUTF16toUTF32 from
FileMoniker::load on a crafted POI WithHyperlink.xls whose HLINK file moniker
says cbUnicodePathBytes 0x1000 with 8 bytes left.

Cause (MsBinaryFile/XlsFile/Format/Logic/Biff_structures): FileMoniker::load
(cbUnicodePathBytes), ItemMoniker::load (delimiter/item Unicode sizes) and
PictFmlaKey::load (cbKey) converted or copied the claimed byte count straight
from getCurData. Fix: each length is limited to the bytes left in the record.

What runs: the REAL FileMoniker::load, ItemMoniker::load and PictFmlaKey::load
on a CFRecord with its REAL bounds-checking methods and string reader,
-fsanitize=address; convertUtf16ToWString is a stand-in that reads every byte
it is told to; PictFmlaKey's ObjFmla members are stand-ins. Cases: file moniker
path of 0x1000 bytes with 8 left (4 chars) and complete (4, unchanged); item
moniker delimiter of 0x1fe bytes with 4 left (2 chars); picture key of 0x1000
with 5 left (5).

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read the sources at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0087 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '195e8f254a^')
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

def main():
    code = '\nnamespace OSHARED {\nstruct FileMoniker { _UINT16 cAnti = 0; std::string ansiPath; _UINT16 endServer = 0, versionNumber = 0; _UINT32 cbUnicodePathSize = 0; _UINT16 usKeyValue = 3; std::wstring unicodePath;\n  void load(XLS::CFRecord& record); };\nstruct ItemMoniker { std::string delimiterAnsi; std::wstring delimiterUnicode; std::string itemAnsi; std::wstring itemUnicode; void load(XLS::CFRecord& record); };\n@@FN@@\n@@FN2@@\n}\nnamespace XLS {\nstruct ObjFmla { void load(CFRecord&) {} };\nstruct PictFmlaKey { _UINT32 cbKey = 0; std::wstring keyBuf; ObjFmla fmlaLinkedCell, fmlaListFillRange; void load(CFRecord& record); };\n@@FN3@@\n}\nint main(int argc, char** argv) {\n  std::string m = argv[1];\n  std::string fm = "0000" "01000000" "00" "ffff" "adde" + std::string(40, \'0\') + "00010000";\n  if (m == "file" || m == "fileok") { CFRecord r(H(fm + (m == "file" ? "00100000" : "08000000") + "0300" "5000500050005000"));\n    OSHARED::FileMoniker f; f.load(r); printf("path=%d\\n", (int)f.unicodePath.size()); }\n  if (m == "item") { CFRecord r(H("00020000" "2100" "41004200")); OSHARED::ItemMoniker i; i.load(r); printf("delim=%d\\n", (int)i.delimiterUnicode.size()); }\n  if (m == "key") { CFRecord r(H("00100000" "4142434445")); PictFmlaKey k; k.load(r); printf("key=%d\\n", (int)k.keyBuf.size()); }\n  return 0;\n}\n'
    code = code.replace('@@FN@@', func(read(X + 'Logic/Biff_structures/FileMoniker.cpp'), 'void FileMoniker::load(XLS::CFRecord& record)'))
    code = code.replace('@@FN2@@', func(read(X + 'Logic/Biff_structures/ItemMoniker.cpp'), 'void ItemMoniker::load(XLS::CFRecord& record)'))
    code = code.replace('@@FN3@@', func(read(X + 'Logic/Biff_structures/PictFmlaKey.cpp'), 'void PictFmlaKey::load(CFRecord& record)'))
    fails = build_run(xls_code(code), [('file', 'file moniker path 0x1000 bytes, 8 left', 'path=4'), ('fileok', 'file moniker path of 8 bytes (unchanged)', 'path=4'), ('item', 'item moniker delimiter 0x1fe bytes, 4 left', 'delim=2'), ('key', 'picture key 0x1000 bytes, 5 left', 'key=5')], 'rd0087')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
