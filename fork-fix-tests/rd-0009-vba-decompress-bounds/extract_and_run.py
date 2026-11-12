#!/usr/bin/env python3
"""
RD-0009 (our corpus run, no upstream issue): opening a macro-enabled document
(.docm/.xlsm/.pptm, or a .doc/.xls/.ppt with a VBA project) decompressed the VBA
module streams without checking the end of the input buffer.

Found with an AddressSanitizer x2t on POI's macro test files (SimpleMacro.docm,
45690.docm, 60158.docm and 8 more, also .xlsm): heap-buffer-overflow READ of
size 4 in CVbaFileStream::CVbaFileStream (MsBinaryFile/Common/Vba/VbaBinary.cpp).

Cause: the MS-OVBA decompressor in CVbaFileStream's constructor
- read every 2-byte chunk header and copy token as `*((_UINT32*)dataCur)`, i.e.
  4 bytes, so a token in the last 2-3 bytes of the stream read past the buffer
  (this is what every one of the corpus files hit: compressed containers
  normally end right after their last token);
- consumed flag bytes, literals and copy tokens of a compressed chunk while
  only checking `dataCur - data > 0`, never the end of the buffer, so a chunk
  that claims more data than the stream holds read on into the heap;
- memcpy'd a stored chunk of chunkSize bytes regardless of what was left;
- computed `dataSize - 2` on a size_t (a 1-byte container underflowed).
Fix: an end pointer for the input; headers and copy tokens are read as two
bytes (little-endian, as the old cast did on our targets) and only when two
bytes are left; the token loops also stop at the end; a stored chunk is clipped
to what is left; the outer loop guards dataSize > 2.

What runs: the REAL CVbaFileStream constructor and its helpers (the CHUNK_*
constants and extract()) are lifted out of VbaBinary.cpp by brace matching
(git show BASE_REF:... with BASELINE=1) and compiled with -fsanitize=address
against the real VbaBinary.h, the vendored POLE (Common/3dParty/pole) and
OOXML/Base/unicode_util.cpp; two NSFile UTF-8 helpers of the kernel library
are stubbed (POLE's file name is ASCII). The
driver writes a compound file with POLE holding a "Module1" stream: signature
byte 1, then a compressed chunk whose flag byte announces a copy token with only
one byte left after it; it reopens the file and constructs CVbaFileStream on the
stream. A second case feeds a normal compressed container ("Attribute VB_Name",
compressed as MS-OVBA's literal-only form) and checks the text comes back.
Passes when ASan reports nothing and the normal case decompresses intact.

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read VbaBinary.cpp at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0009 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', 'cb15bb25e9^')
BASELINE = bool(os.environ.get('BASELINE'))
FLAGS = ['-fsanitize=address', '-fno-omit-frame-pointer', '-g', '-w', '-std=gnu++11',
         '-DLINUX', '-D_LINUX', '-DMAC', '-D_MAC']


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
#include <string>
#include "VbaBinary.h"
#include "../../../DesktopEditor/common/File.h"
std::wstring NSFile::CUtf8Converter::GetWStringFromUTF16(const unsigned short*, LONG) { return L""; }
std::string NSFile::CUtf8Converter::GetUtf8StringFromUnicode2(const wchar_t* p, LONG n, bool) { return std::string(p, p + n); }
@@CONSTS@@
@@CTOR@@
CVbaFileStream::~CVbaFileStream() { arrChunks.clear(); }
static void put(const std::wstring& path, const unsigned char* d, size_t n) {
    POLE::Storage st(path.c_str());
    st.open(true, true);
    POLE::Stream s(&st, L"Module1", true, n);
    s.write((unsigned char*)d, n); s.flush(); st.close();
}
static size_t run(const std::wstring& path, std::string* out) {
    POLE::Storage st(path.c_str());
    if (!st.open()) { printf("reopen failed\n"); return (size_t)-1; }
    POLE::Stream s(&st, L"Module1");
    CVbaFileStream v(&s, 0);
    std::string got(v.arrChunks.begin(), v.arrChunks.end());
    if (out) *out = got;
    return got.size();
}
int main(int argc, char** argv) {
    std::string base(argv[1]);
    std::wstring p1(base.begin(), base.end()); p1 += L"/short.bin";
    std::wstring p2(base.begin(), base.end()); p2 += L"/normal.bin";
    /* signature, chunk header 0xBFFF (compressed, 4096 bytes), flag byte 0x01 (copy token first), 1 byte */
    const unsigned char shortc[] = { 0x01, 0xFF, 0xBF, 0x01, 0x41 };
    put(p1, shortc, sizeof(shortc));
    printf("SHORT=%zu\n", run(p1, NULL));
    /* "Attribute VB_Name" as literal-only compressed chunk: flag 0x00 before every 8 literals */
    const char* text = "Attribute VB_Name";
    std::string body;
    for (size_t i = 0; i < strlen(text); ++i) { if (i % 8 == 0) body.push_back('\0'); body.push_back(text[i]); }
    unsigned short hdr = 0xB000 | (unsigned short)(body.size() - 1);
    std::string c; c.push_back('\x01'); c.push_back((char)(hdr & 0xFF)); c.push_back((char)(hdr >> 8)); c += body;
    put(p2, (const unsigned char*)c.data(), c.size());
    std::string got; run(p2, &got);
    printf("NORMAL=[%s]\n", got.c_str());
    return 0;
}
'''


def main():
    work = tempfile.mkdtemp(prefix='rd0009-')
    vba = os.path.join(REPO, 'MsBinaryFile', 'Common', 'Vba')
    boost = os.path.join(REPO, 'Common', '3dParty', 'boost', 'build', 'mac_arm64', 'include')
    inc = ['-I' + vba, '-I' + boost]
    src = read('MsBinaryFile/Common/Vba/VbaBinary.cpp')
    a = src.find('const unsigned char VBASTREAM_SIGNATURE')
    b = src.find('CVbaFileStream::CVbaFileStream(')
    if a < 0 or b < 0 or b < a:
        sys.exit('VBA decompressor not found - the extractor needs updating')
    consts = src[a:b]
    ctor = block(src, 'CVbaFileStream::CVbaFileStream(')
    hdr = open(os.path.join(vba, 'VbaBinary.h')).read()
    if 'arrChunks' not in hdr:
        sys.exit('CVbaFileStream::arrChunks not in VbaBinary.h - the driver needs updating')
    p = os.path.join(work, 'drv.cpp')
    # arrChunks is private; the driver reads it back to check the output
    open(p, 'w').write('#define private public\n#define protected public\n' +
                       DRIVER.replace('@@CONSTS@@', consts).replace('@@CTOR@@', ctor))
    pole = os.path.join(REPO, 'Common', '3dParty', 'pole', 'pole.cpp')
    exe = os.path.join(work, 'drv')
    uni = os.path.join(REPO, 'OOXML', 'Base', 'unicode_util.cpp')
    r = subprocess.run(['c++'] + FLAGS + inc + [p, pole, uni, '-o', exe], capture_output=True, text=True, cwd=vba)
    if r.returncode:
        sys.exit('driver build failed:\n' + r.stderr[-3000:])
    r = subprocess.run([exe, work], capture_output=True, text=True, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
    out = r.stdout + r.stderr
    asan = re.search(r'ERROR: AddressSanitizer: ([\w-]+)', out)
    normal = 'NORMAL=[Attribute VB_Name]' in out
    ok = r.returncode == 0 and not asan and normal and 'SHORT=' in out
    print(('ok   ' if ok else 'FAIL ') + 'VBA container ending inside a copy token (%s): %s' % (
        'baseline ' + BASE_REF if BASELINE else 'working tree',
        ('ASan ' + asan.group(1)) if asan else ('decompressed, normal module intact' if ok else out.strip()[-300:])))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
