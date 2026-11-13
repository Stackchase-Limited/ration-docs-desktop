#!/usr/bin/env python3
"""
RD-0048 (our corpus run, no upstream issue): .doc lengths and counts far beyond
the file made x2t allocate until it was killed (1.5 GB watchdog):
- Apache POI's Fuzzed.doc: ListFormatOverrideTable (MsBinaryFile/DocFile/
  ListFormatOverrideTable.cpp) created `count` LFOs, count read from the file.
  It is now at most the 16-byte LFOs left in the stream.
- LibreOffice's sw/qa/core/data/ww6/pass/crash-7.doc and hang-1.doc: the Plex
  constructor (Plex.h) read lcb/4 CPs - zeros past the stream end - into a
  vector, lcb straight from the FIB (512 MB). lcb is now at most the size of the
  whole stream; a PLEX that runs a little past the end still reads its missing
  CPs as 0, as before (HeaderAndFooterTable and others rely on that).
- crash-7.doc: PieceTable (PieceTable.cpp) allocated and zero-filled lcbClx
  bytes (738 MB) before reading the Clx; it now allocates what the table stream
  holds after fcClx.

What runs (git show BASE_REF:... with BASELINE=1), with stand-in readers,
streams and element types:
- the REAL Plex<T> constructor: a CP-only PLEX with lcb 0x7FFFFFFF over a
  100-byte stream (the stand-in reader gives up after 1,000,000 reads and says
  so); and lcb 40 at fc 80 of the 100-byte stream - 20 bytes past the end - which
  must still give 10 CPs (unchanged);
- the REAL ListFormatOverrideTable constructor with count 0x10000000 over a
  64-byte stream (at most 3 LFOs), and with count 2 and room for them (2,
  unchanged);
- the REAL PieceTable constructor, compiled with -fsanitize=address and
  max_allocation_size_mb=256, with lcbClx 0x7FFFFFFF over a 100-byte table
  stream (must not ask for 2 GB), and a well-formed Clx with one piece
  (unchanged: 1 piece).

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read the sources at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0048 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '66ed47007e^')
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
#include <cstdlib>
#include <cstring>
#include <list>
#include <map>
#include <vector>
#define RELEASEOBJECT(p) { delete (p); (p) = NULL; }
#define RELEASEARRAYOBJECTS(p) { delete[] (p); (p) = NULL; }
typedef unsigned long ULONG;
namespace POLE { typedef unsigned long long uint64;
  struct Stream { std::vector<unsigned char> d; uint64 pos; uint64 size() { return d.size(); } void seek(uint64 p) { pos = p; }
    uint64 read(unsigned char* o, uint64 n) { uint64 k = pos >= d.size() ? 0 : (n < d.size() - pos ? n : d.size() - pos); if (k) memcpy(o, &d[pos], (size_t)k); pos += k; return k; } }; }
static long g_reads = 0;
struct VirtualStreamReader { POLE::Stream* s; unsigned long long position; int nWordVersion;
  VirtualStreamReader(POLE::Stream* st, ULONG p, int v) : s(st), position(p), nWordVersion(v) {}
  unsigned long GetSize() const { return (unsigned long)s->size(); } unsigned long GetPosition() const { return (unsigned long)position; }
  int ReadInt32() { if (++g_reads > 1000000) { printf("reads>1000000\n"); exit(0); } int v = 0;
    if (position + 4 <= s->d.size()) memcpy(&v, &s->d[(size_t)position], 4); position += 4; return v; }
  unsigned int ReadUInt32() { return (unsigned int)ReadInt32(); } };
'''

PLEX = COMMON + r'''
namespace DocFileFormat {
struct ByteStructure { virtual ~ByteStructure() {} };
struct EmptyStructure : ByteStructure { ByteStructure* ConstructObject(VirtualStreamReader*, int) { return new EmptyStructure(); } };
template<class T> class Plex { public: int CP_LENGTH; std::vector<int> CharacterPositions; std::vector<ByteStructure*> Elements; bool m_bIsValid;
  std::map<int, size_t> mapCP;
@@CTOR@@
};
}
using namespace DocFileFormat;
int main(int argc, char** argv) {
  POLE::Stream s; s.pos = 0; s.d.assign(100, 1);
  Plex<EmptyStructure>* p = argv[1][0] == 'h' ? new Plex<EmptyStructure>(0, &s, 0, 0x7FFFFFFFu, 0) : new Plex<EmptyStructure>(0, &s, 80, 40, 0);
  printf("cps=%zu\n", p->CharacterPositions.size()); return 0;
}
'''

LFO = COMMON + r'''
namespace DocFileFormat {
struct FibWord97 { unsigned int fcPlfLfo, lcbPlfLfo; }; struct FileInformationBlock { FibWord97 m_FibWord97; int m_nWordVersion; };
struct ListFormatOverrideLevel { ListFormatOverrideLevel(VirtualStreamReader*, int) {} };
struct ListFormatOverride { int clfolvl; ListFormatOverrideLevel** rgLfoLvl;
  ListFormatOverride(VirtualStreamReader* r, int len) : clfolvl(0), rgLfoLvl(NULL) { r->position += len; if (++g_reads > 1000000) { printf("lfos>1000000\n"); exit(0); } } };
struct ListFormatOverrideTable : std::vector<ListFormatOverride*> { static const int LFO_LENGTH = 16; static const int LFOLVL_LENGTH = 6;
  std::vector<unsigned int> cps; ListFormatOverrideTable(FileInformationBlock* fib, POLE::Stream* tableStream); };
@@CTOR@@
}
using namespace DocFileFormat;
int main(int argc, char** argv) {
  POLE::Stream s; s.pos = 0; s.d.assign(64, 0); int count = argv[1][0] == 'h' ? 0x10000000 : 2; memcpy(&s.d[0], &count, 4);
  FileInformationBlock fib; fib.m_FibWord97.fcPlfLfo = 0; fib.m_FibWord97.lcbPlfLfo = 64; fib.m_nWordVersion = 0;
  ListFormatOverrideTable t(&fib, &s); printf("lfos=%zu\n", t.size()); return 0;
}
'''

PIECE = COMMON + r'''
#define ENCODING_UTF16 1200
namespace DocFileFormat {
typedef std::pair<int, int> Int_Pair;
struct FormatUtils { static int BytesToInt32(const unsigned char* b, unsigned int s, unsigned int l) { if (!b || s + 3 >= l) return 0; int v; memcpy(&v, b + s, 4); return v; } };
struct PieceDescriptor { unsigned int fc; int cpStart, cpEnd, code_page;
  PieceDescriptor(unsigned char* b, int, int) : cpStart(0), cpEnd(0), code_page(1252) { memcpy(&fc, b + 2, 4); } };
struct FibWord97 { unsigned int fcClx, lcbClx; }; struct FibBase { bool fComplex; int fcMac; };
struct FileInformationBlock { FibWord97 m_FibWord97; FibBase m_FibBase; int m_CodePage; };
struct PieceTable { std::list<PieceDescriptor> Pieces; std::map<int, int>* FileCharacterPositions; std::map<int, int>* CharacterPositions;
  std::list<PieceDescriptor>::iterator m_carriageIter; PieceTable(FileInformationBlock* fib, POLE::Stream* tableStream, POLE::Stream* wordStream); };
@@CTOR@@
}
using namespace DocFileFormat;
int main(int argc, char** argv) {
  POLE::Stream t; t.pos = 0; t.d.assign(100, 0); POLE::Stream w; w.pos = 0; w.d.assign(4000, 'a');
  FileInformationBlock fib = {}; fib.m_FibWord97.fcClx = 0;
  if (argv[1][0] == 'h') fib.m_FibWord97.lcbClx = 0x7FFFFFFFu;
  else { // Clx: 0x02, lcb = 4+4+8, CPs 0 and 10, one PCD with fc 2048
    unsigned char c[] = {2, 16,0,0,0, 0,0,0,0, 10,0,0,0, 0,0, 0,8,0,0, 0,0}; memcpy(&t.d[0], c, sizeof(c)); fib.m_FibWord97.lcbClx = sizeof(c); }
  PieceTable p(&fib, &t, &w); printf("pieces=%zu\n", p.Pieces.size()); return 0;
}
'''


def build_run(work, name, code, cases, asan):
    p = os.path.join(work, name + '.cpp')
    open(p, 'w').write(code)
    exe = p[:-4]
    cmd = ['c++', '-std=gnu++11', '-w'] + (['-fsanitize=address', '-g'] if asan else []) + [p, '-o', exe]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed (%s):\n%s' % (name, r.stderr[-3000:]))
    fails = 0
    for arg, label, want in cases:
        r = subprocess.run([exe, arg], capture_output=True, text=True, timeout=120,
                           env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0:max_allocation_size_mb=256'))
        m = re.search(r'ERROR: AddressSanitizer: ([\w-]+)', r.stderr)
        out = r.stdout.strip()
        ok = r.returncode == 0 and not m and out == want
        fails += not ok
        print(('ok   ' if ok else 'FAIL ') + '%s (%s): %s' % (label, 'baseline ' + BASE_REF if BASELINE else 'working tree',
              ('ASan ' + m.group(1)) if m else (out or 'rc=%d' % r.returncode)))
    return fails


def main():
    work = tempfile.mkdtemp(prefix='rd0048-')
    plex = func(read(D + 'Plex.h'), 'Plex(int structureLength, POLE::Stream* stream')
    fails = build_run(work, 'plex', PLEX.replace('@@CTOR@@', plex),
                      [('h', 'Plex: lcb 0x7FFFFFFF over a 100-byte stream', 'cps=25'),
                       ('n', 'Plex: lcb 40 at fc 80, 20 bytes past the end (unchanged)', 'cps=10')], False)
    lfo = func(read(D + 'ListFormatOverrideTable.cpp'), 'ListFormatOverrideTable::ListFormatOverrideTable(')
    fails += build_run(work, 'lfo', LFO.replace('@@CTOR@@', lfo),
                       [('h', 'LFO table: count 0x10000000 in a 64-byte stream', 'lfos=3'),
                        ('n', 'LFO table: count 2 (unchanged)', 'lfos=2')], False)
    piece = func(read(D + 'PieceTable.cpp'), 'PieceTable::PieceTable (FileInformationBlock *fib')
    fails += build_run(work, 'piece', PIECE.replace('@@CTOR@@', piece),
                       [('h', 'PieceTable: lcbClx 0x7FFFFFFF over a 100-byte table stream', 'pieces=0'),
                        ('n', 'PieceTable: one piece (unchanged)', 'pieces=1')], True)
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
