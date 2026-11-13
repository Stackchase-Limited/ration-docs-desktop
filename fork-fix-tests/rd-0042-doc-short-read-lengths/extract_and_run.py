#!/usr/bin/env python3
"""
RD-0042 (our corpus run, no upstream issue): .doc readers used the length a
record claimed instead of the bytes the stream held, and read past their
buffers. VirtualStreamReader::ReadBytes stops at the end of the stream and
allocates only what it read; these callers kept the claimed length:

- PictureDescriptor::parse, Word 6/95 branch: embeddedDataSize = lcb - header
  stayed at the claimed size, and VMLPictureMapping::CopyPicture memcpy'd that
  many bytes from the short buffer (SIGSEGV in memmove under ASan on
  LibreOffice's sw/qa/core/data/ww6/pass/ofz21385-1.doc).
- VirtualStreamReader::ReadXst converted the claimed number of characters
  (heap over-read then SIGBUS on LibreOffice ww6/pass/crash-3.doc).
- StyleSheetInformation read bytes[4] unchecked and parsed when only one of
  bytes/size was valid ("||"); StyleSheet passed cbStshi instead of the bytes
  read (over-reads on POI's ...POIHWPFFuzzer-5418937293340672.doc).
- Also changed, not exercised here: ListLevel (grpprl/xst sizes), Outline-
  ListDescriptor::ConstructObject, StyleSheet's caller-side sizes, and the DOP's
  grfitbid byte (read via BytesToUChar).
Fix: each uses the number of bytes actually read (and checks the bound).

What runs (all compiled with -fsanitize=address; git show BASE_REF:... with
BASELINE=1):
- the REAL Word 6 picture statements of PictureDescriptor::parse, from
  "int header_size = 114;" to the end of that branch, with the REAL
  VirtualStreamReader::ReadBytes/GetPosition over a stand-in stream, then the
  copy CopyPicture makes (memcpy of embeddedDataSize bytes). Cases: lcb claims
  300 bytes of data with 40 in the stream (size must become 40), lcb fits
  (unchanged, 30), lcb smaller than the header (no data, as before).
- the REAL VirtualStreamReader::ReadXst (+ ReadBytes) in Word 6 and Word 97
  mode on a stream that ends inside the string: the characters present come
  back, nothing past them is read; a complete string is unchanged.
- the REAL StyleSheetInformation constructor with a 2-byte STSHI and with
  (NULL, 30): no read past/through the buffer; a full 22-byte one is unchanged.

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read the sources at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0042 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', 'bde4995945^')
BASELINE = bool(os.environ.get('BASELINE'))
D = 'MsBinaryFile/DocFile/'


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig', 'replace')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig', errors='replace').read()


def func(src, sig):
    a = src.find(sig)
    if a < 0:
        sys.exit(sig + ' not found - the extractor needs updating')
    i = src.find('{', a); depth = 0
    while True:
        if src[i] == '{': depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0: return src[a:i + 1]
        i += 1


COMMON = r'''
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
#define RELEASEARRAYOBJECTS(p) { delete[] (p); (p) = NULL; }
typedef unsigned int _UINT32;
#define GETBIT(from, num) ((from & (1 << num)) != 0)
#define GETBITS(from, numL, numH) ((from & (((1 << (numH - numL + 1)) - 1) << numL)) >> numL)
#define ENCODING_WINDOWS_1250 1250
namespace POLE { typedef unsigned long long uint64;
  struct Stream { std::vector<unsigned char> d; uint64 pos;
    uint64 size() { return d.size(); } void seek(uint64 p) { pos = p; }
    uint64 read(unsigned char* o, uint64 n) { uint64 k = pos >= d.size() ? 0 : (n < d.size() - pos ? n : d.size() - pos);
      if (k) memcpy(o, &d[pos], (size_t)k); pos += k; return k; } }; }
namespace DocFileFormat { struct FormatUtils {
  static unsigned char BytesToUChar(const unsigned char* b, unsigned int s, unsigned int l) { return (!b || s >= l) ? 0 : b[s]; }
  static short BytesToInt16(const unsigned char* b, unsigned int s, unsigned int l) { if (!b || s + 1 >= l) return 0; short v; memcpy(&v, b + s, 2); return v; }
  static unsigned short BytesToUInt16(const unsigned char* b, unsigned int s, unsigned int l) { if (!b || s + 1 >= l) return 0; unsigned short v; memcpy(&v, b + s, 2); return v; }
  static _UINT32 BytesToUInt32(const unsigned char* b, unsigned int s, unsigned int l) { if (!b || s + 3 >= l) return 0; _UINT32 v; memcpy(&v, b + s, 4); return v; }
  static bool GetWStringFromBytes(std::wstring& r, const unsigned char* b, int n, int) { r.clear(); for (int i = 0; i < n; i++) r += (wchar_t)b[i]; return true; } }; }
namespace NSFile { struct CUtf8Converter { static std::wstring GetWStringFromUTF16(const unsigned short* p, long n) {
  std::wstring r; for (long i = 0; i < n; i++) r += (wchar_t)p[i]; return r; } }; }
class VirtualStreamReader { public:
  POLE::Stream* stream; POLE::uint64 position; int nWordVersion;
  unsigned char* ReadBytes(unsigned int count, bool isResultNeeded);
  unsigned long GetPosition() const; std::wstring ReadXst(); };
@@READBYTES@@
@@GETPOSITION@@
'''

PICTURE = COMMON + r'''
int main(int argc, char** argv) {
  POLE::Stream s; s.pos = 0; s.d.assign(114 + 40, 0x5A);           // header + 40 bytes of picture data left
  VirtualStreamReader reader; reader.stream = &s; reader.position = 0; reader.nWordVersion = 1;
  int lcb = atoi(argv[1]), sz_hdr = 58;
  if (argv[1][0] == 'f') { s.d.assign(114 + 30, 0x5A); lcb = 58 + 114 + 30; }
  int embeddedDataSize = 0; unsigned char* embeddedData = NULL; unsigned char* embeddedDataHeader = NULL;
  {
@@FRAGMENT@@
  }
  if (embeddedData && embeddedDataSize > 0) {              // what VMLPictureMapping::CopyPicture does with it
    unsigned char* copy = new unsigned char[embeddedDataSize + 136];
    memcpy(copy + 136, embeddedData, embeddedDataSize); delete[] copy; }
  printf("size=%d\n", embeddedData && embeddedDataSize > 0 ? embeddedDataSize : 0);
  return 0;
}
'''

XST = COMMON + r'''
@@READXST@@
int main(int argc, char** argv) {
  POLE::Stream s; s.pos = 0; bool word97 = argv[1][0] == '9'; bool cut = argv[1][1] == 'c';
  if (word97) { unsigned char h[] = {10, 0}; s.d.assign(h, h + 2); for (int i = 0; i < (cut ? 3 : 10); i++) { s.d.push_back('a' + i); s.d.push_back(0); } }
  else { s.d.push_back(10); for (int i = 0; i < (cut ? 3 : 10); i++) s.d.push_back('a' + i); }
  VirtualStreamReader r; r.stream = &s; r.position = 0; r.nWordVersion = word97 ? 0 : 1;
  std::wstring w = r.ReadXst(); std::string n(w.begin(), w.end());
  printf("xst=%s\n", n.c_str()); return 0;
}
'''

STSHI = COMMON + r'''
using namespace DocFileFormat;
struct LSD { bool fLocked, fSemiHidden, fUnhideWhenUsed, fQFormat; unsigned short iPriority, fReserved; };
struct StyleSheetInformation { unsigned short cstd, cbSTDBaseInFile; bool fStdStylenamesWritten; unsigned short stiMaxWhenSaved,
  istdMaxFixedWhenSaved, nVerBuiltInNamesWhenSaved; std::vector<unsigned short> rgftcStandardChpStsh; unsigned short cbLSD;
  std::vector<LSD> mpstilsd; StyleSheetInformation(unsigned char* bytes, int size); };
@@CTOR@@
int main(int argc, char** argv) {
  unsigned char* b = NULL; int n = 0;
  if (argv[1][0] == 's') { n = 2; b = new unsigned char[2]; b[0] = 7; b[1] = 0; }
  else if (argv[1][0] == 'z') { n = 30; }
  else { n = 22; b = new unsigned char[22](); b[0] = 7; b[4] = 1; }
  StyleSheetInformation i(b, n);
  printf("cstd=%d written=%d\n", i.cstd, (int)i.fStdStylenamesWritten); delete[] b; return 0;
}
'''


def build_run(work, name, code, cases):
    p = os.path.join(work, name + '.cpp')
    open(p, 'w').write(code.replace('#include <cstdio>', '#include <cstdio>\n#include <cstdlib>'))
    exe = p[:-4]
    r = subprocess.run(['c++', '-std=gnu++11', '-fsanitize=address', '-g', '-w', p, '-o', exe], capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed (%s):\n%s' % (name, r.stderr[-3000:]))
    fails = 0
    for arg, label, want in cases:
        r = subprocess.run([exe, arg], capture_output=True, text=True, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
        m = re.search(r'ERROR: AddressSanitizer: ([\w-]+)', r.stderr)
        ok = r.returncode == 0 and not m and r.stdout.strip() == want
        fails += not ok
        print(('ok   ' if ok else 'FAIL ') + '%s (%s): %s' % (label, 'baseline ' + BASE_REF if BASELINE else 'working tree',
              ('ASan ' + m.group(1)) if m else (r.stdout.strip() or 'rc=%d' % r.returncode)))
    return fails


def main():
    vsr = read(D + 'VirtualStreamReader.cpp')
    common = {'@@READBYTES@@': func(vsr, 'unsigned char* VirtualStreamReader::ReadBytes'),
              '@@GETPOSITION@@': func(vsr, 'unsigned long VirtualStreamReader::GetPosition')}
    pic = read(D + 'PictureDescriptor.cpp')
    a = pic.find('int header_size = 114;')
    b = pic.find('\t\telse\n', a)
    if a < 0 or b < 0:
        sys.exit('Word 6 picture statements not found - the extractor needs updating')
    frag = pic[a:pic.rfind('}', a, b)]          # up to (not including) the brace closing the Word 6 branch
    work = tempfile.mkdtemp(prefix='rd0042-')

    def sub(code, extra):
        for k, v in list(common.items()) + list(extra.items()):
            code = code.replace(k, v)
        return code
    fails = build_run(work, 'picture', sub(PICTURE, {'@@FRAGMENT@@': frag}),
                      [('472', 'Word 6 picture: lcb claims 300 data bytes, 40 in the stream', 'size=40'),
                       ('f', 'Word 6 picture: lcb fits the stream (unchanged)', 'size=30'),
                       ('100', 'Word 6 picture: lcb smaller than the header (no data, unchanged)', 'size=0')])
    fails += build_run(work, 'xst', sub(XST, {'@@READXST@@': func(vsr, 'std::wstring VirtualStreamReader::ReadXst')}),
                       [('6c', 'ReadXst Word 6: stream ends after 3 of 10 characters', 'xst=abc'),
                        ('9c', 'ReadXst Word 97: stream ends after 3 of 10 characters', 'xst=abc'),
                        ('6f', 'ReadXst Word 6: complete string (unchanged)', 'xst=abcdefghij'),
                        ('9f', 'ReadXst Word 97: complete string (unchanged)', 'xst=abcdefghij')])
    fails += build_run(work, 'stshi', sub(STSHI, {'@@CTOR@@': func(read(D + 'StyleSheetInformation.cpp'),
                                                                   'StyleSheetInformation::StyleSheetInformation')}),
                       [('s', 'STSHI of 2 bytes', 'cstd=7 written=0'),
                        ('z', 'STSHI with no bytes but a size', 'cstd=0 written=0'),
                        ('f', 'STSHI of 22 bytes (unchanged)', 'cstd=7 written=1')])
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
