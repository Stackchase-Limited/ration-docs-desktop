#!/usr/bin/env python3
"""
RD-0060 - compound files over ~7 MB listed sector 0 in their unused DIFAT slots (our finding).

core Common/cfcpp/compoundfile.cpp CompoundFile_impl::AllocateDIFATSectorChain writes
the FAT sector ids past the header's 109 into DIFAT sectors through a StreamView whose
new sectors are zero-filled, and wrote nothing after the last id. MS-CFB 2.5: unused
DIFAT entries MUST be FREESECT (0xFFFFFFFF). 0 is a valid sector number, so every
version-3 file with more than 109 FAT sectors (~7 MB) - in practice x2t's ECMA-376
encryption container for a large password-protected document - named sector 0 as a
FAT sector dozens of times (48 zero entries in a 12 MB password-protected xlsx saved
by the shipped x2t). A reader that walks DIFAT entries up to FREESECT instead of
counting csectFat would take the first data sector for part of the FAT.

Fix: fill the rest of the DIFAT chain after the last FAT id with FREESECT.

This compiles the REAL cfcpp sources (all of Common/cfcpp from RD_REPO, or from
BASE_REF with BASELINE=1) with a small driver and a stub for NSFile::CUtf8Converter
(ASCII paths only), writes a v3 and a v4 compound file holding one large stream, then
checks the file with an independent Python CFB parser: header, DIFAT chain, every
DIFAT entry after csectFat is FREESECT, every listed FAT sector is marked FATSECT, the
DIFAT sectors are DIFSECT, and the stream read through the FAT chain is byte-identical
to what was written.

Claimed: files written by cfcpp now carry FREESECT in unused DIFAT entries, and stay
readable (by the parser here). NOT claimed: that any particular third-
party reader (Excel, POI) rejected the old files - not tested here; x2t itself was not
rebuilt (the shipped x2t output above was measured by hand); re-saving an opened file
that already has a longer DIFAT chain is not exercised.

  python3 fork-fix-tests/rd-0060-cfb-difat-freesect/extract_and_run.py
  RD_REPO=<core checkout> (default ../../core)   BASELINE=1 -> must FAIL
"""
import os
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '88deda72e2^')
BASELINE = bool(os.environ.get('BASELINE'))
CFCPP = 'Common/cfcpp'
SOURCES = ['RBTree/rbtree.cpp', 'Stream/fstream_utils.cpp', 'Stream/stream_utils.cpp', 'cfitem.cpp',
           'cfstorage.cpp', 'cfstream.cpp', 'compoundfile.cpp', 'directoryentry.cpp', 'header.cpp',
           'sector.cpp', 'sectorcollection.cpp', 'streamrw.cpp', 'streamview.cpp']

DRIVER = r'''
#include "compoundfile.h"
#include "cfstream.h"
#include <vector>
#include <string>
#include <cstdio>
#include <cstdlib>
using namespace CFCPP;
static BYTE pattern(size_t i) { return (BYTE)((i * 2654435761u) >> 13); }
int main(int argc, char** argv)
{
    std::string mode = argv[1], path = argv[2];
    std::wstring wpath(path.begin(), path.end());
    size_t size = (size_t)atoll(argv[3]);
    if (mode == "write")
    {
        CompoundFile cf(atoi(argv[4]) == 4 ? Ver_4 : Ver_3, Default);
        auto st = cf.RootStorage()->AddStream(L"EncryptedPackage");
        std::vector<BYTE> data(size);
        for (size_t i = 0; i < size; ++i) data[i] = pattern(i);
        st->Write(data, 0);
        cf.Save(wpath);
        cf.Close();
        return 0;
    }
    return 2;
}
'''

STUB = r'''
namespace NSFile { class CUtf8Converter { public:
  static void GetUtf8StringFromUnicode(const wchar_t* p, long n, unsigned char*& out, long& outLen, bool bBOM);
}; }
void NSFile::CUtf8Converter::GetUtf8StringFromUnicode(const wchar_t* p, long n, unsigned char*& out, long& outLen, bool)
{ out = new unsigned char[n + 1]; for (long i = 0; i < n; ++i) out[i] = (unsigned char)p[i]; out[n] = 0; outLen = n; }
'''

FREESECT, ENDOFCHAIN, FATSECT, DIFSECT = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD, 0xFFFFFFFC


def expected(size):
    return bytes((((i * 2654435761) & 0xFFFFFFFFFFFFFFFF) >> 13) & 0xFF for i in range(size))


def check_cfb(path):
    """Independent parse; returns a list of problems."""
    d = open(path, 'rb').read()
    problems = []
    if d[:8] != bytes.fromhex('d0cf11e0a1b11ae1'):
        return ['bad signature']
    major, = struct.unpack_from('<H', d, 0x1A)
    shift, = struct.unpack_from('<H', d, 0x1E)
    nfat, firstdir, _, cutoff, _, _, firstdif, ndif = struct.unpack_from('<IIIIIIII', d, 0x2C)
    S = 1 << shift
    sec = lambda n: S + n * S
    difat = list(struct.unpack_from('<109I', d, 0x4C))
    difsecs = []
    s = firstdif
    while s not in (ENDOFCHAIN, FREESECT) and len(difsecs) <= ndif:
        difsecs.append(s)
        ent = struct.unpack_from('<%dI' % (S // 4), d, sec(s))
        difat += ent[:-1]
        s = ent[-1]
    if len(difsecs) != ndif:
        problems.append('DIFAT chain has %d sectors, header says %d' % (len(difsecs), ndif))
    unused = difat[nfat:]
    bad = sum(1 for x in unused if x != FREESECT)
    if bad:
        problems.append('%d unused DIFAT entries are not FREESECT (e.g. %s)' % (bad, hex([x for x in unused if x != FREESECT][0])))
    fatsecs = difat[:nfat]
    fat = []
    for f in fatsecs:
        if sec(f) + S > len(d):
            problems.append('FAT sector %d past EOF' % f)
            return problems
        fat += struct.unpack_from('<%dI' % (S // 4), d, sec(f))
    for f in fatsecs:
        if fat[f] != FATSECT:
            problems.append('FAT sector %d not marked FATSECT' % f)
    for f in difsecs:
        if fat[f] != DIFSECT:
            problems.append('DIFAT sector %d not marked DIFSECT' % f)

    def chain(start):
        out = []
        while start < 0xFFFFFFFA and len(out) <= len(fat):
            out.append(start)
            start = fat[start]
        return out
    raw = b''.join(d[sec(x):sec(x) + S] for x in chain(firstdir))
    for i in range(len(raw) // 128):
        e = raw[i * 128:(i + 1) * 128]
        nl, = struct.unpack_from('<H', e, 64)
        if nl and e[66] == 2:
            start, size = struct.unpack_from('<IQ', e, 116)
            if major == 3:
                size &= 0xFFFFFFFF
            c = chain(start)
            if size >= cutoff and len(c) != (size + S - 1) // S:
                problems.append('stream chain length wrong')
            elif size >= cutoff:
                got = b''.join(d[sec(x):sec(x) + S] for x in c)[:size]
                if got != expected(size):
                    problems.append('stream content read through the FAT differs')
    return problems


def main():
    if not shutil.which('clang++'):
        print('CANNOT RUN: clang++ not found')
        return 2
    tmp = tempfile.mkdtemp(prefix='rd0060-')
    try:
        incroot = os.path.join(tmp, 'root')
        src = os.path.join(incroot, 'Common', 'cfcpp')
        files = subprocess.run(['git', '-C', REPO, 'ls-tree', '-r', '--name-only', 'HEAD', CFCPP],
                               capture_output=True, text=True, check=True).stdout.split()
        for f in files:
            if '/test/' in f:
                continue
            dst = os.path.join(src, os.path.relpath(f, CFCPP))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if BASELINE:
                data = subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, f)],
                                      capture_output=True, check=True).stdout
            else:
                data = open(os.path.join(REPO, f), 'rb').read()
            open(dst, 'wb').write(data)
        # cfcpp includes ../../../OOXML/Base/Types_32.h and DesktopEditor/common/Types.h (read only)
        for inc in ('OOXML/Base', 'DesktopEditor/common'):
            os.makedirs(os.path.join(incroot, os.path.dirname(inc)), exist_ok=True)
            os.symlink(os.path.join(REPO, inc), os.path.join(incroot, inc))
        cdir = src
        open(os.path.join(tmp, 'drv.cpp'), 'w').write(DRIVER)
        open(os.path.join(tmp, 'stub.cpp'), 'w').write(STUB)
        exe = os.path.join(tmp, 'drv')
        cmd = ['clang++', '-std=c++14', '-O1', '-w', '-I' + cdir, os.path.join(tmp, 'drv.cpp'),
               os.path.join(tmp, 'stub.cpp')] + [os.path.join(cdir, s) for s in SOURCES] + ['-o', exe]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            print(r.stderr[-2000:])
            print('CANNOT RUN: compile failed')
            return 2
        failed = 0
        for version, size in ((3, 12000000), (3, 70000000), (4, 12000000), (3, 100000)):
            out = os.path.join(tmp, 'v%d-%d.cfb' % (version, size))
            subprocess.run([exe, 'write', out, str(size), str(version)], check=True)
            problems = check_cfb(out)
            print('%s v%d %9d bytes: %s' % ('ok  ' if not problems else 'FAIL', version, size,
                                            '; '.join(problems) if problems else 'conforms, content intact'))
            failed += bool(problems)
        if failed:
            print('FAIL RD-0060: %d file(s) do not conform%s' % (failed, ' (baseline, as expected)' if BASELINE else ''))
            return 1
        print('PASS RD-0060: unused DIFAT entries are FREESECT' + (' (BASELINE?!)' if BASELINE else ''))
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
