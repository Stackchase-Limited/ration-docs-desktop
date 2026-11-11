#!/usr/bin/env python3
"""
#1031 - "Wrong text encoding when open some wmf image contain Chinese".

The reporter's encoding-test.docx holds word/media/image1.wmf. Its caption is an
EXTTEXTOUT whose bytes are GBK - 39 A1 C1 32 37 30 A1 C1 4E B8 F6 D7 D6 BD DA,
"9×270×N个字节" - drawn with a CREATEFONTINDIRECT "Arial", charset 0 (ANSI_CHARSET).
Windows decodes ANSI_CHARSET/DEFAULT_CHARSET text with the system ANSI code page,
so on the reporter's Simplified Chinese system (cp936) Office draws Chinese.
MetaFile::ConvertToUnicode (core/DesktopEditor/raster/Metafile/Common/
MetaFileUtils.cpp) always used 1252 for ANSI_CHARSET and Latin-1 for
DEFAULT_CHARSET, which gives "9¡Á270¡ÁN¸ö×Ö½Ú" - what the reporter saw, and what
x2t still drew in our 9.4 tree (docx -> pdf, LANG=zh_CN.UTF-8).

Fix: ANSI_CHARSET and DEFAULT_CHARSET follow the host code page when it is 932,
936, 949 or 950 (GetACP() on Windows, LC_ALL/LC_CTYPE/LANG elsewhere); any other
host keeps the old decoding.

This extracts the real ConvertToUnicode and the helpers it calls out of
MetaFileUtils.cpp by brace matching, compiles them with clang++ against the real
MetaFileTypes.h and the real StringExt.cpp/CodePage tables of the same core tree,
and decodes the reporter's bytes under different locales (one process each,
since the code page is read once per process).

Claimed: under a zh_CN locale the reporter's bytes become 9×270×N个字节; under
C/en_US/unset locales ANSI text decodes exactly as 1252 did before, and explicit
charsets (GB2312_CHARSET 134, RUSSIAN 204) are unaffected.
NOT claimed: the Windows branch (GetACP) was not compiled or run here; macOS GUI
launches usually have no LANG, so the desktop app on macOS keeps the old
decoding unless the locale reaches x2t's environment.

RD_REPO overrides the core checkout. BASELINE=1 reads MetaFileUtils.cpp from git
at BASE_REF and must FAIL there.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
REL = 'DesktopEditor/raster/Metafile/Common/MetaFileUtils.cpp'
# Pinned to the parent of the commit that landed this fix, never HEAD.
BASE_REF = os.environ.get('BASE_REF', '9e6c96b316^')

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


def func(pattern, required=True):
    m = re.search(pattern, src, re.M)
    if not m:
        if required:
            raise SystemExit('not found: ' + pattern)
        return ''
    return block(src, m.start()) + '\n'


# The helpers exist only once the fix is in; ConvertToUnicode is extracted in both
# trees, so the baseline runs the same harness against the old decoding.
helpers = (func(r'^\s*static unsigned int GetSystemAnsiCodePage\(\)', False) +
           func(r'^\s*static NSStringExt::CConverter::ESingleByteEncoding GetAnsiEncoding\(', False))
convert = func(r'^\s*std::wstring ConvertToUnicode\(const unsigned char\* pText')

harness = r'''
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include "MetaFileTypes.h"
namespace MetaFile {
%s
%s
}
int main(int argc, char** argv)
{
	// argv[1]: charset, argv[2..]: hex bytes; prints the decoded code points
	unsigned short cs = (unsigned short)atoi(argv[1]);
	unsigned char buf[256]; int n = 0;
	for (int i = 2; i < argc; ++i) buf[n++] = (unsigned char)strtol(argv[i], NULL, 16);
	std::wstring w = MetaFile::ConvertToUnicode(buf, n, cs);
	for (size_t i = 0; i < w.size(); ++i) printf("%%04X ", (unsigned int)w[i]);
	printf("\n");
	return 0;
}
''' % (helpers, convert)

meta_dir = os.path.join(CORE, 'DesktopEditor/raster/Metafile/Common')
common = os.path.join(CORE, 'DesktopEditor/common')
tmp = tempfile.mkdtemp(prefix='rd1031-')
cpp = os.path.join(tmp, 't.cpp')
exe = os.path.join(tmp, 't')
open(cpp, 'w', encoding='utf-8').write(harness)
cxx = os.environ.get('CXX', 'clang++')
r = subprocess.run([cxx, '-std=gnu++11', '-w', '-O0', '-DLINUX', '-D_LINUX', '-DMAC', '-D_MAC',
                    '-I', meta_dir, '-I', common, cpp, os.path.join(common, 'StringExt.cpp'), '-o', exe],
                   capture_output=True, text=True)
if r.returncode:
    sys.stderr.write(r.stderr[-4000:])
    raise SystemExit('compile failed')

REPORTER = '39 A1 C1 32 37 30 A1 C1 4E B8 F6 D7 D6 BD DA'.split()
EXPECT_ZH = [ord(c) for c in '9×270×N个字节']
CP1252 = [ord(c) for c in bytes(int(b, 16) for b in REPORTER).decode('cp1252')]


def run(locale, charset, data):
    env = {k: v for k, v in os.environ.items() if k not in ('LC_ALL', 'LC_CTYPE', 'LANG')}
    if locale is not None:
        env['LANG'] = locale
    out = subprocess.run([exe, str(charset)] + data, capture_output=True, text=True, env=env, check=True).stdout
    return [int(x, 16) for x in out.split()]


results = []


def check(name, got, want):
    ok = got == want
    results.append(ok)
    print('%s  %s%s' % ('PASS' if ok else 'FAIL', name,
                        '' if ok else '\n      got  %s\n      want %s' % (''.join(map(chr, got)), ''.join(map(chr, want)))))


check('zh_CN host: reporter\'s ANSI_CHARSET caption reads 9×270×N个字节', run('zh_CN.UTF-8', 0, REPORTER), EXPECT_ZH)
check('zh_CN host: DEFAULT_CHARSET text follows cp936 too', run('zh_CN.UTF-8', 1, REPORTER), EXPECT_ZH)
check('en_US host: ANSI_CHARSET still decodes as cp1252', run('en_US.UTF-8', 0, REPORTER), CP1252)
check('no locale: ANSI_CHARSET still decodes as cp1252', run(None, 0, REPORTER), CP1252)
check('zh_CN host: explicit GB2312_CHARSET is unchanged', run('zh_CN.UTF-8', 134, REPORTER), EXPECT_ZH)
check('zh_CN host: explicit RUSSIAN_CHARSET is unchanged',
      run('zh_CN.UTF-8', 204, ['C0', 'E1']), [ord(c) for c in b'\xc0\xe1'.decode('cp1251')])

subprocess.run(['rm', '-rf', tmp])
failed = results.count(False)
print('%d of %d FAILED' % (failed, len(results)) if failed else 'all %d passed' % len(results))
sys.exit(1 if failed else 0)
