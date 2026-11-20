#!/usr/bin/env python3
"""
RD-0114 (found while testing upstream 86a717a42f/7a9c80e60c): a docbuilder script line like

  builder.SaveFile("txt", "<path>", "<m_sJsonParams>{'documentLayout':{'drawPlaceHolders':true,...}}</m_sJsonParams>");

aborted docbuilder with SIGABRT - for every output format (txt, pdf, docx, html, odt, rtf), and
for any params with more than one '...' pair.

Cause (core/DesktopEditor/doctrenderer/docbuilder_p.cpp, ParceParameters, called from
CDocBuilder::RunTextA with `std::wstring _builder_params[4]`): an argument ended at ANY quote, so
every ' inside the double-quoted params split off another "argument", and all of them were stored
into the 4-entry array - the 5th and later were written past its end (stack corruption -> abort).
Fix: an argument ends only at the quote that opened it, and at most the array's size is stored.

What runs:
  1. The REAL ParceParameters and the REAL declaration + call lines of _builder_params are lifted
     out of docbuilder_p.cpp (git show BASE_REF:... with BASELINE=1), compiled with
     -fsanitize=address into a harness, and fed the SaveFile line above plus a line with six
     plain arguments. Passes when nothing overflows and the third argument of the SaveFile line
     is the whole <m_sJsonParams>...</m_sJsonParams> string.
  2. End to end, if docbuilder + frameworks are available (same setup as
     upstream-86a717a42f-builder-file-escape): the real docbuilder runs the SaveFile line for
     txt, pdf and docx. Passes when it exits 0 and each output file exists. BASELINE uses the
     2026.3.0 payload frameworks (which abort).

  RD_REPO=<core checkout>   (default ../../core); docbuilder from <repo>/build/bin/mac_arm64,
                            frameworks from RD_CORE_LIBS (default <repo>/build/lib/mac_arm64)
  BASELINE=1                read BASE_REF, frameworks + x2t from RD_PAYLOAD_BASE; must FAIL
  BASE_REF                  default e4e2f8a3c5 (parent of the RD-0114 commit)
  RD_PAYLOAD_BASE           default .rd-work/mac-2026.3.0/payload (sdkjs, empty templates)
  RD_FONTS                  font cache (default .rd-work/fonts-cache; copied first)
  SKIP_E2E=1                only part 1
"""
import glob
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
REPO = os.environ.get('RD_REPO') or os.path.join(ROOT, 'core')
RDWORK = os.path.normpath(os.path.join(ROOT, '..', '.rd-work'))
BASE_REF = os.environ.get('BASE_REF', 'e4e2f8a3c5')
BASELINE = bool(os.environ.get('BASELINE'))
REL = 'DesktopEditor/doctrenderer/docbuilder_p.cpp'
PAYLOAD = os.environ.get('RD_PAYLOAD_BASE') or os.path.join(RDWORK, 'mac-2026.3.0', 'payload')
FONTS = os.environ.get('RD_FONTS') or os.path.join(RDWORK, 'fonts-cache')
DOCBUILDER = os.path.join(REPO, 'build', 'bin', 'mac_arm64', 'docbuilder')
if BASELINE:
    LIBS, X2T = os.path.join(PAYLOAD, 'converter'), os.path.join(PAYLOAD, 'converter', 'x2t')
else:
    LIBS = os.environ.get('RD_CORE_LIBS') or os.path.join(REPO, 'build', 'lib', 'mac_arm64')
    X2T = os.environ.get('RD_X2T') or os.path.join(REPO, 'build', 'bin', 'mac_arm64', 'x2t')

PARAMS = "<m_sJsonParams>{'documentLayout':{'drawPlaceHolders':true,'drawFormHighlight':true,'isPrint':true}}</m_sJsonParams>"

failures = []


def check(cond, what):
    print(('ok   ' if cond else 'FAIL ') + what)
    if not cond:
        failures.append(what)


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig', 'replace')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig', errors='replace').read()


def function(text, head):
    """The function starting at `head`, up to its matching closing brace."""
    a = text.find(head)
    if a < 0:
        raise SystemExit('cannot find %r in %s' % (head, REL))
    i, depth = text.index('{', a), 0
    while True:
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[a:i + 1]
        i += 1


def line_with(text, needle):
    for ln in text.splitlines():
        if needle in ln:
            return ln.strip()
    raise SystemExit('cannot find %r in %s' % (needle, REL))


def harness():
    src = read(REL)
    parce = function(src, 'void ParceParameters(')
    # the declaration of _builder_params (and the size constant, if any) and the call, verbatim
    decl = [line_with(src, 'std::wstring _builder_params[')]
    if 'nMaxBuilderParams' in decl[0]:
        decl.insert(0, line_with(src, 'const int nMaxBuilderParams'))
    call = line_with(src, 'ParceParameters(command, _builder_params')
    code = r'''
#include <string>
#include <cstdio>
#include <cstdlib>
typedef unsigned char BYTE;
typedef long LONG;
namespace NSFile { struct CUtf8Converter {
    static std::wstring GetUnicodeStringFromUTF8(BYTE* p, LONG n) { return std::wstring(p, p + n); } }; }
namespace NSDoctRenderer {
%(parce)s
}
using namespace NSDoctRenderer;
int main(int argc, char** argv)
{
    std::string command = argv[1];
    %(decl)s
    int nCountParameters = 0;
    %(call)s
    printf("count=%%d\n", nCountParameters);
    for (int i = 0; i < nCountParameters && i < 3; ++i)
    {
        std::string s(_builder_params[i].begin(), _builder_params[i].end());
        printf("p%%d=%%s\n", i, s.c_str());
    }
    return 0;
}
''' % dict(parce=parce, decl='\n    '.join(decl), call=call)
    return code


def part1(work):
    cpp, exe = os.path.join(work, 'h.cpp'), os.path.join(work, 'h')
    open(cpp, 'w').write(harness())
    r = subprocess.run(['clang++', '-std=c++17', '-g', '-O0', '-fsanitize=address', '-fno-omit-frame-pointer', cpp, '-o', exe],
                       capture_output=True, text=True)
    if r.returncode:
        print(r.stderr[-2000:])
        raise SystemExit('harness did not compile')
    env = dict(os.environ, ASAN_OPTIONS='detect_leaks=0:symbolize=0')
    line = 'builder.SaveFile("txt", "/tmp/out.txt", "%s");' % PARAMS
    r = subprocess.run([exe, line], capture_output=True, text=True, env=env, timeout=120)
    overflow = r.returncode != 0
    print('  SaveFile line: rc=%d %s' % (r.returncode, r.stdout.strip().replace('\n', ' | ')))
    if overflow:
        print('  ' + '\n  '.join(l for l in r.stderr.splitlines() if 'ERROR' in l or 'SUMMARY' in l))
    check(not overflow, "ParceParameters stays inside _builder_params for SaveFile params with ' quotes")
    check(not overflow and ('p2=' + PARAMS) in r.stdout.splitlines(), 'the third SaveFile argument is the whole <m_sJsonParams> string')
    check(not overflow and 'p1=/tmp/out.txt' in r.stdout.splitlines(), 'the path argument is unchanged')
    r = subprocess.run([exe, 'builder.SaveFile("txt", "/tmp/o.txt", "x1", "x2", "x3", "x4");'], capture_output=True, text=True, env=env, timeout=120)
    print('  six arguments: rc=%d %s' % (r.returncode, r.stdout.strip().replace('\n', ' | ')))
    check(r.returncode == 0, 'more arguments than _builder_params holds do not overflow it')


def part2(work):
    for p, what in ((DOCBUILDER, 'docbuilder'), (X2T, 'x2t'), (os.path.join(LIBS, 'doctrenderer.framework'), 'doctrenderer.framework'),
                    (os.path.join(PAYLOAD, 'editors', 'sdkjs', 'word'), 'sdkjs'), (os.path.join(FONTS, 'AllFonts.js'), 'fonts cache')):
        if not os.path.exists(p):
            print('skip end-to-end: missing %s (%s)' % (what, p))
            return
    print('end to end: frameworks %s' % LIBS)
    b = os.path.join(work, 'bin')
    os.makedirs(os.path.join(b, 'empty'))
    os.makedirs(os.path.join(work, 'Frameworks'))
    for f in glob.glob(os.path.join(LIBS, '*.framework')):
        os.symlink(f, os.path.join(work, 'Frameworks', os.path.basename(f)))
    shutil.copy(DOCBUILDER, b)
    shutil.copy(X2T, os.path.join(b, 'x2t'))
    for f in glob.glob(os.path.join(PAYLOAD, 'converter', 'empty', 'en-US', 'new.*')):
        shutil.copy(f, os.path.join(b, 'empty'))
    fonts = os.path.join(work, 'fonts')
    shutil.copytree(FONTS, fonts)
    ed = os.path.join(PAYLOAD, 'editors')
    open(os.path.join(b, 'DoctRenderer.config'), 'w').write(
        '<Settings><file>{e}/sdkjs/common/Native/native.js</file><file>{e}/sdkjs/common/Native/jquery_native.js</file>'
        '<allfonts>{f}/AllFonts.js</allfonts><file>{e}/web-apps/vendor/xregexp/xregexp-all-min.js</file>'
        '<sdkjs>{e}/sdkjs</sdkjs></Settings>'.format(e=ed, f=fonts))
    env = dict(os.environ, DYLD_FRAMEWORK_PATH=os.path.join(work, 'Frameworks'))
    for fmt in ('txt', 'pdf', 'docx'):
        out = os.path.join(work, 'out.' + fmt)
        p = os.path.join(b, 'script.docbuilder')
        open(p, 'w').write('builder.CreateFile("docx");\nApi.GetDocument().GetElement(0).AddText("hello");\n'
                           'builder.SaveFile("%s", "%s", "%s");\nbuilder.CloseFile();\n' % (fmt, out, PARAMS))
        r = subprocess.run([os.path.join(b, 'docbuilder'), '--check-fonts=0', '--all-fonts-path=' + os.path.join(fonts, 'AllFonts.js'), p],
                           capture_output=True, text=True, timeout=300, env=env, cwd=b)
        print('  %s: rc=%d out=%s' % (fmt, r.returncode, os.path.getsize(out) if os.path.exists(out) else 'missing'))
        check(r.returncode == 0, 'docbuilder SaveFile("%s", ..., documentLayout params) exits 0 (rc=%d)' % (fmt, r.returncode))
        check(os.path.exists(out) and os.path.getsize(out) > 0, 'docbuilder wrote out.%s' % fmt)
        if fmt == 'txt':
            check(os.path.exists(out) and open(out, encoding='utf-8-sig').read().strip() == 'hello', 'out.txt holds the text')


def main():
    print('(%s)' % ('baseline ' + BASE_REF if BASELINE else 'working tree'))
    work = tempfile.mkdtemp(prefix='rd0114-')
    try:
        part1(work)
        if not os.environ.get('SKIP_E2E'):
            part2(work)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if failures:
        print('%s: FAIL, %d check(s) failed' % ('BASELINE' if BASELINE else 'FIX', len(failures)))
        sys.exit(1)
    print('%s: PASS, docbuilder SaveFile params with \' quotes save instead of aborting' % ('BASELINE' if BASELINE else 'FIX'))


if __name__ == '__main__':
    main()
