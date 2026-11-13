#!/usr/bin/env python3
"""
RD-0044 (our corpus run, no upstream issue): a .ppt slide whose records could
not be read crashed x2t. Two NULL dereferences, on Apache POI's slideshow fuzz
files:

- clusterfuzz-testcase-minimized-POIHSLFFuzzer-6032591399288832.ppt, SIGSEGV:
  CPPTUserInfo keeps an unreadable slide persist in m_mapSlides as NULL
  (PPTDocumentInfoOneUser.cpp, "m_mapSlides.insert(... NULL)"), and
  CPPTXWriter::WriteTiming (PPTXWriter/Converter.cpp) passed slide_iter->second
  to Intermediate::ParseSlideAnimation, whose getOldSlideAnimation called
  pSlide->GetRecordsByType (Converter/Animation/AnimationParser.cpp).
  Fix: WriteTiming passes NULL for a missing/unread record, and
  getOldSlideAnimation / getPP10SlideBinaryTagExtension return "no animation"
  for NULL.
- clusterfuzz-testcase-minimized-POIHSLFFuzzer-5018229722382336.ppt, SIGABRT
  ("Assertion failed: (px != 0)", boost::shared_ptr): CPPTUserInfo::LoadSlide
  tested pElement->m_bIsBackground on the element GetElement returned, which is
  NULL for this shape. Fix: the test starts with "pElement &&".

What runs (git show BASE_REF:... with BASELINE=1), compiled with
-fsanitize=address:
- the REAL getOldSlideAnimation and getPP10SlideBinaryTagExtension with stand-in
  record classes, called with NULL (must return empty / nullptr) and with a slide
  holding one shape container with a shape and an animation (one animation,
  unchanged);
- the REAL "if (...m_bIsBackground...)" condition of LoadSlide's
  shape-container branch, evaluated on a NULL element (with a shared_ptr
  stand-in that aborts on NULL ->, like boost's) and on a background element
  without anchor (true, unchanged).
NOT claimed: WriteTiming's iterator change is not executed here (it is a
one-line NULL-for-end() substitution; read the diff).

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read the sources at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0044 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '8fbcbd7f5b^')
BASELINE = bool(os.environ.get('BASELINE'))
ANIM = 'MsBinaryFile/PptFile/Converter/Animation/AnimationParser.cpp'
USER = 'MsBinaryFile/PptFile/Reader/PPTDocumentInfoOneUser.cpp'


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig', 'replace')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig', errors='replace').read()


def func(src, sig):
    a = src.find(sig)
    if a < 0:
        sys.exit(sig + ' not found - the extractor needs updating')
    i = src.find('{', a); depth = 0
    while True:
        if src[i] == '{': depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0: return src[a:i + 1]
        i += 1


DRIVER = r'''
#include <cstdio>
#include <cstdlib>
#include <vector>
struct IRecord { virtual ~IRecord() {} };
struct CRecordsContainer : IRecord { std::vector<IRecord*> m_arRecords;
  template <typename T> void GetRecordsByType(std::vector<T>* out, bool, bool = false) const {
    for (size_t i = 0; i < m_arRecords.size(); i++) { T p = dynamic_cast<T>(m_arRecords[i]); if (p) out->push_back(p); } } };
struct CRecordShape : IRecord { int m_nID; };
struct CRecordAnimationInfoContainer : IRecord {};
struct CRecordShapeContainer : CRecordsContainer {};
struct CRecordPP10SlideBinaryTagExtension {};
struct CRecordSlideProgTagsContainer { CRecordPP10SlideBinaryTagExtension* getPP10SlideBinaryTagExtension() { return NULL; } };
struct CRecordSlide : CRecordsContainer { CRecordSlideProgTagsContainer* m_pSlideProgTagsContainer; CRecordSlide() : m_pSlideProgTagsContainer(NULL) {} };
struct SOldAnimation { int shapeId; CRecordAnimationInfoContainer* anim; };
// boost::shared_ptr asserts on -> through NULL
struct CElement { bool m_bIsBackground, m_bHaveAnchor; };
struct CElementPtr { CElement* px; CElement* operator->() const { if (!px) { fprintf(stderr, "Assertion failed: (px != 0)\n"); abort(); } return px; }
  operator bool() const { return px != NULL; } };
@@ANIM@@
int main(int argc, char** argv) {
  char c = argv[1][0];
  if (c == 'n') { std::vector<SOldAnimation> v = getOldSlideAnimation(NULL); printf("anims=%zu ext=%p\n", v.size(), (void*)getPP10SlideBinaryTagExtension(NULL)); }
  else if (c == 's') { CRecordSlide s; CRecordShapeContainer sc; CRecordShape sh; sh.m_nID = 7; CRecordAnimationInfoContainer an;
    sc.m_arRecords.push_back(&sh); sc.m_arRecords.push_back(&an); s.m_arRecords.push_back(&sc);
    std::vector<SOldAnimation> v = getOldSlideAnimation(&s); printf("anims=%zu id=%d\n", v.size(), v.empty() ? 0 : v[0].shapeId); }
  else { CElement e = { true, false }; CElementPtr pElement = { c == 'e' ? NULL : &e }; bool bMasterBackGround = false; bool bg = false;
    @@COND@@ bg = true;
    printf("background=%d\n", (int)bg); }
  return 0;
}
'''

CASES = [('n', 'no slide record (NULL): no animation', 'anims=0 ext=0x0'),
         ('s', 'slide with one animated shape (unchanged)', 'anims=1 id=7'),
         ('e', 'LoadSlide: GetElement returned NULL', 'background=0'),
         ('b', 'LoadSlide: background element without anchor (unchanged)', 'background=1')]


def main():
    anim = read(ANIM)
    code = func(anim, 'CRecordPP10SlideBinaryTagExtension* getPP10SlideBinaryTagExtension') + '\n' + \
        func(anim, 'std::vector<SOldAnimation> getOldSlideAnimation')
    user = read(USER)
    a = user.find('void CPPTUserInfo::LoadSlide')
    m = re.compile(r'if \((pElement[^\n]*m_bIsBackground[^\n]*)\)\s*\n').search(user, a)
    if a < 0 or not m:
        sys.exit('LoadSlide background test not found - the extractor needs updating')
    drv = DRIVER.replace('@@ANIM@@', code.replace('nullptr', 'NULL')).replace('@@COND@@', 'if (%s)' % m.group(1))
    work = tempfile.mkdtemp(prefix='rd0044-')
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write(drv)
    exe = os.path.join(work, 'drv')
    r = subprocess.run(['c++', '-std=gnu++11', '-fsanitize=address', '-g', '-w', p, '-o', exe], capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-3000:])
    fails = 0
    for arg, name, want in CASES:
        r = subprocess.run([exe, arg], capture_output=True, text=True, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
        m = re.search(r'ERROR: AddressSanitizer: ([\w-]+)|Assertion failed', r.stderr)
        ok = r.returncode == 0 and not m and r.stdout.strip() == want
        fails += not ok
        print(('ok   ' if ok else 'FAIL ') + '%s (%s): %s' % (
            name, 'baseline ' + BASE_REF if BASELINE else 'working tree',
            (('ASan ' + m.group(1)) if m.group(1) else m.group(0)) if m else (r.stdout.strip() or 'rc=%d' % r.returncode)))
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
