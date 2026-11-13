#!/usr/bin/env python3
"""
RD-0089 (our crafted-input audit, no upstream issue): an .xls drawing whose
property table (OfficeArtFOPT) claims more properties than its record holds
made x2t read past the record buffer - ASan heap-buffer-overflow (READ of 2) in
OfficeArtFOPTE::load_and_create from OfficeArtRGFOPTE::load on a crafted POI
27933.xls whose FOPT says 4095 properties.

Cause (MsBinaryFile/XlsFile/Format/Logic/Biff_structures/ODRAW/OfficeArtFOPTE.cpp):
load_and_create, called once per claimed property, read the property id
through getCurData without a bounds check.
Fix: no property past the end of the record.

What runs: the REAL OfficeArtFOPTE::load_and_create(XLS::CFRecord&) on a
CFRecord with its REAL bounds-checking methods, -fsanitize=address, called
options_count times as OfficeArtRGFOPTE::load does (a missing property is
skipped); OfficeArtFOPTE::create/load are stand-ins reading the 6-byte
property. Cases: 2 properties in the record with a count of 4095 (2 loaded),
a count of 2 (2, unchanged).

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read the sources at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0089 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '69cf1181b0^')
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
    code = '\n#define GETBITS(from, numL, numH) ((from & (((1 << (numH - numL + 1)) - 1) << numL)) >> numL)\nnamespace ODRAW {\nstruct OfficeArtFOPTE; typedef std::shared_ptr<OfficeArtFOPTE> OfficeArtFOPTEPtr;\nstruct OfficeArtFOPTE { unsigned short opid = 0; _INT32 op = 0;\n  void load(XLS::CFRecord& record) { unsigned short id; record >> id >> op; opid = GETBITS(id, 0, 13); }\n  static OfficeArtFOPTEPtr create(unsigned short) { return OfficeArtFOPTEPtr(new OfficeArtFOPTE); }\n  static OfficeArtFOPTEPtr load_and_create(XLS::CFRecord& record); };\n@@FN@@\n}\nint main(int argc, char** argv) {\n  std::string m = argv[1]; int options_count = m == "huge" ? 4095 : 2; int n = 0;\n  CFRecord r(H("7f0004000000" "bf0008000800"));\n  for (int i = 0; i < options_count; ++i) { ODRAW::OfficeArtFOPTEPtr f = ODRAW::OfficeArtFOPTE::load_and_create(r); if (!f) continue; n++; }\n  printf("loaded=%d\\n", n > 2 ? -n : n); return 0;\n}\n'
    code = code.replace('@@FN@@', func(read(X + 'Logic/Biff_structures/ODRAW/OfficeArtFOPTE.cpp'), 'OfficeArtFOPTEPtr OfficeArtFOPTE::load_and_create(XLS::CFRecord& record)'))
    fails = build_run(xls_code(code), [('huge', '2 properties in the record, count 4095', 'loaded=2'), ('ok', '2 properties, count 2 (unchanged)', 'loaded=2')], 'rd0089')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
