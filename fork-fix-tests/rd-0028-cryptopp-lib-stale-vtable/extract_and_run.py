#!/usr/bin/env python3
"""
RD-0028 (our corpus run, no upstream issue; a BUILD defect, no source change):
the libCryptoPPLib.a that x2t links was not rebuilt after CryptTransform.h
changed, so every CryptoAPI-encrypted .xls/.doc/.ppt crashed or failed in x2t.

Found on Apache POI's test-data/spreadsheet/35897-type4.xls (CryptoAPI RC4,
default password): the release x2t - the main tree's build and the 2026-11-05
payload alike - dies with SIGSEGV. With the right password,
test-data/document/password_password_cryptoapi.doc ("password") ran x2t past
1.5 GB and slideshow/cryptoapi-proc2356.ppt ("crypto") failed with error 91.
With libCryptoPPLib.a rebuilt from the same sources: 35897-type4.xls reports
"password required" (90) as it should, the .doc and .ppt convert (0).

Cause: core eb34e8e49c (fix bug #81411, cherry-picked 2026-10-27) added
"virtual ~Decryptor() {}" as the FIRST virtual of CRYPT::Decryptor in
OfficeCryptReader/source/CryptTransform.h. CryptTransform.cpp (ECMADecryptor) is
compiled into libCryptoPPLib.a (Common/3dParty/cryptopp/project), which
.rd-work/bin/corebuild.sh skips (-not -path '*/3dParty/*'); the main tree's copy
is from 2026-09-19. Its ECMADecryptor vtable still has the old layout
(destructor last), while the XLS/DOC/PPT readers, compiled against the new
header, call slot 6 for IsVerify() - which in the old layout is the deleting
destructor: GlobalsSubstream::loadContent deletes the decryptor and goes on to
use it (ASan: heap-use-after-free, freed and used in GlobalsSubstream.cpp
220/222).

What runs: a 6-line program, compiled with -fsanitize=address against the
CURRENT CryptTransform.h (RD_REPO), creates a CRYPT::ECMADecryptor through a
CRYPT::Decryptor* and calls IsVerify() and delete, linked against the library
under test:
  default     RD_LIB (default <RD_REPO>/build/lib/mac_arm64/libCryptoPPLib.a, i.e.
              what x2t links) - passes once the library is rebuilt;
  BASELINE=1  an ECMADecryptor compiled from CryptTransform.cpp/.h at BASE_REF
              (default eb34e8e49c^, the sources the stale library was built from) -
              must FAIL, showing the failure signature of a stale library.
Passes when IsVerify() returns false and ASan reports nothing.
NOT claimed: Windows/Linux builds (check that their libCryptoPPLib is rebuilt too).

  RD_REPO=<core checkout>   (default ../../core)
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', 'eb34e8e49c^')
BASELINE = bool(os.environ.get('BASELINE'))
LIB = os.environ.get('RD_LIB') or os.path.join(REPO, 'build', 'lib', 'mac_arm64', 'libCryptoPPLib.a')
LIBDIR = os.path.join(os.path.normpath(os.path.join(HERE, '..', '..', 'core')), 'build', 'lib', 'mac_arm64')

MAIN = r'''
#include <cstdio>
#include "CryptTransform.h"
extern "C" void ConvertUTF32toUTF16() {}   /* not reached: only the password code uses it */
int main() {
    CRYPT::Decryptor* d = new CRYPT::ECMADecryptor();
    bool v = d->IsVerify();                /* no password set yet: false */
    printf("IsVerify=%d\n", (int)v);
    delete d;
    return 0;
}
'''
FLAGS = ['-std=gnu++11', '-w', '-DMAC', '-D_MAC', '-DLINUX', '-D_LINUX', '-DCRYPTOPP_DISABLE_ASM', '-DDISABLE_TYPE_MISMATCH',
         '-D_LIBCPP_ENABLE_CXX17_REMOVED_UNARY_BINARY_FUNCTION']


def main():
    work = tempfile.mkdtemp(prefix='rd0028-')
    boost = os.path.join(REPO, 'Common', '3dParty', 'boost', 'build', 'mac_arm64', 'include')
    if not os.path.isdir(boost):
        boost = os.path.join(os.path.normpath(os.path.join(HERE, '..', '..', 'core')), 'Common', '3dParty', 'boost', 'build', 'mac_arm64', 'include')
    m = os.path.join(work, 'main.cpp'); open(m, 'w').write(MAIN)
    objs = []
    if BASELINE:
        # the sources the stale library was built from, compiled next to the repo's Common/OOXML/DesktopEditor
        src = os.path.join(work, 'OfficeCryptReader', 'source'); os.makedirs(src)
        for n in ('CryptTransform.cpp', 'CryptTransform.h'):
            data = subprocess.run(['git', '-C', REPO, 'show', '%s:OfficeCryptReader/source/%s' % (BASE_REF, n)],
                                  capture_output=True, check=True).stdout
            open(os.path.join(src, n), 'wb').write(data)
        for d in ('Common', 'OOXML', 'DesktopEditor'):
            os.symlink(os.path.join(REPO, d), os.path.join(work, d))
        o = os.path.join(work, 'old.o')
        r = subprocess.run(['c++', '-c'] + FLAGS + ['-fsanitize=address', '-I' + boost, os.path.join(src, 'CryptTransform.cpp'), '-o', o],
                           capture_output=True, text=True)
        if r.returncode:
            sys.exit('baseline object build failed:\n' + r.stderr[-3000:])
        objs = [o]
        # the library's own CryptTransform.o / ECMACryptFile.o must not be linked next to it: keep only crypto++ itself
        x = os.path.join(work, 'ar'); os.makedirs(x)
        subprocess.run(['ar', 'x', os.path.abspath(LIB)], cwd=x, check=True)
        keep = [n for n in sorted(os.listdir(x)) if n.endswith('.o') and n not in ('CryptTransform.o', 'ECMACryptFile.o')]
        lib = os.path.join(work, 'libcryptopp-only.a')
        subprocess.run(['ar', 'rcs', lib] + keep, cwd=x, check=True)
    else:
        lib = LIB
    exe = os.path.join(work, 'vt')
    r = subprocess.run(['c++'] + FLAGS + ['-fsanitize=address', '-g', '-I' + os.path.join(REPO, 'OfficeCryptReader', 'source'), '-I' + boost,
                        m] + objs + [lib, '-F' + LIBDIR, '-framework', 'kernel', '-Wl,-rpath,' + LIBDIR, '-o', exe],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-3000:])
    r = subprocess.run([exe], capture_output=True, text=True, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
    mm = re.search(r'ERROR: AddressSanitizer: ([\w-]+)', r.stderr)
    ok = r.returncode == 0 and not mm and r.stdout.strip() == 'IsVerify=0'
    print(('ok   ' if ok else 'FAIL ') + 'ECMADecryptor called through the current CRYPT::Decryptor (%s): %s' % (
        'baseline: ECMADecryptor from ' + BASE_REF if BASELINE else LIB,
        ('ASan ' + mm.group(1) + ' - IsVerify() ran the destructor') if mm else (r.stdout.strip() or 'rc=%d' % r.returncode)))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
