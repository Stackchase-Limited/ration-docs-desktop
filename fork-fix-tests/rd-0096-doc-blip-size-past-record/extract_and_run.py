#!/usr/bin/env python3
"""
RD-0096 (our crafted-input audit, no upstream issue): a .doc picture (blip)
record claiming more bytes than it holds put uninitialised heap into the .docx
image, or made x2t over-read 4 GB. Crafted POI 53446.doc (Data stream, PNG blip
at offset 236): size 3057 -> 4000 gives a docx image1.png of 3967 bytes ending
in 943 bytes of ASan's malloc fill (0xbe), instead of 3024; size -> 16 gives
ASan heap-buffer-overflow READ of size 4294967279 at MemoryStream.cpp:219.

Cause (MsBinaryFile/DocFile): MemoryStream::ReadBytes allocated the count asked
for but copied only the bytes left (the tail stayed uninitialised), and once the
position was past the end (ReadByte advances it anyway) m_Size - m_Position
wrapped and the whole count was copied from past the buffer. BitmapBlip asks
for its pixels with the header's claimed size, not the size Record clamped,
and writes pvBitsSize bytes as the image.
Fix: ReadBytes returns only the bytes present; BitmapBlip keeps the number it
got as pvBitsSize.

What runs: the REAL MemoryStream constructor, ReadByte, ReadBytes, GetPosition,
GetSize, the REAL Record(IBinaryReader*, ...) constructor body and the REAL
BitmapBlip(IBinaryReader*, ...) constructor body (OfficeDrawing/), with a
stand-in FormatUtils/Log, -fsanitize=address. The parent stream holds a PNG
blip body (16-byte uid, tag byte, pixel bytes 0x01, 0x02, ...).
Cases: a blip claiming 4000 bytes with 100 present (before: pvBitsSize 3983,
the tail uninitialised - its sum differs; now 83 bytes), a blip claiming 16 (uid
only; before: 4 GB over-read; now 0 bytes), a blip claiming exactly the 100
bytes present (unchanged, 83 bytes).

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read the sources at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0096 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '558d235a1c^')
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

PRE = r'''
#include <cstdio>
#include <cstring>
#include <string>
typedef unsigned long long _UINT64; typedef unsigned int _UINT32; typedef int _INT32;
#define RELEASEARRAYOBJECTS(p) { delete[] (p); (p) = NULL; }
#define RELEASEOBJECT(p) { delete (p); (p) = NULL; }
struct Log { static void warning(const wchar_t*) {} };
struct IBinaryReader { virtual ~IBinaryReader() {} virtual unsigned char ReadByte() = 0; virtual unsigned char* ReadBytes(unsigned int, bool) = 0;
  virtual unsigned long GetPosition() const = 0; virtual unsigned long GetSize() const = 0; };
class MemoryStream : public IBinaryReader { public:
  MemoryStream(unsigned char* data, unsigned long size, bool bMemCopy = true); virtual ~MemoryStream() { if (bMemoryCopy) RELEASEARRAYOBJECTS(m_Data); }
  virtual unsigned char ReadByte(); virtual unsigned char* ReadBytes(unsigned int count, bool isResultNeeded);
  virtual unsigned long GetPosition() const; virtual unsigned long GetSize() const;
private: unsigned char* m_Data; unsigned long m_Size; unsigned long m_Position; bool bMemoryCopy; };
@@MS@@
struct Record { static const unsigned int HEADER_SIZE_IN_BYTES = 8; };
struct Blip {
  unsigned int HeaderSize, BodySize; unsigned char* RawData; IBinaryReader* Reader;
  unsigned char *m_rgbUid, *m_rgbUidPrimary, *m_pvBits; unsigned char m_bTag; unsigned int pvBitsSize;
  Blip() : RawData(NULL), Reader(NULL), m_rgbUid(NULL), m_rgbUidPrimary(NULL), m_pvBits(NULL), m_bTag(0), pvBitsSize(0) {}
  void record(IBinaryReader* _reader, unsigned int bodySize) { BodySize = bodySize; @@REC@@ }
  void blip(unsigned int size, unsigned int instance) @@BLIP@@
};
int main(int argc, char** argv) {
  std::string m = argv[1]; unsigned int claimed = m == "long" ? 4000 : m == "uid" ? 16 : 100;
  unsigned char body[100]; for (int i = 0; i < 100; i++) body[i] = (unsigned char)(i < 17 ? 0x55 : i - 16);
  MemoryStream parent(body, 100); Blip b; b.record(&parent, claimed); b.blip(claimed, 0x6E0);
  unsigned long s = 0; for (unsigned int i = 0; i < b.pvBitsSize; i++) s += b.m_pvBits[i];
  printf("pvBitsSize=%u sum=%lu\n", b.pvBitsSize, s); return 0;
}
'''


def main():
    ms = read(D + 'MemoryStream.cpp')
    msc = '\n'.join(func(ms, s) for s in ('MemoryStream::MemoryStream (', 'unsigned char MemoryStream::ReadByte', 'unsigned char* MemoryStream::ReadBytes',
                                           'unsigned long MemoryStream::GetPosition', 'unsigned long MemoryStream::GetSize'))
    rec = func(read(D + 'OfficeDrawing/Record.cpp'), 'Record::Record( IBinaryReader* _reader')
    rec = rec[rec.index('{') + 1:rec.rindex('}')]
    blip = func(read(D + 'OfficeDrawing/BitmapBlip.cpp'), 'BitmapBlip::BitmapBlip(IBinaryReader* _reader')
    blip = blip[blip.index('{'):]
    code = PRE.replace('@@MS@@', msc).replace('@@REC@@', rec).replace('@@BLIP@@', blip)
    fails = build_run(code, [('long', 'blip claiming 4000 bytes, 100 present', 'pvBitsSize=83 sum=3486'),
                             ('uid', 'blip claiming 16 bytes (uid only)', 'pvBitsSize=0 sum=0'),
                             ('exact', 'blip claiming the 100 bytes present (unchanged)', 'pvBitsSize=83 sum=3486')], 'rd0096')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
