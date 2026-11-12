#!/usr/bin/env python3
"""
#572 - "Pdf Quality". Exporting to PDF decoded many JPEG pictures and compressed
them again at quality 85, while a JPEG without metadata was embedded byte for byte.

PdfWriter::CImageDict::LoadJpeg (core/PdfFile/SrcWriter/Image.cpp) embeds the file
as a DCTDecode stream unless NSImageReSaver::CorrectImage returns a re-encoded
buffer. CorrectImage decided by searching the first 10000 bytes for "Adobe",
"Photoshop" or "photoshop" - names found in Photoshop's APP13 block and in nearly
every XMP packet ("Adobe XMP Core"), i.e. in photos from Photoshop, Lightroom,
macOS Preview/sips and many cameras. With the shipped x2t, docx -> PDF of a
1600x1600 q100 JPEG written by sips came out as a 641 KB q85 stream instead of its
own 1.4 MB.

Fix: CorrectImage walks the JPEG markers to the frame header and re-encodes only
what the image dictionary (DeviceRGB/DeviceGray) cannot describe: frames that have
neither 1 nor 3 components (CMYK/YCCK), or any file with an APP14 "Adobe" colour
transform segment. If no frame header is found, the old name search decides.

This extracts the real `namespace NSImageReSaver` block from Image.cpp by brace
matching, compiles it with clang++ against stubs for the file reader, the format
checker and CBgraFrame (whose Encode only records that a re-encode happened), and
feeds it JPEG headers built here.

Claimed: Photoshop-APP13 and XMP-carrying RGB/gray JPEGs (also with the frame header
past a 70 KB ICC segment) are no longer re-encoded; CMYK with or without an Adobe
marker, 3-component files with an Adobe marker, and unparseable files that name
Photoshop still are; plain JPEGs are untouched as before.
NOT claimed: image data is not decoded here (CBgraFrame is a stub). The end-to-end
check was a run of x2t with this PdfFile (docx -> PDF: the Photoshop-tagged JPEG
embedded byte-identical, CMYK still re-encoded), not part of this test. PNG and other
non-JPEG pictures are still converted to JPEG q85 by CPdfWriter::LoadImage - unchanged.

RD_REPO overrides the core checkout (default ../../core). BASELINE=1 reads Image.cpp
from git at BASE_REF and must FAIL there.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
REL = 'PdfFile/SrcWriter/Image.cpp'
# Pinned to the parent of the commit that landed this fix, never HEAD.
BASE_REF = os.environ.get('BASE_REF', 'eb2c12c2b7^')

if os.environ.get('BASELINE'):
    src = subprocess.run(['git', '-C', CORE, 'show', '%s:%s' % (BASE_REF, REL)],
                         capture_output=True, text=True, check=True).stdout
else:
    src = open(os.path.join(CORE, REL), encoding='utf-8-sig').read()


def block(text, start):
    ob = text.index('{', start)
    depth = 0
    for i in range(ob, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise SystemExit('unbalanced braces')


m = re.search(r'^namespace NSImageReSaver\b', src, re.M)
if not m:
    raise SystemExit('namespace NSImageReSaver not found')
resaver = block(src, m.start())

harness = r'''
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
typedef unsigned char BYTE;
typedef unsigned int DWORD;
#define RELEASEARRAYOBJECTS(p) { if (p) { delete[] p; p = NULL; } }
enum { _CXIMAGE_FORMAT_UNKNOWN = 0, _CXIMAGE_FORMAT_JPG = 3 };
static std::string narrow(const wchar_t* w) { std::string s; while (*w) s += (char)*w++; return s; }
class CImageFileFormatChecker {
public:
    int eFileType;
    CImageFileFormatChecker(const wchar_t* p) : eFileType(_CXIMAGE_FORMAT_UNKNOWN) {
        FILE* f = fopen(narrow(p).c_str(), "rb"); unsigned char b[2] = {0, 0};
        if (f) { if (fread(b, 1, 2, f) == 2 && b[0] == 0xFF && b[1] == 0xD8) eFileType = _CXIMAGE_FORMAT_JPG; fclose(f); }
    }
};
namespace NSFile {
class CFileBinary {
    FILE* m_f;
public:
    CFileBinary() : m_f(NULL) {}
    ~CFileBinary() { CloseFile(); }
    bool OpenFile(const std::wstring& p) { m_f = fopen(narrow(p.c_str()).c_str(), "rb"); return m_f != NULL; }
    long GetFileSize() { long c = ftell(m_f); fseek(m_f, 0, SEEK_END); long n = ftell(m_f); fseek(m_f, c, SEEK_SET); return n; }
    bool ReadFile(BYTE* d, DWORD n, DWORD& r) { r = (DWORD)fread(d, 1, n, m_f); return r == n; }
    void CloseFile() { if (m_f) fclose(m_f); m_f = NULL; }
};
}
static int g_encodes = 0;
class CBgraFrame {
public:
    bool OpenFile(const std::wstring&) { return true; }
    void SetJpegQuality(double) {}
    bool Encode(BYTE*& p, int& n, unsigned int) { ++g_encodes; p = (BYTE*)malloc(4); n = 4; return true; }
    int get_Width() { return 16; }
    int get_Height() { return 16; }
};
%s
int main(int argc, char** argv)
{
    std::wstring w; for (const char* c = argv[1]; *c; ++c) w += (wchar_t)*c;
    BYTE* buf = NULL; int n = 0; unsigned int uw = 0, uh = 0;
    NSImageReSaver::CorrectImage(w.c_str(), buf, n, uw, uh);
    printf("%%s\n", buf ? "reencoded" : "kept");
    if (buf) free(buf);
    return 0;
}
''' % resaver

tmp = tempfile.mkdtemp(prefix='rd572-')
cpp = os.path.join(tmp, 't.cpp')
exe = os.path.join(tmp, 't')
open(cpp, 'w', encoding='utf-8').write(harness)
cxx = os.environ.get('CXX', 'clang++')
r = subprocess.run([cxx, '-std=gnu++11', '-w', '-O0', cpp, '-o', exe], capture_output=True, text=True)
if r.returncode:
    sys.stderr.write(r.stderr[-4000:])
    raise SystemExit('compile failed')


# --- JPEG headers (the stubbed decoder never looks past them) ---------------------
def seg(marker, payload):
    return bytes([0xFF, marker]) + (len(payload) + 2).to_bytes(2, 'big') + payload

JFIF = seg(0xE0, b'JFIF\x00\x01\x01\x00\x00\x48\x00\x48\x00\x00')
APP13 = seg(0xED, b'Photoshop 3.0\x008BIM\x04\x04\x00\x00\x00\x00\x00\x00')
XMP = seg(0xE1, b'http://ns.adobe.com/xap/1.0/\x00<x:xmpmeta xmlns:x="adobe:ns:meta/" '
                b'x:xmptk="Adobe XMP Core 9.1-c001"></x:xmpmeta>')
ICC_BIG = seg(0xE2, b'ICC_PROFILE\x00\x01\x01' + b'\x00' * 65000) + \
          seg(0xE2, b'ICC_PROFILE\x00\x02\x02' + b'\x00' * 5000)

def adobe(transform):
    return seg(0xEE, b'Adobe\x00\x64\x00\x00\x00\x00' + bytes([transform]))

def sof(ncomp, marker=0xC0):
    comps = b''.join(bytes([i + 1, 0x11, 0]) for i in range(ncomp))
    return seg(marker, b'\x08\x00\x10\x00\x10' + bytes([ncomp]) + comps)

TAIL = seg(0xDA, b'\x01\x01\x00\x00\x3f\x00') + b'\x12\x34' * 32 + b'\xFF\xD9'

def jpeg(*parts):
    return b'\xFF\xD8' + b''.join(parts) + TAIL

CASES = [
    # name, data, expected
    ('plain JFIF RGB JPEG is embedded as is', jpeg(JFIF, sof(3)), 'kept'),
    ('RGB JPEG with Photoshop APP13 (Photoshop, macOS sips/Preview) is embedded as is',
     jpeg(JFIF, APP13, sof(3)), 'kept'),
    ('RGB JPEG with an XMP packet ("Adobe XMP Core") is embedded as is', jpeg(JFIF, XMP, sof(3)), 'kept'),
    ('progressive RGB JPEG with Photoshop APP13 is embedded as is', jpeg(APP13, sof(3, 0xC2)), 'kept'),
    ('grayscale JPEG with Photoshop APP13 is embedded as is', jpeg(APP13, sof(1)), 'kept'),
    ('frame header behind a 70 KB ICC profile, Photoshop APP13 in the first 10000 bytes: embedded as is',
     jpeg(APP13, ICC_BIG, sof(3)), 'kept'),
    ('CMYK JPEG with the Adobe APP14 marker is still re-encoded', jpeg(APP13, adobe(2), sof(4)), 'reencoded'),
    ('3-component JPEG with the Adobe APP14 marker is still re-encoded', jpeg(adobe(0), sof(3)), 'reencoded'),
    ('CMYK JPEG without any Adobe marker is re-encoded (DeviceRGB cannot describe it)',
     jpeg(JFIF, sof(4)), 'reencoded'),
    ('unparseable header naming Photoshop falls back to the name search (re-encoded)',
     b'\xFF\xD8' + b'Photoshop' + b'\x00' * 64, 'reencoded'),
]

print('#572 which JPEGs the PDF writer re-encodes  (%s)' %
      ('BASELINE %s' % BASE_REF if os.environ.get('BASELINE') else CORE))
fails = 0
for i, (name, data, want) in enumerate(CASES):
    p = os.path.join(tmp, 'c%d.jpg' % i)
    open(p, 'wb').write(data)
    got = subprocess.run([exe, p], capture_output=True, text=True, check=True).stdout.strip()
    ok = got == want
    fails += not ok
    print('%s  %s%s' % ('PASS' if ok else 'FAIL', name, '' if ok else '  (got %s)' % got))

print('%d passed, %d failed' % (len(CASES) - fails, fails))
sys.exit(1 if fails else 0)
