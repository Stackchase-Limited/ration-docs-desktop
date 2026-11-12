#!/usr/bin/env python3
"""
RD-0010 (our corpus run, no upstream issue): a .doc style whose UPX (property
exception) length points past the style's bytes copied kilobytes of heap memory
into the style.

Found with an AddressSanitizer x2t on 5 .doc files of the POI and LibreOffice
corpora (e.g. POI clusterfuzz-testcase-minimized-POIHWPFFuzzer-6610789829836800.doc,
which also SEGVs a release x2t): heap-buffer-overflow READ of size 27727 in
StyleSheetDescription::StyleSheetDescription
(MsBinaryFile/DocFile/StyleSheetDescription.cpp) on a 64-byte STD.

Cause: the constructor parses the variable part of an STD from `bytes`/`size`
without bounds: bytes[cbStdBase] (name length), a memcpy of the name, and for
every UPX a memcpy of cbUPX bytes from bytes + upxOffset + 2, cbUPX coming from
the file. A cbUPX larger than what is left of the STD copied that much heap
memory into the style (and on to the PAPX/CHPX parsers). In addition
StyleSheet::StyleSheet passed the STD's cbStd as the size, although
VirtualStreamReader::ReadBytes returns fewer bytes when the table stream ends
early (the same pattern as RD-0007). Fix: the name length is clipped to the
bytes present, the UPX loop stops when the length field or the UPX body would
run past `size`, and StyleSheet passes the number of bytes actually read.

What runs: the REAL StyleSheetDescription.cpp (git show BASE_REF with
BASELINE=1) compiled with -fsanitize=address against the real headers; the
constructors of the PAPX/CHPX/TAPX parsers are left unresolved (linked with
-undefined dynamic_lookup; the case never reaches them on the fixed code, and on
the old code ASan stops at the memcpy before them); FormatUtils::GetWStringFromBytes
and NSFile's UTF-16 helper are stubbed. A 16-byte
paragraph-style STD (cbStdBase 10, one UPX, empty name) whose UPX claims 4096
bytes is parsed. Passes when ASan reports nothing.

NOT claimed: the StyleSheet.cpp half (size = bytes read) is not run here; it
needs the whole FIB/table-stream setup and follows RD-0007's pattern.

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read StyleSheetDescription.cpp at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0010 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '2582055add^')
BASELINE = bool(os.environ.get('BASELINE'))
FLAGS = ['-fsanitize=address', '-fno-omit-frame-pointer', '-g', '-w', '-std=gnu++11',
         '-DLINUX', '-D_LINUX', '-DMAC', '-D_MAC']


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig', 'replace')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig', errors='replace').read()


DRIVER = r'''
#include <cstdio>
#include "StyleSheetDescription.h"
#include "../../DesktopEditor/common/File.h"
using namespace DocFileFormat;
/* name decoders; the PAPX/CHPX/TAPX parsers are left unresolved (dynamic lookup): never called here */
bool FormatUtils::GetWStringFromBytes(std::wstring&, unsigned char*, int, int) { return false; }
std::wstring NSFile::CUtf8Converter::GetWStringFromUTF16(const unsigned short*, LONG) { return L""; }
int main() {
    /* STD base (cbStdBase 10): stk = paragraph style (bits 16..19), cupx = 1 (bits 32..35);
       name: 0 characters; UPX at offset 14 (even border after 10 + 1 + 0 + 2) claims 0x1000 bytes */
    unsigned char* std = new unsigned char[16];
    const unsigned char d[16] = { 0,0, 0x01,0, 0x01,0, 0,0, 0,0, 0, 0,0, 0, 0x00,0x10 };
    for (int i = 0; i < 16; ++i) std[i] = d[i];
    StyleSheetDescription* s = new StyleSheetDescription(std, 16, 10, NULL, 0);
    printf("STD OK stk=%d cupx=%d\n", (int)s->stk, (int)s->cupx);
    delete[] std;
    return 0;
}
'''


def main():
    work = tempfile.mkdtemp(prefix='rd0010-')
    d = os.path.join(REPO, 'MsBinaryFile', 'DocFile')
    boost = os.path.join(REPO, 'Common', '3dParty', 'boost', 'build', 'mac_arm64', 'include')
    inc = ['-I' + d, '-I' + boost]
    src = os.path.join(work, 'StyleSheetDescription.cpp')
    open(src, 'w').write(read('MsBinaryFile/DocFile/StyleSheetDescription.cpp'))
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write('#define private public\n#define protected public\n' + DRIVER)
    exe = os.path.join(work, 'drv')
    r = subprocess.run(['c++'] + FLAGS + inc + [src, p, '-Wl,-undefined,dynamic_lookup', '-o', exe], capture_output=True, text=True, cwd=d)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-3000:])
    r = subprocess.run([exe], capture_output=True, text=True, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
    out = r.stdout + r.stderr
    a = re.search(r'ERROR: AddressSanitizer: ([\w-]+)', out)
    ok = r.returncode == 0 and not a and 'STD OK stk=1 cupx=1' in out
    print(('ok   ' if ok else 'FAIL ') + 'paragraph STD whose UPX claims 4096 of 16 bytes (%s): %s' % (
        'baseline ' + BASE_REF if BASELINE else 'working tree',
        ('ASan ' + a.group(1)) if a else ('parsed, UPX skipped' if ok else out.strip()[-300:])))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
