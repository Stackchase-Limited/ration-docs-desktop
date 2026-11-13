#!/usr/bin/env python3
"""
RD-0088 (our crafted-input audit, no upstream issue): an .xls Continue record
shorter than its header made x2t write past a heap buffer - ASan
heap-buffer-overflow WRITE in CFRecord::appendRawData from
XLUnicodeRichExtendedString::appendNextContinue (crafted POI
SimpleWithColours.xls: an SST string continued into an empty Continue) and from
SortData::readFields (crafted maxindextest.xls: a 4-byte ContinueFrt12).

Cause (MsBinaryFile/XlsFile/Format/Logic): getDataSize() - 1 / - 12 wrapped for
a shorter record, and appendRawData's new char[size_ + size] wrapped too, so
memcpy wrote the old data past the new buffer.
Fix: an empty Continue is skipped for the string; a ContinueFrt12 of 12 bytes
or less adds nothing.

What runs: the REAL XLUnicodeRichExtendedString::appendNextContinue and the
REAL SortData statements from "std::list<CFRecordPtr>& recs =
continue_records[rt_ContinueFrt12];" up to its "for(unsigned int i = 0; ..."
loop, with the REAL CFRecord::appendRawData and bounds checks,
-fsanitize=address. Cases: empty Continue (record unchanged, 5 bytes), a
Continue of 3 bytes (7, unchanged), a 4-byte ContinueFrt12 (sort data
unchanged, 3), a 14-byte one (5, unchanged).

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read the sources at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0088 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '0ee329b64d^')
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
    code = '\ntypedef unsigned short RecordType; static const RecordType rt_SST = 0x00FC, rt_Continue = 0x003C, rt_ContinueFrt12 = 0x087F;\nnamespace XLS {\nstruct XLUnicodeRichExtendedString { bool fHighByte = true; std::list<CFRecordPtr>& cont_recs_;\n  XLUnicodeRichExtendedString(std::list<CFRecordPtr>& l) : cont_recs_(l) {}\n  const bool appendNextContinue(CFRecord& record, const bool read_high_byte); };\n@@FN@@\n}\nstatic void sortdata(CFRecord& record, std::map<unsigned short, std::list<CFRecordPtr> >& continue_records) {\n@@SNIP1@@\n}\nint main(int argc, char** argv) {\n  std::string m = argv[1];\n  if (m == "sst0" || m == "sst3") { std::list<CFRecordPtr> l; l.push_back(CFRecordPtr(new CFRecord(H(m == "sst0" ? "" : "004344"), rt_Continue)));\n    CFRecord r(H("0a00004142")); XLUnicodeRichExtendedString s(l); s.appendNextContinue(r, true); printf("size=%d\\n", (int)r.getDataSize()); }\n  else { std::map<unsigned short, std::list<CFRecordPtr> > c;\n    c[rt_ContinueFrt12].push_back(CFRecordPtr(new CFRecord(H(m == "sort4" ? "7f080000" : "7f0800000000000000000000" "4142"), rt_ContinueFrt12)));\n    CFRecord r(H("010203")); sortdata(r, c); printf("size=%d\\n", (int)r.getDataSize()); }\n  return 0;\n}\n'
    code = code.replace('@@FN@@', func(read(X + 'Logic/Biff_structures/XLUnicodeRichExtendedString.cpp'), 'const bool XLUnicodeRichExtendedString::appendNextContinue'))
    code = code.replace('@@SNIP1@@', span(read(X + 'Logic/Biff_records/SortData.cpp'), 'std::list<CFRecordPtr>& recs = continue_records[rt_ContinueFrt12];', 'for(unsigned int i = 0; i < cconditions'))
    fails = build_run(xls_code(code), [('sst0', 'SST string continued into an empty Continue', 'size=5'), ('sst3', 'SST string continued into 3 bytes (unchanged)', 'size=7'), ('sort4', 'SortData with a 4-byte ContinueFrt12', 'size=3'), ('sort14', 'SortData with a 14-byte ContinueFrt12 (unchanged)', 'size=5')], 'rd0088')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
