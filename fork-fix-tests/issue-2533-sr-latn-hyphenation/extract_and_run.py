#!/usr/bin/env python3
"""
#2533 - with the text language set to Serbian (Latin), automatic hyphenation
broke a word right before a word-final "lj" or "nj": prijate-lj, ko-nj. In
Serbian these are single letters (Cyrillic љ, њ), so the next line started with
a bare consonant pair and one-syllable words like konj were split.

The engine is not at fault: libhyphen (core/Common/3dParty/hyphen, driven by
core/DesktopEditor/fontengine/TextHyphen.cpp through hnj_hyphen_hyphenate2)
counts RIGHTHYPHENMIN in UTF-8 characters, as it should. The pattern file
dictionaries/sr_Latn_RS/hyph_sr_Latn_RS.dic had no pattern against a break
before the final digraph, and two characters satisfy RIGHTHYPHENMIN 2. The fix
adds "2lj." and "2nj.".

This compiles the REAL vendored libhyphen (hyphen.c, hnjalloc.c) from the core
repo, loads the REAL pattern file from the dictionaries repo and hyphenates
the words from the report, plus controls whose breaks must stay.

  RD_REPO   dictionaries checkout (default ../../dictionaries)
  RD_CORE   core checkout for libhyphen (default ../../core)
  BASELINE=1 reads the pattern file with `git show $BASE_REF:...`, where the
  final-digraph cases must FAIL.

What is NOT claimed: the app loads the file through TextHyphen.cpp's own
hnj_hyphen_load_stream (a copy of hnj_hyphen_load that adds NOHYPHEN and
apostrophe lines); that wrapper and the wasm build are not exercised here, and
no line was laid out in the editor. Needs a C compiler (cc).
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'dictionaries'))
CORE = os.environ.get('RD_CORE') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
DIC = 'sr_Latn_RS/hyph_sr_Latn_RS.dic'
HYPHEN = os.path.join(CORE, 'Common', '3dParty', 'hyphen', 'hyphen')
# Pinned to the parent of the commit that landed the fix, never HEAD.
BASE_REF = os.environ.get('BASE_REF', '27dae48^')
BASELINE = bool(os.environ.get('BASELINE'))

DRIVER = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "hyphen.h"
int main(int argc, char **argv) {
  HyphenDict *d = hnj_hyphen_load(argv[1]);
  char w[256];
  if (!d) { fprintf(stderr, "cannot load %s\n", argv[1]); return 2; }
  while (fgets(w, sizeof w, stdin)) {
    int n;
    char *h, *hw, **rep = NULL;
    int *pos = NULL, *cut = NULL;
    w[strcspn(w, "\r\n")] = 0;
    n = (int)strlen(w);
    if (!n) continue;
    h = malloc(n + 5); hw = malloc(n * 3 + 10);
    hnj_hyphen_hyphenate2(d, w, n, h, hw, &rep, &pos, &cut);
    printf("%s\t%s\n", w, hw);
    free(h); free(hw);
  }
  return 0;
}
'''

# word -> expected hyphenation ('=' marks a break). From the report's table.
CASES = [
    ('prijatelj', 'pri=ja=telj'),
    ('roditelj', 'ro=di=telj'),
    ('učitelj', 'uči=telj'),
    ('iscelitelj', 'is=ce=li=telj'),
    ('konj', 'konj'),
    ('panj', 'panj'),
    # controls: breaks that already were right and must survive
    ('prijateljstvo', 'pri=ja=telj=stvo'),
    ('prijatelja', 'pri=ja=te=lja'),
    ('konja', 'ko=nja'),
    ('menadž', 'me=nadž'),
]


def read_dic():
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, DIC)],
                              capture_output=True, check=True).stdout
    with open(os.path.join(REPO, DIC), 'rb') as f:
        return f.read()


def main():
    for f in ('hyphen.c', 'hnjalloc.c', 'hyphen.h'):
        if not os.path.isfile(os.path.join(HYPHEN, f)):
            raise SystemExit('libhyphen not found at %s (set RD_CORE)' % HYPHEN)
    tmp = tempfile.mkdtemp(prefix='rd2533-')
    drv = os.path.join(tmp, 'drv.c')
    exe = os.path.join(tmp, 'hy')
    dic = os.path.join(tmp, 'hyph.dic')
    with open(drv, 'w') as f:
        f.write(DRIVER)
    with open(dic, 'wb') as f:
        f.write(read_dic())
    subprocess.run(['cc', '-O1', '-w', '-I', HYPHEN, drv, os.path.join(HYPHEN, 'hyphen.c'),
                    os.path.join(HYPHEN, 'hnjalloc.c'), '-o', exe], check=True)
    out = subprocess.run([exe, dic], input='\n'.join(w for w, _ in CASES) + '\n',
                         capture_output=True, text=True, check=True).stdout
    got = dict(line.split('\t') for line in out.splitlines())
    failed = 0
    for word, want in CASES:
        ok = got.get(word) == want
        failed += not ok
        print('%s %-14s got %-18s want %s' % ('PASS' if ok else 'FAIL', word, got.get(word), want))
    print('%s: %d passed / %d failed' % ('BASELINE ' + BASE_REF if BASELINE else 'fix',
                                         len(CASES) - failed, failed))
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
