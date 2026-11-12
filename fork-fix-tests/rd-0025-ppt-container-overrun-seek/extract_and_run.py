#!/usr/bin/env python3
"""
RD-0025 (our corpus run, no upstream issue): a .ppt container whose child
records overran its stated length sent the reader back towards the start of the
stream, where it parsed the same records again (nesting deeper each time) until
x2t was killed: LibreOffice's sd/qa/unit/data/ppt/pass/hang-4/-5/-6/-8/-9/-12.ppt
(7.7 KB each) ran the release x2t for over 60 s, up to 1.5 GB.

Cause: CRecordsContainer::ReadFromStream (MsBinaryFile/PptFile/Reader/
Records.cpp, both overloads) seeks to the end of the container when the children
do not add up to its length, but computed the target from a second
"LONG lPosition = 0;" declared inside that branch, shadowing the container's
start position - so it seeked to the absolute offset RecLen. Fix: the inner
declaration is removed; the seek goes to start + RecLen.

What runs: the REAL POLE::Stream overload of CRecordsContainer::ReadFromStream
and SRecordHeader::ReadFromStream(POLE::Stream*) (brace-matched; git show
BASE_REF:... with BASELINE=1) over an in-memory stream with stand-in
StreamUtils / CreateByType (every child is an atom that skips its length).
Cases: a 16-byte container at offset 100 whose child atom claims 20 bytes (the
reader must continue at 100 + 8 + 16 = 124, not at 16), and a container whose
children fit exactly (continues right after it, unchanged).

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read Records.cpp at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0025 commit
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', 'cccd6bc2e3^')
BASELINE = bool(os.environ.get('BASELINE'))
REL = 'MsBinaryFile/PptFile/Reader/Records.cpp'


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


DRIVER = r'''
#include <cstdio>
#include <cstring>
#include <vector>
typedef long LONG; typedef unsigned int UINT; typedef unsigned long ULONG;
#define FALSE false
namespace POLE { typedef unsigned long long uint64;
struct Stream { std::vector<unsigned char> d; uint64 pos;
    uint64 read(unsigned char* b, uint64 n) { uint64 k = 0; while (k < n && pos < d.size()) b[k++] = d[pos++]; return k; }
    uint64 tell() { return pos; } uint64 size() { return d.size(); } void seek(uint64 p) { pos = p; } }; }
namespace StreamUtils { void StreamPosition(LONG& p, POLE::Stream* s) { p = (LONG)s->tell(); }
                        void StreamSeek(LONG p, POLE::Stream* s) { s->seek((POLE::uint64)p); } }
namespace PPT {
struct SRecordHeader { unsigned char RecVersion; unsigned short RecInstance, RecType; UINT RecLen; bool bBadHeader;
    void Clear() { RecVersion = 0; RecInstance = RecType = 0; RecLen = 0; bBadHeader = false; }
    bool ReadFromStream(POLE::Stream* pStream); };
struct IRecord { virtual ~IRecord() {} virtual void ReadFromStream(SRecordHeader& h, POLE::Stream* s) { s->seek(s->tell() + h.RecLen); } };
struct CommonInfo {};
static IRecord* CreateByType(SRecordHeader&, CommonInfo*) { return new IRecord; }
struct CRecordsContainer { SRecordHeader m_oHeader; std::vector<IRecord*> m_arRecords; CommonInfo* m_pCommonInfo;
    void ReadFromStream(SRecordHeader & oHeader, POLE::Stream* pStream); };
@@HDR@@
@@CONT@@
}
using namespace PPT;
static void put(std::vector<unsigned char>& d, size_t at, unsigned short ver, unsigned short type, unsigned int len) {
    unsigned short rec = ver; memcpy(&d[at], &rec, 2); memcpy(&d[at + 2], &type, 2); memcpy(&d[at + 4], &len, 4); }
int main(int argc, char** argv) {
    POLE::Stream s; s.d.assign(300, 0); s.pos = 100;
    if (argv[1][0] == 'o') { put(s.d, 100, 15, 1000, 16); put(s.d, 108, 0, 1001, 20); }  /* child claims 20 of 16 */
    else                   { put(s.d, 100, 15, 1000, 16); put(s.d, 108, 0, 1001, 8); }   /* fits: 8 + 8 */
    SRecordHeader h; h.ReadFromStream(&s);
    CRecordsContainer c; c.m_pCommonInfo = 0; c.ReadFromStream(h, &s);
    printf("next=%llu records=%zu\n", s.tell(), c.m_arRecords.size());
    return 0;
}
'''

CASES = [('o', 'child record overruns its container', 'next=124 records=1'),
         ('f', 'children fit the container (unchanged)', 'next=124 records=1')]


def main():
    src = read(REL)
    hdr = func(src, 'bool SRecordHeader::ReadFromStream(POLE::Stream *pStream)')
    cont = func(src, 'void CRecordsContainer::ReadFromStream(SRecordHeader & oHeader, POLE::Stream* pStream)')
    work = tempfile.mkdtemp(prefix='rd0025-')
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write(DRIVER.replace('@@HDR@@', hdr).replace('@@CONT@@', cont))
    exe = os.path.join(work, 'drv')
    r = subprocess.run(['c++', '-std=gnu++11', '-w', p, '-o', exe], capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-3000:])
    fails = 0
    for arg, name, want in CASES:
        r = subprocess.run([exe, arg], capture_output=True, text=True, timeout=60)
        out = r.stdout.strip()
        ok = r.returncode == 0 and out == want
        fails += not ok
        print(('ok   ' if ok else 'FAIL ') + '%s (%s): %s' % (
            name, 'baseline ' + BASE_REF if BASELINE else 'working tree', out or 'rc=%d' % r.returncode))
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
