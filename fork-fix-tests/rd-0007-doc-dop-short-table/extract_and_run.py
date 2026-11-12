#!/usr/bin/env python3
"""
RD-0007 (our corpus run, no upstream issue): opening a .doc whose document
properties (DOP) run past the end of the table stream read up to ~700 bytes past
a heap buffer.

Found with an AddressSanitizer x2t on the POI and LibreOffice .doc test files
(31 of them, e.g. POI 52117.doc, Bug60936.doc, Bug60942b.doc): heap-buffer-
overflow READ in WordDocumentProperties::WordDocumentProperties
(MsBinaryFile/DocFile/DocumentProperties.cpp), on a buffer as small as 1 byte.

Cause: the constructor reads lcbDop bytes at fcDop with
VirtualStreamReader::ReadBytes(size, true). ReadBytes clips the count at the end
of the stream and allocates only what is left, but the constructor kept using
the FIB's lcbDop (`size`) for every "size > N" bound (83 ... 690) before
reading the bytes at those offsets. Files that truncate or misplace the DOP
(common in the wild, and every save by some third-party writers) therefore
read heap memory past the buffer; a release build turns that garbage into
document settings or crashes. Fix: after ReadBytes, `size` is set to the number
of bytes actually read (the reader's position delta), so the existing bounds
apply to the real buffer.

What runs: the REAL DocumentProperties.cpp, VirtualStreamReader.cpp,
DateAndTime/AutoSummaryInfo/DrawingObjectGrid/DocumentTypographyInfo.cpp,
OOXML/Base/unicode_util.cpp and the vendored POLE
(Common/3dParty/pole) are compiled with -fsanitize=address (DocumentProperties.cpp
via git show BASE_REF with BASELINE=1). The driver writes a compound file with
POLE whose "1Table" stream is 16 bytes long, reopens it, and builds
WordDocumentProperties with a FIB (Word 97+) that puts the DOP at offset 15 with
lcbDop 700 - one byte is really there. Two NSFile UTF-8 helpers (kernel library; POLE's file name is ASCII) and
FormatUtils::GetWStringFromBytes (UnicodeConverter, not reached) are stubbed. Passes when ASan reports nothing.

NOT claimed: the other readers of the .doc (style sheet, FKPs) are separate
findings; only the DOP is covered.

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read DocumentProperties.cpp at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0007 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', 'c02a029ed8^')
BASELINE = bool(os.environ.get('BASELINE'))
ASAN = ['-fsanitize=address', '-fno-omit-frame-pointer', '-g', '-w', '-std=gnu++11',
        '-DLINUX', '-D_LINUX', '-DMAC', '-D_MAC']
UNITS = ['MsBinaryFile/DocFile/VirtualStreamReader.cpp', 'MsBinaryFile/DocFile/DateAndTime.cpp',
         'MsBinaryFile/DocFile/AutoSummaryInfo.cpp', 'MsBinaryFile/DocFile/DrawingObjectGrid.cpp',
         'MsBinaryFile/DocFile/DocumentTypographyInfo.cpp',
         'OOXML/Base/unicode_util.cpp', 'Common/3dParty/pole/pole.cpp']
TESTED = 'MsBinaryFile/DocFile/DocumentProperties.cpp'


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig', 'replace')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig', errors='replace').read()


DRIVER = r'''
#include <cstdio>
#include <cstring>
#include <new>
#include "DocumentProperties.h"
#include "../../DesktopEditor/common/File.h"
/* kernel (NSFile) helpers: POLE turns its file name to UTF-8 with the second one (ASCII here) */
std::wstring NSFile::CUtf8Converter::GetWStringFromUTF16(const unsigned short*, LONG) { return L""; }
std::string NSFile::CUtf8Converter::GetUtf8StringFromUnicode2(const wchar_t* p, LONG n, bool) { return std::string(p, p + n); }
/* FormatUtils.cpp needs the UnicodeConverter library; only this one is referenced, and not reached */
bool DocFileFormat::FormatUtils::GetWStringFromBytes(std::wstring&, unsigned char*, int, int) { return false; }
int main(int argc, char** argv) {
    std::wstring path = L"PATH";
    {
        POLE::Storage st(path.c_str());
        if (!st.open(true, true)) { printf("create failed\n"); return 2; }
        POLE::Stream s(&st, L"1Table", true, 16);
        unsigned char data[16]; memset(data, 0, sizeof(data));
        s.write(data, sizeof(data)); s.flush();
        st.close();
    }
    POLE::Storage st(path.c_str());
    if (!st.open()) { printf("reopen failed\n"); return 2; }
    POLE::Stream table(&st, L"1Table");
    printf("table=%llu\n", (unsigned long long)table.size());
    /* a FIB is only ever built from a stream; its parts are plain data */
    alignas(DocFileFormat::FileInformationBlock) static unsigned char raw[sizeof(DocFileFormat::FileInformationBlock)];
    memset(raw, 0, sizeof(raw));
    DocFileFormat::FileInformationBlock* fib = reinterpret_cast<DocFileFormat::FileInformationBlock*>(raw);
    fib->m_nWordVersion = 0;               /* Word 97 and later */
    fib->m_FibWord97.fcDop  = 15;          /* one byte left in the table stream ... */
    fib->m_FibWord97.lcbDop = 700;         /* ... the FIB promises 700 */
    DocFileFormat::WordDocumentProperties* dop = new DocFileFormat::WordDocumentProperties(fib, &table);
    printf("DOP OK\n");
    delete dop;
    return 0;
}
'''


def main():
    work = tempfile.mkdtemp(prefix='rd0007-')
    boost = os.path.join(REPO, 'Common', '3dParty', 'boost', 'build', 'mac_arm64', 'include')
    inc = ['-I' + boost, '-I' + os.path.join(REPO, 'MsBinaryFile', 'DocFile')]
    objs = []
    tested = os.path.join(work, 'DocumentProperties.cpp')
    # compiled from the DocFile directory so its relative includes resolve
    src = read(TESTED)
    open(tested, 'w').write('#line 1 "DocumentProperties.cpp"\n' + src.replace('#include "DocumentProperties.h"',
                            '#include "%s"' % os.path.join(REPO, 'MsBinaryFile', 'DocFile', 'DocumentProperties.h')))
    for u in [tested] + [os.path.join(REPO, x) for x in UNITS]:
        o = os.path.join(work, os.path.basename(u)[:-4] + '.o')
        r = subprocess.run(['c++', '-c'] + ASAN + inc + [u, '-o', o], capture_output=True, text=True,
                           cwd=os.path.dirname(u) if u != tested else os.path.join(REPO, 'MsBinaryFile', 'DocFile'))
        if r.returncode:
            sys.exit('compile failed (%s):\n%s' % (u, r.stderr[-2500:]))
        objs.append(o)
    drv = os.path.join(REPO, 'MsBinaryFile', 'DocFile')
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write(DRIVER.replace('PATH', os.path.join(work, 'dop.cfb')))
    exe = os.path.join(work, 'drv')
    r = subprocess.run(['c++'] + ASAN + inc + ['-I' + drv, p] + objs + ['-o', exe], capture_output=True, text=True, cwd=drv)
    if r.returncode:
        sys.exit('driver build failed:\n' + r.stderr[-3000:])
    r = subprocess.run([exe], capture_output=True, text=True, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
    out = r.stdout + r.stderr
    a = re.search(r'ERROR: AddressSanitizer: ([\w-]+)', out)
    ok = r.returncode == 0 and not a and 'DOP OK' in out and 'table=16' in out
    print(('ok   ' if ok else 'FAIL ') + 'DOP of 700 bytes at the last byte of a 16-byte table stream (%s): %s' % (
        'baseline ' + BASE_REF if BASELINE else 'working tree',
        ('ASan ' + a.group(1)) if a else ('DOP OK' if ok else out.strip()[-300:])))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
