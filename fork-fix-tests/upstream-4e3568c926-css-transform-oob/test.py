#!/usr/bin/env python3
"""
Upstream 4e3568c926 (ONLYOFFICE bug #82216), backported for 2026.3.1:
an SVG/CSS `transform` value without its closing bracket - transform="translate(10,20" -
crashed whatever read it. NSCSS::CMatrix::CutTransforms (Common/3dParty/html/css/src/
StyleProperties.cpp) built std::wstring(citBegin, citEnd + 1) with citEnd == end(), then set
citBegin past the end and kept scanning memory for the next letter until it faulted. Any SVG
reaches it: an .svg on its own, one embedded in a docx/pptx/xlsx, HTML/EPUB styles.
Fix (upstream): stop at an unterminated function.

What runs:
  1. ASan: the REAL CMatrix::CutTransforms, extracted by brace matching from StyleProperties.cpp
     (BASE_REF with BASELINE=1), compiled with -fsanitize=address and fed unterminated and
     well-formed transform lists. Passes when ASan is silent and the well-formed functions come
     back whole.
  2. End to end: a small driver linked against the REAL graphics/kernel frameworks loads SVGs
     carrying unterminated transforms with MetaFile::IMetaFile::LoadFromFile (the reader x2t
     and the editors use) and rasterises them. Passes when every load returns. The 2026.3.0
     frameworks die on SIGBUS/SIGSEGV here.

  RD_CORE=<core checkout>        sources/headers (default ../../core)
  RD_CORE_LIBS=<dir>             frameworks under test (default <core>/build/lib/mac_arm64)
  BASELINE=1                     read sources at BASE_REF and link RD_CORE_LIBS_BASE; must FAIL
  BASE_REF                       default aa16ec2c0d (v2026.3.0, before the backport)
  RD_CORE_LIBS_BASE              default .rd-work/mac-2026.3.0/payload/converter (v2026.3.0)
  RD_FONTS                       font cache (default .rd-work/fonts-cache; copied first)
Exit 77 (skip) when the frameworks or fonts are missing.
"""
import os
import shutil
import signal
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
CORE = os.environ.get('RD_CORE') or os.path.join(ROOT, 'core')
BASELINE = bool(os.environ.get('BASELINE'))
BASE_REF = os.environ.get('BASE_REF', 'aa16ec2c0d')
RDWORK = os.path.normpath(os.path.join(ROOT, '..', '.rd-work'))
LIBS = (os.environ.get('RD_CORE_LIBS_BASE') or os.path.join(RDWORK, 'mac-2026.3.0', 'payload', 'converter')) if BASELINE \
    else (os.environ.get('RD_CORE_LIBS') or os.path.join(CORE, 'build', 'lib', 'mac_arm64'))
FONTS = os.environ.get('RD_FONTS') or os.path.join(RDWORK, 'fonts-cache')
SRC = 'Common/3dParty/html/css/src/StyleProperties.cpp'

failures = []


def check(cond, what):
    print(('ok   ' if cond else 'FAIL ') + what)
    if not cond:
        failures.append(what)


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', CORE, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig', 'replace')
    return open(os.path.join(CORE, rel), encoding='utf-8-sig', errors='replace').read()


def block(src, start):
    a = src.find(start)
    if a < 0:
        return None
    i = src.find('{', a)
    depth = 0
    while True:
        if src[i] == '{':
            depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0:
                return src[a:i + 1]
        i += 1


DRIVER = r'''
#include <algorithm>
#include <cstdio>
#include <cwctype>
#include <string>
#include <vector>
struct CMatrix { std::vector<std::wstring> CutTransforms(const std::wstring &wsValue) const; };
@@FN@@
static std::string narrow(const std::wstring& s) { return std::string(s.begin(), s.end()); }
int main() {
  const wchar_t* inputs[] = {
    L"translate(10,20",                       // no ")" at all
    L"scale(2) rotate(45 50 50) translate(10", // last function unterminated
    L"matrix(1 0 0 1 10 20) skewx(30)",        // well formed
  };
  for (const wchar_t* in : inputs) {
    std::wstring v(in);
    v.reserve(v.size());            // heap buffer of exactly the string, so ASan sees the overrun
    std::vector<std::wstring> r = CMatrix().CutTransforms(v);
    printf("%s ->", narrow(v).c_str());
    for (const std::wstring& s : r) printf(" [%s]", narrow(s).c_str());
    printf("\n");
  }
  return 0;
}
'''

SVGDRV = r'''
#include <cstdio>
#include <cstring>
#include <string>
#include "DesktopEditor/graphics/pro/Fonts.h"
#include "DesktopEditor/graphics/pro/Image.h"
#include "DesktopEditor/common/File.h"
static std::wstring w(const char* s) { return NSFile::CUtf8Converter::GetUnicodeStringFromUTF8((BYTE*)s, (LONG)strlen(s)); }
int main(int argc, char** argv) {   // drv <fonts> <in.svg> <out.png>
  NSFonts::IApplicationFonts* app = NSFonts::NSApplication::Create();
  app->InitializeFromFolder(w(argv[1]));
  MetaFile::IMetaFile* mf = MetaFile::Create(app);
  bool ok = mf->LoadFromFile(w(argv[2]).c_str());
  if (ok) mf->ConvertToRaster(w(argv[3]).c_str(), 4, 64, 64);
  printf("loaded=%d\n", ok ? 1 : 0);
  return 0;
}
'''

SVGS = {
    'translate': '<rect x="10" y="10" width="50" height="50" fill="red" transform="translate(10,20"/>',
    'style': '<rect x="10" y="10" width="50" height="50" fill="red" style="transform: scale(2) rotate(45"/>',
    'group': '<g transform="matrix(1 0 0 1 5 5) translate(3"><circle cx="30" cy="30" r="20"/></g>',
}


def part_asan(work):
    fn = block(read(SRC), 'std::vector<std::wstring> CMatrix::CutTransforms(')
    if not fn:
        sys.exit('CMatrix::CutTransforms not found - the extractor needs updating')
    p = os.path.join(work, 'cut.cpp')
    open(p, 'w').write(DRIVER.replace('@@FN@@', fn))
    exe = os.path.join(work, 'cut')
    r = subprocess.run(['c++', '-std=gnu++14', '-g', '-O0', '-w', '-fsanitize=address', p, '-o', exe], capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-3000:])
    r = subprocess.run([exe], capture_output=True, text=True, timeout=60,
                       env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
    out = r.stdout.strip()
    asan = 'AddressSanitizer' in r.stderr
    print(out)
    if asan:
        print('\n'.join(l for l in r.stderr.splitlines() if 'ERROR' in l or ' #0 ' in l or ' #1 ' in l)[:600])
    check(r.returncode == 0 and not asan, 'ASan: CutTransforms on unterminated transforms reads nothing outside the string')
    check('[matrix(1 0 0 1 10 20)] [skewx(30)]' in out, 'well-formed transform list still cut into its functions')
    check('[scale(2)] [rotate(45 50 50)]' in out, 'functions before an unterminated one are kept')


def part_e2e(work):
    for p, what in ((os.path.join(LIBS, 'graphics.framework'), 'graphics.framework'), (os.path.join(FONTS, 'AllFonts.js'), 'fonts cache')):
        if not os.path.exists(p):
            print('skip end to end: missing %s (%s)' % (what, p))
            return False
    fonts = os.path.join(work, 'fonts')
    shutil.copytree(FONTS, fonts)
    src = os.path.join(work, 'drv.cpp')
    open(src, 'w').write(SVGDRV)
    exe = os.path.join(work, 'drv')
    r = subprocess.run(['c++', '-std=gnu++14', '-w', '-O1', '-DLINUX', '-D_LINUX', '-DMAC', '-D_MAC', '-I' + CORE, src,
                        '-F' + LIBS, '-framework', 'graphics', '-framework', 'kernel', '-Wl,-rpath,' + LIBS, '-o', exe],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit('driver build failed:\n' + r.stderr[-3000:])
    for name, body in SVGS.items():
        svg = os.path.join(work, name + '.svg')
        open(svg, 'w').write('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">%s</svg>' % body)
        try:
            r = subprocess.run([exe, fonts, svg, os.path.join(work, name + '.png')], capture_output=True, text=True, timeout=60)
            rc = r.returncode
        except subprocess.TimeoutExpired:
            rc = 'timeout'
        how = ('killed by %s' % signal.Signals(-rc).name) if isinstance(rc, int) and rc < 0 else 'rc=%s' % rc
        check(rc == 0, 'real SVG reader survives %s (%s)' % (name, how))
    return True


def main():
    print('%s  (frameworks: %s)' % ('BASELINE ' + BASE_REF if BASELINE else 'working tree ' + CORE, LIBS))
    work = tempfile.mkdtemp(prefix='up4e3568-')
    try:
        part_asan(work)
        part_e2e(work)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if failures:
        print('FAIL: %d check(s) failed' % len(failures))
        sys.exit(1)
    print('PASS: upstream 4e3568c926 unterminated SVG/CSS transform no longer reads past the string')


if __name__ == '__main__':
    main()
