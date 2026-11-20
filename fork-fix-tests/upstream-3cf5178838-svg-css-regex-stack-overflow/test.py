#!/usr/bin/env python3
"""
Upstream 3cf5178838 + 4a68bd2470 + ef6efb16b5 (ONLYOFFICE bug #80547), backported for 2026.3.1.

Crash: CSvgParser::ParseStyles (DesktopEditor/raster/Metafile/svg/CSvgParser.cpp) found SVG
@font-face blocks with std::wregex("@font-face\\s*(\\{[^}]*\\})"), and NSCSS::CURL::SetValue
(Common/3dParty/html/css/src/StyleProperties.cpp) read url(...) with another std::wregex. The
libstdc++ (Linux) and MSVC (Windows) regex engines recurse once per character matched, so an
@font-face holding an embedded font, or a long url(data:...), overflowed the stack.
macOS libc++ runs these regexes iteratively: the crash itself does NOT reproduce on a Mac
(checked: 10 MB inputs, and 1 MB inside a 512 KB-stack thread, pass with libc++).
Data loss, same code: the @font-face properties were split on every ":" and ";", so a
quoted src: url("data:font/svg;base64,...") was cut apart and the font face dropped (ef6efb16b5).

What runs - the REAL code, extracted by brace matching (BASE_REF with BASELINE=1):
CSvgParser::ParseStyles (+ ParseFontFace/TrimQuotes when present), CURL::SetValue, and the
NS_STATIC_FUNCTIONS GetWordsW/RemoveSpaces it uses, compiled with ASan against a stub CSvgFile
that records AddFontFace calls. Run on its own thread with a 256 KB stack:
  1. @font-face { font-family: "Embedded"; src: url("data:font/svg;base64,QUJD") }
     -> AddFontFace("Embedded", "data:font/svg;base64,QUJD"). 2026.3.0 drops it (FAILS).
  2. the same with a 4 MB base64 payload -> registered, payload intact, no crash.
  3. "font-family: Plain; src: url(#svgfont)" - spaces after the colons - is registered
     (2026.3.0 dropped it too); a compact url( 'x' ) face still is.
  4. CURL::SetValue on a 4 MB url(data:...) -> the whole address, no crash.
  RD_GXX=<g++ using libstdc++>  also builds and runs the same with libstdc++, where 2026.3.0
                                dies on the stack (not available on our Macs by default).

  RD_CORE=<core checkout>   (default ../../core)
  BASELINE=1                read the sources at BASE_REF; must FAIL
  BASE_REF                  default aa16ec2c0d (v2026.3.0, before the backport)
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.environ.get('RD_CORE') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASELINE = bool(os.environ.get('BASELINE'))
BASE_REF = os.environ.get('BASE_REF', 'aa16ec2c0d')
PARSER = 'DesktopEditor/raster/Metafile/svg/CSvgParser.cpp'
PROPS = 'Common/3dParty/html/css/src/StyleProperties.cpp'
STATIC = 'Common/3dParty/html/css/src/StaticFunctions.cpp'

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


def block(src, start, what):
    """`start` through its brace-matched body; braces in string/char literals and comments do not count."""
    a = src.find(start)
    if a < 0:
        sys.exit('%s not found - the extractor needs updating' % what)
    i = src.find('{', a)
    depth = 0
    while i < len(src):
        c = src[i]
        if c in '"\'':
            j = i + 1
            while src[j] != c:
                j += 2 if src[j] == '\\' else 1
            i = j
        elif src.startswith('//', i):
            i = src.find('\n', i)
        elif src.startswith('/*', i):
            i = src.find('*/', i) + 1
        elif c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return src[a:i + 1]
        i += 1
    sys.exit('%s: unbalanced braces' % what)


HEAD = r'''
#include <algorithm>
#include <cstdio>
#include <cstring>
#include <cwctype>
#include <map>
#include <pthread.h>
#include <regex>
#include <sstream>
#include <string>
#include <vector>
namespace NSCSS { namespace NS_STATIC_FUNCTIONS {
std::vector<std::wstring> GetWordsW(const std::wstring& wsLine, bool bWithSigns = false, const std::wstring& wsDelimiters = L" \n\r\t\f\v:;,!");
void RemoveSpaces(std::wstring& wsString);
@@STATIC@@
} }
namespace NSCSS {
class CURL { public: bool SetValue(const std::wstring& wsValue); bool Empty() const { return m_wsValue.empty(); }
  std::wstring GetValue() const { return m_wsValue; } std::wstring m_wsValue; };
@@SETVALUE@@
}
namespace SVG { struct TFontArguments { std::wstring m_wsFontFamily; }; typedef NSCSS::CURL SvgURL; }
using namespace SVG;
struct CSvgFile {
  std::vector<std::pair<std::wstring, std::wstring> > faces;
  void AddStyles(const std::wstring&) {}
  void AddFontFace(const SVG::TFontArguments& a, const std::wstring& id) { faces.push_back(std::make_pair(a.m_wsFontFamily, id)); }
};
namespace SVG {
struct CSvgParser { void ParseStyles(const std::wstring &wsStyles, CSvgFile *pFile) const; };
@@HELPERS@@
@@PARSE@@
}
static std::string n(const std::wstring& s) { return std::string(s.begin(), s.end()); }
static std::wstring big(size_t k) { std::wstring s; s.reserve(k); for (size_t i = 0; i < k; ++i) s += L"QUJD"[i % 4]; return s; }
static void faces(const char* label, const std::wstring& css) {
  CSvgFile f; SVG::CSvgParser().ParseStyles(css, &f);
  printf("%s:", label);
  for (auto& p : f.faces) { std::string v = n(p.second); if (v.size() > 40) v = v.substr(0, 30) + "...(" + std::to_string(v.size()) + ")"; printf(" [%s|%s]", n(p.first).c_str(), v.c_str()); }
  printf("\n"); fflush(stdout);
}
static void* run(void*) {
  faces("quoted-data", L"@font-face { font-family: \"Embedded\"; src: url(\"data:font/svg;base64,QUJD\") }");
  faces("big-data", L"@font-face { font-family: \"Embedded\"; src: url(\"data:font/svg;base64," + big(4u << 20) + L"\") }");
  faces("svg-font", L"text { fill: red } @font-face { font-family: Plain; src: url(#svgfont) } p { }");
  faces("spaces", L"@font-face{font-family:Sp;src:url( 'x.svg#f' )}");
  NSCSS::CURL u; bool ok = u.SetValue(L"url(data:image/png;base64," + big(4u << 20) + L")");
  printf("curl-big: %d %zu\n", ok ? 1 : 0, u.GetValue().size()); fflush(stdout);
  return NULL;
}
int main() {
  pthread_attr_t a; pthread_attr_init(&a); pthread_attr_setstacksize(&a, 256 * 1024);
  pthread_t t; pthread_create(&t, &a, run, NULL); pthread_join(t, NULL);
  printf("done\n");
  return 0;
}
'''


def source():
    st = read(STATIC)
    static = '\n'.join(block(st, sig, sig) for sig in ('std::vector<std::wstring> GetWordsW(', 'void RemoveSpaces('))
    setvalue = block(read(PROPS), 'bool CURL::SetValue(', 'CURL::SetValue')
    p = read(PARSER)
    parse = block(p, 'void CSvgParser::ParseStyles(', 'CSvgParser::ParseStyles')
    helpers = ''
    a = p.find('typedef std::pair<std::wstring, std::wstring> StylePropertie;')
    if a >= 0:
        helpers = p[a:p.find('void CSvgParser::ParseStyles(')]
    return HEAD.replace('@@STATIC@@', static).replace('@@SETVALUE@@', setvalue) \
               .replace('@@HELPERS@@', helpers).replace('@@PARSE@@', parse)


def build_and_run(cxx, flags, work, tag):
    p = os.path.join(work, 'drv_%s.cpp' % tag)
    open(p, 'w').write(source())
    exe = p[:-4]
    r = subprocess.run([cxx, '-std=gnu++14', '-g', '-O1', '-w'] + flags + [p, '-o', exe, '-lpthread'], capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed (%s):\n%s' % (cxx, r.stderr[-3000:]))
    r = subprocess.run([exe], capture_output=True, text=True, timeout=600, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
    return r


def verify(r, tag):
    out = r.stdout
    print(out.strip())
    if r.returncode:
        print('\n'.join(r.stderr.strip().splitlines()[:4]))
    check(r.returncode == 0 and 'done' in out, '%s: no crash with a 256 KB stack (rc=%d)' % (tag, r.returncode))
    check('quoted-data: [Embedded|data:font/svg;base64,QUJD]' in out,
          '%s: quoted data: URL @font-face is registered with its whole address' % tag)
    url = 'data:font/svg;base64,' + 'QUJD' * (1 << 20)
    check('big-data: [Embedded|%s...(%d)]' % (url[:30], len(url)) in out,
          '%s: 4 MB embedded font is registered intact' % tag)
    check('svg-font: [Plain|#svgfont]' in out, '%s: "font-family: Plain; src: url(#svgfont)" (spaces after the colons) is registered' % tag)
    check('spaces: [Sp|x.svg#f]' in out, "%s: compact url( '...' ) with inner spaces still registered" % tag)
    check('curl-big: 1 %d' % (len('data:image/png;base64,') + (4 << 20)) in out, '%s: CURL::SetValue reads a 4 MB url(data:...)' % tag)


def main():
    print('(%s)' % ('BASELINE ' + BASE_REF if BASELINE else 'working tree ' + CORE))
    work = tempfile.mkdtemp(prefix='up3cf517-')
    try:
        verify(build_and_run('c++', ['-fsanitize=address'], work, 'libcxx_asan'), 'libc++ ASan')
        if os.environ.get('RD_GXX'):
            verify(build_and_run(os.environ['RD_GXX'], [], work, 'libstdcxx'), 'libstdc++')
        else:
            print('note: RD_GXX not set - the libstdc++ stack overflow itself is not exercised on this machine')
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if failures:
        print('FAIL: %d check(s) failed' % len(failures))
        sys.exit(1)
    print('PASS: upstream 3cf5178838/4a68bd2470/ef6efb16b5 SVG @font-face and CSS url() parsed without std::regex')


if __name__ == '__main__':
    main()
