#!/usr/bin/env python3
"""
RD-0006 (our corpus run, no upstream issue): every picture that went through the
JasPer decoder (CxImageJAS - JPEG 2000, PNM, RAS, PGX and the probe CxImage does
for unrecognised pictures) closed its JasPer stream through function pointers
that lived in a stack object that had already gone out of scope.

Found with an AddressSanitizer x2t on POI's bug60345_paperfigures.ppt:
stack-use-after-scope in jas_stream_close called from CxImageJAS::Decode
(DesktopEditor/cximage/CxImage/ximajas.cpp). In a release build the stale stack
slot is usually still intact, but jas_matrix_destroy / jas_cleanup /
jas_image_destroy run in between and may overwrite it, after which the close
jumps through a garbage pointer.

Cause: Decode (and Encode) construct `CxFileJas src(hFile, in)` inside the
cx_try block. The CxFileJas constructor points stream->ops_ at its own member
jas_stream_CxFile; the stream is closed with jas_stream_close(in) after the
block, when `src` is already dead, and jas_stream_close calls
stream->ops_->close_. Fix: the CxFileJas is allocated before the block's scope
ends (a pointer declared next to `in`/`out`) and deleted after
jas_stream_close.

What runs: the REAL JasPer sources of core (cximage/jasper, the files listed in
graphics' raster.pri) compiled with -fsanitize=address; the REAL CxFileJas class
(ximajas.h) and the REAL CxImageJAS::Decode body (ximajas.cpp, git show
BASE_REF:... with BASELINE=1) are lifted out by brace matching and compiled
against a minimal stand-in for CxImage (info/head fields, Create/SetPixel*
no-ops) and CxFile (memory reader), with the cx_try/cx_throw macros of
ximadef.h for DISABLE_IMAGE_EXCEPTIONS (how graphics is built). Decode is fed
a few bytes no JasPer format recognises (the probe case, the most common one).
Passes when ASan reports nothing and Decode returns false.

NOT claimed: Encode gets the same change but is not exercised (x2t never
writes JPEG 2000 through CxImage).

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read ximajas.cpp/.h at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0006 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', 'aa7fbced56^')
BASELINE = bool(os.environ.get('BASELINE'))
ASAN = ['-fsanitize=address', '-fno-omit-frame-pointer', '-g', '-w']


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


PRELUDE = r'''
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include "jasper/jasper.h"
/* ximadef.h, DISABLE_IMAGE_EXCEPTIONS (CXIMAGE_SUPPORT_EXCEPTION_HANDLING 0) */
#define cx_try bool cx_error=false;
#define cx_throw(message) {cx_error=true; if(strcmp(message,"")) strncpy(info.szLastError,message,255); goto cx_error_catch;}
#define cx_catch cx_error_catch: char message[]=""; if(cx_error)
#define CXIMAGE_SUPPORT_JP2 1
#define CXIMAGE_SUPPORT_JPC 1
#define CXIMAGE_SUPPORT_PGX 1
#define CXIMAGE_SUPPORT_PNM 1
#define CXIMAGE_SUPPORT_RAS 1
enum { CXIMAGE_FORMAT_JP2 = 1, CXIMAGE_FORMAT_JPC, CXIMAGE_FORMAT_PGX, CXIMAGE_FORMAT_PNM, CXIMAGE_FORMAT_RAS };
struct RGBQUAD { uint8_t rgbBlue, rgbGreen, rgbRed, rgbReserved; };
class CxFile { public:
    const unsigned char* p; long n, pos;
    size_t Read(void* b, size_t s, size_t c) { long k = (long)(s * c); if (k > n - pos) k = n - pos; memcpy(b, p + pos, k); pos += k; return k; }
    size_t Write(const void*, size_t, size_t) { return 0; }
    bool Seek(long off, int o) { pos = (o == SEEK_SET ? 0 : o == SEEK_CUR ? pos : n) + off; return true; }
};
@@CXFILEJAS@@
class CxImageJAS { public:
    struct { char szLastError[256]; int32_t nEscape, nNumFrames, nFrame, nBkgndIndex; uint32_t dwType, dwEffWidth; RGBQUAD nBkgndColor; } info;
    struct { int32_t biWidth, biHeight; } head;
    CxImageJAS() { memset(&info, 0, sizeof(info)); memset(&head, 0, sizeof(head)); }
    bool Create(int32_t, int32_t, int32_t, int32_t) { return true; }
    void SetPixelColor(int32_t, int32_t, RGBQUAD) {}
    void SetPixelIndex(int32_t, int32_t, uint8_t) {}
    void SetGrayPalette() {}
    bool Decode(CxFile* hFile, uint32_t imagetype = 0);
};
@@DECODE@@
int main() {
    static const unsigned char junk[] = "this is not a picture any JasPer codec knows";
    CxFile f; f.p = junk; f.n = sizeof(junk); f.pos = 0;
    CxImageJAS img;
    bool ok = img.Decode(&f, 0);
    printf("DECODE=%d %s\n", (int)ok, img.info.szLastError);
    return 0;
}
'''


def main():
    work = tempfile.mkdtemp(prefix='rd0006-')
    d = os.path.join(REPO, 'DesktopEditor')
    pri = open(os.path.join(d, 'graphics', 'pro', 'raster.pri')).read()
    srcs = re.findall(r'cximage/jasper/[^\s\\]+\.c', pri)
    if not srcs:
        sys.exit('jasper sources not found in raster.pri')
    inc = ['-I' + os.path.join(d, 'cximage', 'jasper', 'include')]
    objs = []
    for s in srcs:
        o = os.path.join(work, os.path.basename(s)[:-2] + '.o')
        r = subprocess.run(['cc', '-c'] + ASAN + ['-DEXCLUDE_JPG_SUPPORT', '-DHAVE_UNISTD_H', '-DHAVE_FCNTL_H'] + inc +
                           [os.path.join(d, s), '-o', o], capture_output=True, text=True)
        if r.returncode:
            sys.exit('jasper compile failed (%s):\n%s' % (s, r.stderr[-2000:]))
        objs.append(o)
    h = read('DesktopEditor/cximage/CxImage/ximajas.h')
    c = read('DesktopEditor/cximage/CxImage/ximajas.cpp')
    cls = block(h, 'class CxFileJas') + ';'
    dec = block(c, 'bool CxImageJAS::Decode(CxFile *hFile')
    src = PRELUDE.replace('@@CXFILEJAS@@', cls).replace('@@DECODE@@', dec)
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write(src)
    exe = os.path.join(work, 'drv')
    r = subprocess.run(['c++', '-std=gnu++11'] + ASAN + inc + [p] + objs + ['-lm', '-o', exe], capture_output=True, text=True)
    if r.returncode:
        sys.exit('driver build failed:\n' + r.stderr[-3000:])
    r = subprocess.run([exe], capture_output=True, text=True, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
    out = r.stdout + r.stderr
    a = re.search(r'ERROR: AddressSanitizer: ([\w-]+)', out)
    dm = re.search(r'DECODE=(\d)', out)
    ok = r.returncode == 0 and not a and dm and dm.group(1) == '0'
    print(('ok   ' if ok else 'FAIL ') + 'CxImageJAS::Decode of an unknown picture (%s): %s' % (
        'baseline ' + BASE_REF if BASELINE else 'working tree',
        ('ASan ' + a.group(1)) if a else (dm.group(0) if dm else 'rc=%d' % r.returncode)))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
