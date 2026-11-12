#!/usr/bin/env python3
"""
RD-0005 (our corpus run, no upstream issue): a broken MNG/PNG-like picture freed
the libmng decoder while libmng was still using it (heap-use-after-free, then a
double free when the CxImageMNG was destroyed).

Found with an AddressSanitizer x2t on POI's PPT test files (bug60345_*.ppt and a
clusterfuzz PPT): opening them stopped with heap-use-after-free READ in
mng_readdisplay (DesktopEditor/cximage/mng/libmng_hlapi.c), the block having
been freed by mng_cleanup called from mymngerror (CxImage/ximamng.cpp). The
picture blips reach CxImageMNG through CBgraFrame::OpenFile, so any document
with such a picture (PPT, DOC, DOCX, ...) can hit it.

Cause: CxImageMNG installs mymngerror as libmng's error callback, and that
callback ran mng_cleanup(&mng) - it freed the whole decoder state from inside
libmng's own error path. mng_process_error returns into mng_read_graphic /
mng_readdisplay, which go on to read the freed state; CxImageMNG::Decode then
calls mng_store_error(hmng, ...) and reads hmng->zErrortext on the dangling
handle, and ~CxImageMNG runs mng_cleanup(&hmng) on it again. Fix: the callback
only reports failure (MNG_FALSE, which is what mng_cleanup's MNG_NOERROR used
to be read as, so libmng still aborts the read with the error code); the
handle is released once, by ~CxImageMNG, as before.

What runs: the REAL libmng sources of core (DesktopEditor/cximage/mng/*.c) are
compiled with -fsanitize=address with the defines of graphics' raster.pri
(JNG left out, it needs libjpeg and is not involved), and the REAL mymngerror
is lifted out of ximamng.cpp (git show BASE_REF:... with BASELINE=1). A small
driver sets the same kind of callbacks CxImageMNG sets, reads a 3-chunk MNG
(MHDR, an IHDR with an invalid colour type, MEND) through mng_readdisplay and
then releases the handle as ~CxImageMNG does. Passes when ASan reports nothing
and mng_readdisplay returned an error code.

NOT claimed: CxImageMNG::Decode itself is not compiled (cximage pulls in the
whole graphics library); the driver mirrors its calls.

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read ximamng.cpp at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0005 commit
"""
import glob
import os
import re
import struct
import subprocess
import sys
import tempfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '87c5a74031^')
BASELINE = bool(os.environ.get('BASELINE'))
DEFS = ['-DMNG_NO_INCLUDE_JNG', '-DMNG_SUPPORT_DISPLAY', '-DMNG_SUPPORT_READ', '-DMNG_ACCESS_CHUNKS',
        '-DMNG_STORE_CHUNKS', '-DMNG_ERROR_TELLTALE']
ASAN = ['-fsanitize=address', '-fno-omit-frame-pointer', '-g', '-w']


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig', 'replace')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig', errors='replace').read()


DRIVER = r'''
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#include "libmng.h"
#include "libmng_data.h"
extern "C" {
#include "libmng_error.h"
}
MYMNGERROR
static std::vector<unsigned char> g; static size_t gpos = 0;
static mng_ptr ma(mng_size_t n) { return calloc(1, n); }
static void mf(mng_ptr p, mng_size_t) { free(p); }
static mng_bool op(mng_handle) { return MNG_TRUE; }
static mng_bool cl(mng_handle) { return MNG_TRUE; }
static mng_bool rd(mng_handle, mng_ptr buf, mng_uint32 len, mng_uint32p got) {
    size_t n = g.size() - gpos; if (n > len) n = len;
    memcpy(buf, g.data() + gpos, n); gpos += n; *got = (mng_uint32)n; return MNG_TRUE; }
static unsigned char canvas[1 << 16];
static mng_bool hdr(mng_handle, mng_uint32, mng_uint32) { return MNG_TRUE; }
static mng_ptr line(mng_handle, mng_uint32) { return canvas; }
static mng_bool refresh(mng_handle, mng_uint32, mng_uint32, mng_uint32, mng_uint32) { return MNG_TRUE; }
static mng_uint32 tick(mng_handle) { return 0; }
static mng_bool timer(mng_handle, mng_uint32) { return MNG_TRUE; }
int main(int argc, char** argv) {
    FILE* f = fopen(argv[1], "rb"); int c; while ((c = fgetc(f)) != EOF) g.push_back((unsigned char)c); fclose(f);
    /* CxImageMNG::Decode: mng_initialize, callbacks (SetCallbacks), mng_readdisplay */
    mng_handle hmng = mng_initialize(NULL, ma, mf, MNG_NULL);
    mng_set_storechunks(hmng, MNG_FALSE);
    mng_set_suspensionmode(hmng, MNG_FALSE);
    mng_setcb_openstream(hmng, op); mng_setcb_closestream(hmng, cl); mng_setcb_readdata(hmng, rd);
    mng_setcb_processheader(hmng, hdr); mng_setcb_getcanvasline(hmng, line); mng_setcb_refresh(hmng, refresh);
    mng_setcb_gettickcount(hmng, tick); mng_setcb_settimer(hmng, timer); mng_setcb_errorproc(hmng, mymngerror);
    mng_retcode r = mng_readdisplay(hmng);
    printf("readdisplay=%d\n", (int)r);
    if (r != MNG_NOERROR && r != MNG_NEEDTIMERWAIT)
        mng_store_error(hmng, r, 0, 0);          /* as Decode does before reading zErrortext */
    if (hmng) mng_cleanup(&hmng);               /* ~CxImageMNG */
    printf("DONE\n");
    return 0;
}
'''


def chunk(t, d):
    return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)


def main():
    work = tempfile.mkdtemp(prefix='rd0005-')
    mng = os.path.join(REPO, 'DesktopEditor', 'cximage', 'mng')
    inc = ['-I' + mng, '-I' + os.path.join(REPO, 'OfficeUtils', 'src')]
    objs = []
    for c in sorted(glob.glob(os.path.join(mng, '*.c'))):
        o = os.path.join(work, os.path.basename(c)[:-2] + '.o')
        r = subprocess.run(['cc', '-c'] + ASAN + DEFS + inc + [c, '-o', o], capture_output=True, text=True)
        if r.returncode:
            sys.exit('libmng compile failed (%s):\n%s' % (c, r.stderr[-2000:]))
        objs.append(o)
    src = read('DesktopEditor/cximage/CxImage/ximamng.cpp')
    m = re.search(r'static mng_bool mymngerror\s*\([^)]*\)\s*\{.*?\n\}', src, re.S)
    if not m:
        sys.exit('mymngerror not found in ximamng.cpp - the extractor needs updating')
    open(os.path.join(work, 'drv.cpp'), 'w').write(DRIVER.replace('MYMNGERROR', m.group(0)))
    exe = os.path.join(work, 'drv')
    r = subprocess.run(['c++'] + ASAN + DEFS + inc + [os.path.join(work, 'drv.cpp')] + objs + ['-lz', '-o', exe],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit('driver build failed:\n' + r.stderr[-3000:])
    # MHDR 1x1, then an IHDR with colour type 9 (invalid) -> MNG_INVALIDCOLORTYPE inside mng_read_graphic
    data = (b'\x8aMNG\r\n\x1a\n' + chunk(b'MHDR', struct.pack('>7I', 1, 1, 1, 0, 0, 0, 0)) +
            chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 9, 0, 0, 0)) + chunk(b'MEND', b''))
    pic = os.path.join(work, 'bad.mng')
    open(pic, 'wb').write(data)
    r = subprocess.run([exe, pic], capture_output=True, text=True, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
    out = r.stdout + r.stderr
    a = re.search(r'ERROR: AddressSanitizer: ([\w-]+)', out)
    rd = re.search(r'readdisplay=(-?\d+)', out)
    ok = r.returncode == 0 and not a and rd and int(rd.group(1)) != 0 and 'DONE' in out
    print(('ok   ' if ok else 'FAIL ') + 'MNG with an invalid IHDR through mymngerror (%s): %s' % (
        'baseline ' + BASE_REF if BASELINE else 'working tree',
        ('ASan ' + a.group(1)) if a else (rd.group(0) if rd else 'rc=%d' % r.returncode)))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
