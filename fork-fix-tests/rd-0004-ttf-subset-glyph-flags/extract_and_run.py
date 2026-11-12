#!/usr/bin/env python3
"""
RD-0004 (our corpus run, no upstream issue): every PDF export that embedded a
TrueType subset read one byte past the heap block of "used glyph" flags.

Found by running the POI/LibreOffice/Tika test corpora through an
AddressSanitizer x2t (Editor.bin -> PDF): ~1 in 3 documents stopped with
heap-buffer-overflow READ of size 1 in CFontFileTrueType::WriteTTF
(PdfFile/SrcWriter/FontTTWriter.cpp), called from CFontCidTrueType::BeforeWrite.

Cause: CFontCidTrueType::GetWidthsAndGids allocates pGlyphs with one flag per
glyph (m_nGlyphsCount == the font's numGlyphs). WriteTTF walks the 'loca'
table, which has numGlyphs + 1 entries (the last one only closes the final
glyph), with `for (i = 0; i <= m_nGlyphs; ++i)` and tested `pUseGlyfs[i]` for
every entry, so the closing entry read pUseGlyfs[numGlyphs]. A release build
reads a stray heap byte there (the entry has length 0, so the output did not
change); an ASan build aborts the export. Fix: only consult the flag for
i < m_nGlyphs.

What runs: the REAL FontTTWriter.cpp/.h from core (git show BASE_REF:... with
BASELINE=1) are compiled with -fsanitize=address next to a minimal stand-in for
Streams.h (a CStream that only counts bytes; WriteTTF only calls Write) and a
stand-in for DesktopEditor/common/File.h (only used by LoadFromFile, not
called). A real TrueType font from the core tree (FontAwesome.ttf in the
freetype docs) is loaded with CFontFileTrueType::LoadFromBuffer and
WriteTTF(stream, NULL, codeToGid, n, flags, numGlyphs) is called with a flags
block of exactly numGlyphs bytes, as CFontCidTrueType::BeforeWrite does.
Passes when ASan reports nothing and a font stream was produced.

NOT claimed: the subset font content is not validated here (the corpus PDFs
were compared by size only); CFontCidTrueType itself is not compiled.

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read the sources at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0004 commit
"""
import os
import re
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '9e859476ed^')
BASELINE = bool(os.environ.get('BASELINE'))
FONT = 'DesktopEditor/freetype-2.10.4/docs/reference/assets/fonts/specimen/FontAwesome.ttf'


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig').read()


def num_glyphs(data):
    n = struct.unpack('>H', data[4:6])[0]
    for k in range(n):
        tag, _, off, _ = struct.unpack('>4sIII', data[12 + 16 * k:28 + 16 * k])
        if tag == b'maxp':
            return struct.unpack('>H', data[off + 4:off + 6])[0]
    sys.exit('no maxp table in ' + FONT)


STREAMS_H = r'''
#ifndef RD_STUB_STREAMS_H
#define RD_STUB_STREAMS_H
#include <cstdlib>
#include <cstring>
#include <string>
typedef unsigned char BYTE;
typedef unsigned int DWORD;
namespace PdfWriter {
class CStream {
public:
    unsigned long long size = 0;
    void Write(const BYTE*, unsigned int n) { size += n; }
    void Write(BYTE* p, unsigned int n) { size += n; (void)p; }
};
}
#endif
'''

FILE_H = r'''
#pragma once
#include <string>
namespace NSFile { class CFileBinary { public:
    bool OpenFile(const std::wstring&) { return false; }
    int GetFileSize() { return 0; }
    bool ReadFile(BYTE*, DWORD, DWORD&) { return false; }
    void CloseFile() {}
}; }
'''

MAIN = r'''
#include <cstdio>
#include <cstdlib>
#include "FontTTWriter.h"
using namespace PdfWriter;
/* OpenType/CFF branch lives in FontOTWriter.cpp; never reached for a TrueType font */
void CFontFileTrueType::WriteCIDFontType0C(CStream*, unsigned short*, unsigned int) {}
int main(int argc, char** argv) {
    FILE* f = fopen(argv[1], "rb");
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    char* buf = (char*)malloc(n); if (fread(buf, 1, n, f) != (size_t)n) return 2; fclose(f);
    int nGlyphs = atoi(argv[2]);
    CFontFileTrueType* pTTF = CFontFileTrueType::LoadFromBuffer(buf, (int)n, 0);
    if (!pTTF) { printf("load failed\n"); return 2; }
    /* as CFontCidTrueType::GetWidthsAndGids: one flag per glyph, a few glyphs used */
    unsigned char* pGlyphs = new unsigned char[nGlyphs]();
    pGlyphs[0] = 1; pGlyphs[1] = 1; pGlyphs[nGlyphs - 1] = 1;
    unsigned short codeToGid[3] = { 0, 1, (unsigned short)(nGlyphs - 1) };
    CStream s;
    pTTF->WriteTTF(&s, NULL, codeToGid, 3, pGlyphs, nGlyphs);
    printf("WROTE %llu\n", s.size);
    delete[] pGlyphs; delete pTTF; free(buf);
    return 0;
}
'''


def main():
    font = os.path.join(REPO, FONT)
    data = open(font, 'rb').read()
    ng = num_glyphs(data)
    work = tempfile.mkdtemp(prefix='rd0004-')
    h = read('PdfFile/SrcWriter/FontTTWriter.h')
    c = read('PdfFile/SrcWriter/FontTTWriter.cpp')
    c2 = c.replace('#include "../../DesktopEditor/common/File.h"', '#include "File.h"')
    if c2 == c:
        sys.exit('File.h include not found - the extractor needs updating')
    for name, text in (('FontTTWriter.h', h), ('FontTTWriter.cpp', c2), ('Streams.h', STREAMS_H),
                       ('File.h', FILE_H), ('main.cpp', MAIN)):
        open(os.path.join(work, name), 'w').write(text)
    exe = os.path.join(work, 'ttw')
    cmd = ['c++', '-std=c++11', '-fsanitize=address', '-fno-omit-frame-pointer', '-g', '-w',
           '-include', 'Streams.h', '-I' + work, '-o', exe,
           os.path.join(work, 'FontTTWriter.cpp'), os.path.join(work, 'main.cpp')]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=work)
    if r.returncode:
        sys.exit('compile failed:\n' + r.stderr[-3000:])
    env = dict(os.environ, ASAN_OPTIONS='detect_leaks=0')
    r = subprocess.run([exe, font, str(ng)], capture_output=True, text=True, env=env)
    out = r.stdout + r.stderr
    m = re.search(r'ERROR: AddressSanitizer: ([\w-]+)', out)
    wrote = re.search(r'WROTE (\d+)', out)
    ok = r.returncode == 0 and not m and wrote and int(wrote.group(1)) > 0
    print(('ok   ' if ok else 'FAIL ') + 'WriteTTF with %d glyph flags (%s): %s' % (
        ng, 'baseline ' + BASE_REF if BASELINE else 'working tree',
        ('ASan ' + m.group(1)) if m else (wrote.group(0) if wrote else 'rc=%d' % r.returncode)))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
