#!/usr/bin/env python3
r"""
#2506 - "[PDF] White (light) image on the last slide turns black in OnlyOffice".

The reporter's PDF is not attached, so this is the one defect in our image path
that produces the symptom on a PDF we can build ourselves.

A JPEG 2000 image (/Filter /JPXDecode) may omit /ColorSpace; the reader must
then take it from the JPEG 2000 data.  Gfx::doImage asks the stream through
getImageParams, and our own JPX filter

    PdfFile/SrcReader/JPXStream2.cpp   JPXStream2::getImageParams

answered DeviceRGB for every image.  The decoded buffer of a grayscale JPX
holds one byte per pixel, so the reader consumed three per pixel: the first
third of the picture came out as coloured stripes and the rest of the lines
were never filled - black under an /SMask (the mask supplies the alpha), fully
transparent without one.  Run through the real x2t (pdf -> png) a light-grey
64x48 grayscale JP2 with a soft mask rendered black from a third of the way
down; poppler renders it light grey.  With /ColorSpace /DeviceGray written out,
or with an RGB JP2, the same image was already right.

The fix asks xpdf's own JPXStream header parser (colr box of a JP2, or the
component count in the SIZ marker of a bare codestream) for the colour space,
keeping DeviceRGB as the fallback.

This test extracts the REAL JPXStream2::getImageParams and the REAL xpdf
JPXStream header readers (getImageParams, getImageParams2, readBoxHdr,
readMarkerHdr, readU*/readByte) by brace matching, runs them over the headers
of JPEG 2000 files made by opj_compress (embedded below), and checks the
colour space they report.

  RD_REPO=<core checkout>   default ../../core relative to this file
  BASELINE=1                read sources via `git show $BASE_REF:<path>`; must FAIL

NOT claimed: that the reporter's map is a grayscale JPX (their file is not
available; they guessed indexed + soft mask, and indexed images with soft masks
render the same as poppler in x2t for every variant tried: 1/2/4/8 bpc, small/
large/1-/4-bit masks, Matte, Decode, RGB/Gray/CMYK/Lab/ICC/stream-lookup bases).
Nothing here explains "Linux only"; the code path is the same on every platform.
"""
import os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', 'a1e8e1c060^')


def read(rel):
    if os.environ.get('BASELINE'):
        return subprocess.run(['git', '-C', CORE, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, text=True, check=True).stdout
    return open(os.path.join(CORE, rel), encoding='utf-8-sig').read()


def func(text, pattern):
    m = re.search(pattern, text, re.M)
    if not m:
        raise SystemExit('FAIL: %s not found' % pattern)
    depth, i = 0, text.index('{', m.start())
    for j in range(i, len(text)):
        depth += {'{': 1, '}': -1}.get(text[j], 0)
        if depth == 0:
            return text[m.start():j + 1]
    raise SystemExit('unbalanced braces')


jpx2 = read('PdfFile/SrcReader/JPXStream2.cpp')
jpx = read('PdfFile/lib/xpdf/JPXStream.cc')
jpxh = read('PdfFile/lib/xpdf/JPXStream.h')

parts = [func(jpxh, r'^enum JPXColorSpaceType \{')[:] + ';']
for name in ['getImageParams', 'getImageParams2']:
    parts.append(func(jpx, r'^void JPXStream::%s\(' % name))
for name in ['readBoxHdr', 'readUByte', 'readByte', 'readUWord', 'readULong']:
    parts.append(func(jpx, r'^GBool JPXStream::%s\(' % name))
parts.append(func(jpx, r'^int JPXStream::readMarkerHdr\('))
parts.append(func(jpx2, r'^void JPXStream2::getImageParams\('))

prog = r'''
#include <cstdio>
#include <string>
typedef unsigned int Guint; typedef bool GBool;
#define gTrue true
#define gFalse false
#define cover(idx)
enum StreamColorSpaceMode { streamCSNone, streamCSDeviceGray, streamCSDeviceRGB, streamCSDeviceCMYK };
enum { errSyntaxError };
static void error(int, long long, const char*, ...) {}
struct Stream { std::string d; size_t p; Stream(const std::string& s) : d(s), p(0) {} Stream* copy() { return new Stream(d); } };
struct BufStream {
  Stream* s; BufStream(Stream* str, int) : s(str) {} ~BufStream() { delete s; }
  void reset() { s->p = 0; } void close() {}
  int getChar() { return s->p < s->d.size() ? (unsigned char)s->d[s->p++] : EOF; }
  int lookChar() { return s->p < s->d.size() ? (unsigned char)s->d[s->p] : EOF; }
  Guint discardChars(Guint n) { s->p += n; return n; }
};
class JPXStream {
public:
  JPXStream(Stream* str) : bufStr(new BufStream(str, 3)) {}
  ~JPXStream() { delete bufStr; }
  long long getPos() { return 0; }
  void getImageParams(int*, StreamColorSpaceMode*); void getImageParams2(int*, StreamColorSpaceMode*);
  GBool readBoxHdr(Guint*, Guint*, Guint*); int readMarkerHdr(int*, Guint*);
  GBool readUByte(Guint*); GBool readByte(int*); GBool readUWord(Guint*); GBool readULong(Guint*);
  BufStream* bufStr;
};
class JPXStream2 { public: Stream* str; JPXStream2(Stream* s) : str(s) {} ~JPXStream2() { delete str; }
  void getImageParams(int*, StreamColorSpaceMode*); };
PARTS
static std::string unhex(const char* h) { std::string s; for (; h[0] && h[1]; h += 2) { unsigned v; sscanf(h, "%2x", &v); s += (char)v; } return s; }
int main() {
  // headers (up to and including SIZ) of files written by opj_compress from a 64x48 PGM / PPM
  struct { const char* name; const char* hex; StreamColorSpaceMode want; } cases[] = {
    {"grayscale JP2 ", "0000000c6a5020200d0a870a00000014667479706a703220000000006a7032200000002d6a703268000000166968647200000030000000400001070700000000000f636f6c72010000000000110000035b6a703263ff4fff510029000000000040000000300000000000000000000000400000003000000000000000000001070101ff", streamCSDeviceGray},
    {"sRGB JP2      ", "0000000c6a5020200d0a870a00000014667479706a703220000000006a7032200000002d6a703268000000166968647200000030000000400003070700000000000f636f6c7201000000000010000004e06a703263ff4fff51002f00000000004000000030000000000000000000000040000000300000000000000000000307010107", streamCSDeviceRGB},
    {"gray codestream", "ff4fff510029000000000040000000300000000000000000000000400000003000000000000000000001070101ff", streamCSDeviceGray},
    {"RGB codestream", "ff4fff51002f00000000004000000030000000000000000000000040000000300000000000000000000307010107", streamCSDeviceRGB},
    {"not JPX        ", "00010203", streamCSDeviceRGB},
  };
  const char* names[] = {"None", "DeviceGray", "DeviceRGB", "DeviceCMYK"};
  int bad = 0;
  for (auto& c : cases) {
    JPXStream2 s(new Stream(unhex(c.hex)));
    int bits = 0; StreamColorSpaceMode cs = streamCSNone;
    s.getImageParams(&bits, &cs);
    bool ok = cs == c.want && bits == 8;
    printf("%s -> %s, %d bpc (expect %s) %s\n", c.name, names[cs], bits, names[c.want], ok ? "ok" : "WRONG");
    bad += !ok;
  }
  return bad ? 1 : 0;
}
'''.replace('PARTS', '\n'.join(parts))

with tempfile.TemporaryDirectory() as t:
    c, exe = os.path.join(t, 't.cpp'), os.path.join(t, 't')
    open(c, 'w').write(prog)
    r = subprocess.run(['c++', '-std=c++11', '-w', c, '-o', exe], capture_output=True, text=True)
    if r.returncode:
        print(r.stderr[-3000:]); print('FAIL: does not build'); sys.exit(1)
    r = subprocess.run([exe], capture_output=True, text=True)
    print(r.stdout, end='')
    print('PASS' if r.returncode == 0 else 'FAIL'); sys.exit(r.returncode)
