#!/usr/bin/env python3
"""
RD-0013 (our corpus run, no upstream issue): saving a document with a bulleted
or numbered list as RTF built the paragraph's list text from a 1-byte char
array as if it were a C string, reading stack bytes past it into the output.

Found with an AddressSanitizer x2t on 5 RTF files with lists (e.g. Tika's
testRTFListLibreOffice.rtf), Editor.bin -> RTF: stack-buffer-overflow READ in
RtfListLevelProperty::GenerateListText (RtfFile/Format/RtfProperty.cpp), called
from RtfParagraphProperty::RenderToRtf.

Cause: `char cBullet[1]; cBullet[0] = (char)149; std::string sBullet = cBullet;`
- std::string(const char*) runs strlen over the array, which has no
terminator, so the string took whatever stack bytes followed until a zero
byte. Those bytes were written into the saved RTF as the list text after the
bullet. Fix: the string is built from exactly that one char.

What runs: the REAL RtfListLevelProperty::GenerateListText body is lifted out
of RtfProperty.cpp by brace matching (git show BASE_REF:... with BASELINE=1) and
compiled as a free function with -fsanitize=address, then called. Passes when
ASan reports nothing and the text is exactly one character (the bullet, as
before).

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read RtfProperty.cpp at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0013 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '74a8ff889d^')
BASELINE = bool(os.environ.get('BASELINE'))


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


def main():
    src = read('RtfFile/Format/RtfProperty.cpp')
    fn = block(src, 'std::wstring RtfListLevelProperty::GenerateListText()')
    fn = fn.replace('RtfListLevelProperty::GenerateListText', 'GenerateListText', 1)
    drv = '#include <cstdio>\n#include <string>\n' + fn + r'''
int main() {
    std::wstring t = GenerateListText();
    printf("LEN=%zu FIRST=%x\n", t.size(), t.empty() ? 0u : (unsigned)(t[0] & 0xFF));
    return 0;
}
'''
    work = tempfile.mkdtemp(prefix='rd0013-')
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write(drv)
    exe = os.path.join(work, 'drv')
    r = subprocess.run(['c++', '-std=gnu++11', '-fsanitize=address', '-g', '-w', '-O0', p, '-o', exe],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-2000:])
    r = subprocess.run([exe], capture_output=True, text=True, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
    out = r.stdout + r.stderr
    a = re.search(r'ERROR: AddressSanitizer: ([\w-]+)', out)
    ok = r.returncode == 0 and not a and 'LEN=1 FIRST=95' in out
    print(('ok   ' if ok else 'FAIL ') + 'RTF list text (%s): %s' % (
        'baseline ' + BASE_REF if BASELINE else 'working tree',
        ('ASan ' + a.group(1)) if a else (out.strip() if out.strip() else 'rc=%d' % r.returncode)))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
