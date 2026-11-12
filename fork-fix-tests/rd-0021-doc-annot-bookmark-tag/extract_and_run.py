#!/usr/bin/env python3
"""
RD-0021 (our corpus run, no upstream issue): a .doc whose comment-range
bookmarks have no tag data, or whose bookmark end table is shorter than the
start table, crashed x2t (SIGSEGV) while loading.

Found on LibreOffice's fuzz regression files sw/qa/core/data/ww6/pass/crash-3.doc,
ww8/pass/ofz18554-1.doc, ofz46457-1.doc and ofz53457-1.doc: the release x2t
dies with SIGSEGV at address 0x0 / 0x2 in WordDocument::LoadDocument
(MsBinaryFile/DocFile/WordDocument.cpp, the PlcfAtnBkf loop).

Cause: each comment-range bookmark's tag is read from the 6 extra bytes of its
name in SttbfAtnBkmk as *(bookmarks[i] + 2), with no check that the name table
has an entry i, that it has extra data (ReadBytes gives NULL for cbExtra 0 or
past the end of the stream) or that cbExtra >= 6. The end positions of all three
bookmark tables (PlcfBkl, PlcfAtnBkl, PlcfBklProt) were indexed by i without a
bound; with the tag read guarded the same files then died on an empty end plex.
Fix: a comment range is paired only when its tag is present and complete, and
every loop checks that the end plex has an entry i.

What runs: the REAL three bookmark-pairing loops of WordDocument::LoadDocument
(from "for (size_t i = 0; i < BookmarkStartPlex->Elements.size()" up to the
"AutoTextPlex" assignment; git show BASE_REF:... with BASELINE=1) compiled with
-fsanitize=address against stand-in Plex / StringTable / BookmarkFirst types.
Cases: (a) comment bookmark whose name has no extra data, (b) bookmark/comment/
protection end tables empty, (c) a well-formed file - all three pairs made, the
comment pair carrying the tag from the extra bytes. Passes when ASan reports
nothing, (a)/(b) pair nothing they cannot, and (c) is unchanged.
NOT claimed: the other damage in those fuzz files (crash-3.doc still runs out of
memory later, see the report); only the loading of these three tables.

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read WordDocument.cpp at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0021 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '020ab05c8f^')
BASELINE = bool(os.environ.get('BASELINE'))
REL = 'MsBinaryFile/DocFile/WordDocument.cpp'


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig', 'replace')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig', errors='replace').read()


DRIVER = r'''
#include <cstdio>
#include <cstring>
#include <vector>
typedef unsigned int _UINT32;
struct ByteStructure { virtual ~ByteStructure() {} };
struct BookmarkFirst : ByteStructure { short id; BookmarkFirst(short i) : id(i) {} };
struct Plex { std::vector<ByteStructure*> Elements; std::vector<int> CharacterPositions; };
struct Names { std::vector<unsigned char*> extra; unsigned short cbExtra;
    std::vector<unsigned char*>& getDataExtra() { return extra; }
    unsigned short getDataExtraSize() { return cbExtra; } };
struct _bmkStartEnd { int start, end; _UINT32 bookmarkId; };
struct Doc {
    Plex *BookmarkStartPlex, *BookmarkEndPlex, *AnnotStartPlex, *AnnotEndPlex, *BookmarkProtStartPlex, *BookmarkProtEndPlex;
    Names* BkmkAnnotNames; void* AutoTextPlex;
    std::vector<_bmkStartEnd> BookmarkStartEndCPs, AnnotStartEndCPs, BookmarkProtStartEndCPs;
    void run() {
@@FRAGMENT@@
    }
};
static Plex* plex(int n, bool cps) { Plex* p = new Plex; for (int i = 0; i < n; i++) p->Elements.push_back(new BookmarkFirst(7 + i));
    if (cps) for (int i = 0; i <= n; i++) p->CharacterPositions.push_back(10 * i + 1); return p; }
static Plex* ends(int n) { Plex* p = new Plex; for (int i = 0; i <= n; i++) p->CharacterPositions.push_back(10 * i + 5); return p; }
int main(int argc, char** argv) {
    char c = argv[1][0];
    Doc d; d.AutoTextPlex = 0; Names names; d.BkmkAnnotNames = &names;
    d.BookmarkStartPlex = plex(1, true); d.AnnotStartPlex = plex(1, true); d.BookmarkProtStartPlex = plex(1, true);
    if (c == 'a') {            /* comment bookmark whose name carries no extra data */
        d.BookmarkEndPlex = ends(1); d.AnnotEndPlex = ends(1); d.BookmarkProtEndPlex = ends(1);
        names.cbExtra = 0; names.extra.push_back(NULL);
    } else if (c == 'b') {     /* end tables empty, tags present */
        d.BookmarkEndPlex = new Plex; d.AnnotEndPlex = new Plex; d.BookmarkProtEndPlex = new Plex;
        names.cbExtra = 6; unsigned char* e = new unsigned char[6]; e[0] = 0; e[1] = 1; _UINT32 t = 0x1234; memcpy(e + 2, &t, 4); names.extra.push_back(e);
    } else {                   /* well-formed */
        d.BookmarkEndPlex = ends(1); d.AnnotEndPlex = ends(1); d.BookmarkProtEndPlex = ends(1);
        names.cbExtra = 6; unsigned char* e = new unsigned char[6]; e[0] = 0; e[1] = 1; _UINT32 t = 0x1234; memcpy(e + 2, &t, 4); names.extra.push_back(e);
    }
    d.run();
    printf("BKM=%zu ANN=%zu PROT=%zu", d.BookmarkStartEndCPs.size(), d.AnnotStartEndCPs.size(), d.BookmarkProtStartEndCPs.size());
    if (!d.AnnotStartEndCPs.empty()) printf(" tag=%x end=%d", d.AnnotStartEndCPs[0].bookmarkId, d.AnnotStartEndCPs[0].end);
    printf("\n");
    return 0;
}
'''

CASES = [('a', 'comment bookmark without tag data', 'BKM=1 ANN=0 PROT=1'),
         ('b', 'end tables shorter than start tables', 'BKM=0 ANN=0 PROT=0'),
         ('c', 'well-formed bookmarks unchanged', 'BKM=1 ANN=1 PROT=1 tag=1234 end=5')]


def main():
    src = read(REL)
    a = src.find('for (size_t i = 0; i < BookmarkStartPlex->Elements.size(); ++i)')
    b = src.find('AutoTextPlex', a)
    if a < 0 or b < 0:
        sys.exit('bookmark loops not found - the extractor needs updating')
    work = tempfile.mkdtemp(prefix='rd0021-')
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write(DRIVER.replace('@@FRAGMENT@@', src[a:b]))
    exe = os.path.join(work, 'drv')
    r = subprocess.run(['c++', '-std=gnu++11', '-fsanitize=address', '-g', '-w', p, '-o', exe],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-3000:])
    fails = 0
    for arg, name, want in CASES:
        r = subprocess.run([exe, arg], capture_output=True, text=True, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
        out = r.stdout + r.stderr
        m = re.search(r'ERROR: AddressSanitizer: ([\w-]+)', out)
        ok = r.returncode == 0 and not m and r.stdout.strip() == want
        fails += not ok
        print(('ok   ' if ok else 'FAIL ') + '%s (%s): %s' % (
            name, 'baseline ' + BASE_REF if BASELINE else 'working tree',
            ('ASan ' + m.group(1)) if m else (r.stdout.strip() or 'rc=%d' % r.returncode)))
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
