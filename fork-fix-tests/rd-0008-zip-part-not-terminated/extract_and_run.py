#!/usr/bin/env python3
"""
RD-0008 (our corpus run, no upstream issue): the format detector ran strstr()
over zip parts that were not NUL-terminated, reading past the heap buffer.

Found with an AddressSanitizer x2t on POI's 47950_lower.doc / 47950_upper.doc
(zip containers named .doc): heap-buffer-overflow READ in
COfficeFileFormatChecker::isXpsFile (Common/OfficeFileFormatChecker2.cpp) on the
buffer from ZLibZipUtils::get_file_in_archive (OfficeUtils/src/ZipUtilsCP.cpp).

Cause: get_file_in_archive allocates exactly the part's uncompressed size and
hands it out through COfficeUtils::LoadFileFromArchive. The format checker
treats these buffers as C strings - strstr() for "fixedrepresentation"/"/xps/"/
"/oxps/" in _rels/.rels (isXpsFile), the ODF mimetype lines
(isOpenOfficeFormatFile), "ofd:OFD" (isOFDFile), the HWPX version line - so
every probe of a zip part without those words read on past the end until it hit
a zero byte. Every zip-based document that is opened passes through some of
these probes. Fix: get_file_in_archive allocates one more byte and zeroes it
(nFileSize is unchanged), which makes all of those callers safe at once.

What runs: the REAL OfficeUtils (OfficeUtils.cpp, ZipBuffer.cpp, ZipUtilsCP.cpp,
the vendored minizip and zlib) and the kernel files it needs
(DesktopEditor/common/File.cpp, Directory.cpp, Path.cpp, Base64.cpp) are
compiled with -fsanitize=address (ZipUtilsCP.cpp via git show BASE_REF with
BASELINE=1). The REAL COfficeFileFormatChecker::isXpsFile is lifted out of
OfficeFileFormatChecker2.cpp by brace matching and compiled against the real
OfficeFileFormatChecker.h. It is run on a zip (made here with Python's zipfile)
whose _rels/.rels is an ordinary OOXML relationship part. Passes when ASan
reports nothing and the file is not taken for XPS.

NOT claimed: the other strstr callers are covered by the same allocation
change but are not run one by one.

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read ZipUtilsCP.cpp at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0008 commit
"""
import os
import re
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', 'd2bc0bbcf9^')
BASELINE = bool(os.environ.get('BASELINE'))
FLAGS = ['-fsanitize=address', '-fno-omit-frame-pointer', '-g', '-w', '-DLINUX', '-D_LINUX', '-DMAC', '-D_MAC']


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig', 'replace')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig', errors='replace').read()


def block(text, start):
    a = text.find(start)
    if a < 0:
        sys.exit('%r not found - the extractor needs updating' % start)
    b = text.find('{', a)
    depth = 0
    for i in range(b, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[a:i + 1]
    sys.exit('unbalanced braces after %r' % start)


DRIVER = r'''
#include <cstdio>
#include <cstring>
#include "Common/OfficeFileFormatChecker.h"
#include "OfficeUtils/src/OfficeUtils.h"
@@ISXPS@@
int main(int argc, char** argv) {
    std::string a(argv[1]);
    std::wstring path(a.begin(), a.end());
    COfficeFileFormatChecker checker;
    bool xps = checker.isXpsFile(path);
    printf("XPS=%d\n", (int)xps);
    return 0;
}
'''

RELS = (b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        b'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
        b'officeDocument" Target="word/document.xml"/></Relationships>')


def main():
    work = tempfile.mkdtemp(prefix='rd0008-')
    s = os.path.join(REPO, 'OfficeUtils', 'src')
    z = os.path.join(s, 'zlib-1.2.11')
    mz = os.path.join(z, 'contrib', 'minizip')
    inc = ['-I' + s, '-I' + z, '-I' + mz, '-I' + REPO]
    zu = os.path.join(work, 'ZipUtilsCP.cpp')
    open(zu, 'w').write(read('OfficeUtils/src/ZipUtilsCP.cpp'))
    units = [(zu, s)]
    units += [(os.path.join(s, f), s) for f in ('OfficeUtils.cpp', 'ZipBuffer.cpp')]
    units += [(os.path.join(REPO, 'DesktopEditor', 'common', f), None) for f in
              ('File.cpp', 'Directory.cpp', 'Path.cpp', 'Base64.cpp')]
    units += [(os.path.join(mz, f), None) for f in ('unzip.c', 'zip.c', 'ioapi.c', 'ioapibuf.c')]
    units += [(os.path.join(s, 'zlib_addon.c'), None)]
    units += [(os.path.join(z, f), None) for f in ('adler32.c', 'crc32.c', 'inflate.c', 'inffast.c', 'inftrees.c',
                                                  'zutil.c', 'deflate.c', 'trees.c', 'compress.c', 'uncompr.c')]
    objs = []
    for n, (u, extra) in enumerate(units):
        o = os.path.join(work, '%02d_%s.o' % (n, os.path.basename(u).split('.')[0]))
        cc = ['c++', '-std=gnu++11'] if u.endswith('.cpp') else ['cc']
        r = subprocess.run(cc + ['-c'] + FLAGS + inc + ([] if extra is None else ['-I' + extra]) + [u, '-o', o],
                           capture_output=True, text=True)
        if r.returncode:
            sys.exit('compile failed (%s):\n%s' % (u, r.stderr[-2500:]))
        objs.append(o)
    chk = read('Common/OfficeFileFormatChecker2.cpp')
    fn = block(chk, 'bool COfficeFileFormatChecker::isXpsFile(')
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write(DRIVER.replace('@@ISXPS@@', fn))
    exe = os.path.join(work, 'drv')
    r = subprocess.run(['c++', '-std=gnu++11'] + FLAGS + inc + [p] + objs + ['-o', exe], capture_output=True, text=True)
    if r.returncode:
        sys.exit('driver build failed:\n' + r.stderr[-3000:])
    doc = os.path.join(work, 'plain.docx')
    with zipfile.ZipFile(doc, 'w') as zf:
        zf.writestr('_rels/.rels', RELS)
        zf.writestr('word/document.xml', b'<w:document/>')
    r = subprocess.run([exe, doc], capture_output=True, text=True, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
    out = r.stdout + r.stderr
    a = re.search(r'ERROR: AddressSanitizer: ([\w-]+)', out)
    x = re.search(r'XPS=(\d)', out)
    ok = r.returncode == 0 and not a and x and x.group(1) == '0'
    print(('ok   ' if ok else 'FAIL ') + 'isXpsFile on an OOXML zip (%s): %s' % (
        'baseline ' + BASE_REF if BASELINE else 'working tree',
        ('ASan ' + a.group(1)) if a else (x.group(0) if x else out.strip()[-300:])))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
