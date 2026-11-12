#!/usr/bin/env python3
"""
RD-0018 (our corpus run, no upstream issue): converting an EMF picture to SVG
(how documents with EMF images are opened in the editor) crashed when a text
record was empty but carried a character-spacing (Dx) array.

Found with an AddressSanitizer x2t on POI's tika-3388.docx (open): SEGV on a
WRITE to address 0 in MetaFile::CInterpretatorSvgBase::WriteText
(DesktopEditor/raster/Metafile/Wmf/WmfInterpretator/CInterpretatorSvgBase.cpp),
from CEmfInterpretatorSvg::HANDLE_EMR_EXTTEXTOUTW. The release x2t did not crash
on this file in our run (undefined behaviour; whether the write through the
empty vector's data pointer faults depends on the build).

Cause: WriteText builds per-character x coordinates when a Dx array is given and
it has at least as many entries as the text has characters:
`std::vector<double> arXCoords(wsNormalizedText.length()); arXCoords[0] = ...`.
For an empty text with a non-empty Dx array the vector is empty and element 0
is written through its null data pointer. Fix: an empty text takes the
single-coordinate path, like a text without Dx.

What runs: the REAL fragment of WriteText that computes the x coordinate(s)
(from "std::wstring wsXCoord;" through the end of its else-block, git show
BASE_REF:... with BASELINE=1) is compiled with -fsanitize=address with a
stand-in ConvertToWString, and run for an empty text with Dx {10} and for
"ab" with Dx {10, 10}. Passes when ASan reports nothing, the empty text gets
the single coordinate and "ab" gets two.

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read CInterpretatorSvgBase.cpp at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0018 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', 'ccddc3317b^')
BASELINE = bool(os.environ.get('BASELINE'))
SRC = 'DesktopEditor/raster/Metafile/Wmf/WmfInterpretator/CInterpretatorSvgBase.cpp'


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig', 'replace')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig', errors='replace').read()


DRIVER = r'''
#include <cstdio>
#include <string>
#include <vector>
static std::wstring ConvertToWString(double d) { return std::to_wstring((int)d); }
static std::wstring ConvertToWString(const std::vector<double>& v) {
    std::wstring s; for (size_t i = 0; i < v.size(); ++i) { if (i) s += L' '; s += std::to_wstring((int)v[i]); } return s; }
static std::wstring x(const std::wstring& wsNormalizedText, const std::vector<double>& arDx, double dXCoord) {
@@FRAGMENT@@
    return wsXCoord;
}
int main() {
    printf("EMPTY=[%ls]\n", x(L"", std::vector<double>(1, 10.0), 5).c_str());
    printf("AB=[%ls]\n", x(L"ab", std::vector<double>(2, 10.0), 5).c_str());
    return 0;
}
'''


def main():
    src = read(SRC)
    a = src.find('std::wstring wsXCoord;')
    if a < 0:
        sys.exit('x coordinate block not found - the extractor needs updating')
    e = src.find('wsXCoord = ConvertToWString(arXCoords);', a)
    if e < 0:
        sys.exit('x coordinate block end not found - the extractor needs updating')
    e = src.find('}', e) + 1
    work = tempfile.mkdtemp(prefix='rd0018-')
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write(DRIVER.replace('@@FRAGMENT@@', src[a:e]))
    exe = os.path.join(work, 'drv')
    r = subprocess.run(['c++', '-std=gnu++11', '-fsanitize=address', '-g', '-w', '-O0', p, '-o', exe],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-3000:])
    r = subprocess.run([exe], capture_output=True, text=True, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
    out = r.stdout + r.stderr
    m = re.search(r'ERROR: AddressSanitizer: ([\w-]+)', out)
    ok = r.returncode == 0 and not m and 'EMPTY=[5]' in out and 'AB=[5 15]' in out
    print(('ok   ' if ok else 'FAIL ') + 'EMF text x coordinates, empty text with Dx (%s): %s' % (
        'baseline ' + BASE_REF if BASELINE else 'working tree',
        ('ASan ' + m.group(1)) if m else (out.strip().replace('\n', ' ') if out.strip() else 'rc=%d' % r.returncode)))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
