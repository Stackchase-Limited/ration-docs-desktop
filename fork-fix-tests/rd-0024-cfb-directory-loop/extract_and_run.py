#!/usr/bin/env python3
"""
RD-0024 (our corpus run, no upstream issue): a compound (OLE/CFB) file whose
directory entries link back in a loop made x2t recurse and allocate without
bound - LibreOffice's sd/qa/unit/data/ppt/pass/hang-16.ppt (7.7 KB) took the
release x2t past 1.5 GB in about a second.

Cause: CollectStreams in Common/3dParty/pole/pole.cpp (used by
Storage::GetAllStreams, which the format checker calls for every OLE file in
COfficeFileFormatChecker::isCompoundFile) walks child/prev/next indexes with no
record of the entries it has already seen; a storage whose child chain reaches
itself recurses forever (each level copying the path), a closed prev/next chain
loops forever in its queue. Its own comment said "potential infinite loop in
case of closed Entry chain ... it seems not to happen". Fix: the walk carries
the set of visited entries and skips an entry met again.

What runs: the REAL CollectStreams and the body of Storage::GetAllStreams
(brace-matched; git show BASE_REF:... with BASELINE=1) against a stand-in
DirTree/DirEntry/StorageIO. The stand-in's entry() stops the process (exit 3)
after a million lookups, so the baseline fails fast instead of eating memory.
Cases: a storage whose child is the root again (directory loop), a sibling
chain that closes on itself, and a well-formed tree (root -> {A, sub/ -> {B, C}}
listed exactly as before).

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read pole.cpp at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0024 commit
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', 'e26964a596^')
BASELINE = bool(os.environ.get('BASELINE'))
REL = 'Common/3dParty/pole/pole.cpp'


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
            if depth == 0: return a, src[a:i + 1]
        i += 1


DRIVER = r'''
#include <cstdio>
#include <cstdlib>
#include <list>
#include <queue>
#include <set>
#include <string>
#include <vector>
namespace POLE {
typedef unsigned long long uint64;
struct DirEntry { bool dir; std::wstring name; uint64 child, prev, next; };
struct DirTree { static const uint64 End = 0xffffffff; std::vector<DirEntry> v; long calls = 0;
    DirEntry* entry(uint64 i) { if (++calls > 1000000) { printf("directory walk did not end (1000000 lookups)\n"); exit(3); }
                                return i < v.size() ? &v[i] : 0; }
    DirEntry* entry(const std::wstring&, bool) { return &v[0]; } };
struct StorageIO { DirTree* dirtree; };
struct Storage { StorageIO* io; std::list<std::wstring> GetAllStreams(const std::wstring& storageName); };
@@COLLECT@@
@@GETALL@@
}
using namespace POLE;
static DirEntry E(bool d, const wchar_t* n, uint64 c, uint64 p, uint64 x) { DirEntry e; e.dir = d; e.name = n; e.child = c; e.prev = p; e.next = x; return e; }
int main(int argc, char** argv) {
    const uint64 N = DirTree::End; DirTree t; char c = argv[1][0];
    t.v.push_back(E(true, L"Root Entry", 1, N, N));
    if (c == 'd') { t.v.push_back(E(true, L"S", 0, N, N)); }                     /* storage S whose child is the root again */
    else if (c == 's') { t.v.push_back(E(false, L"A", N, 2, N)); t.v.push_back(E(false, L"B", N, N, 1)); } /* A <-> B */
    else { t.v.push_back(E(false, L"A", N, N, 2)); t.v.push_back(E(true, L"sub", 3, N, N));
           t.v.push_back(E(false, L"B", N, N, 4)); t.v.push_back(E(false, L"C", N, N, N)); }
    StorageIO io; io.dirtree = &t; Storage s; s.io = &io;
    std::list<std::wstring> r = s.GetAllStreams(L"/");
    printf("%zu:", r.size()); for (std::list<std::wstring>::iterator i = r.begin(); i != r.end(); ++i) printf(" %ls", i->c_str());
    printf("\n"); return 0;
}
'''

CASES = [('d', 'storage whose child chain leads back to the root', '0:'),
         ('s', 'sibling chain closed on itself', '2: /A /B'),
         ('w', 'well-formed tree (unchanged)', '3: /A /sub/B /sub/C')]


def main():
    src = read(REL)
    _, collect = func(src, 'void CollectStreams(')
    a, getall = func(src, 'std::list<std::wstring> Storage::GetAllStreams(')
    work = tempfile.mkdtemp(prefix='rd0024-')
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write(DRIVER.replace('@@COLLECT@@', collect).replace('@@GETALL@@', getall))
    exe = os.path.join(work, 'drv')
    r = subprocess.run(['c++', '-std=gnu++11', '-w', p, '-o', exe], capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-3000:])
    fails = 0
    for arg, name, want in CASES:
        try:
            r = subprocess.run([exe, arg], capture_output=True, text=True, timeout=60)
            out, rc = r.stdout.strip(), r.returncode
        except subprocess.TimeoutExpired:
            out, rc = 'timed out', -1
        ok = rc == 0 and out == want
        fails += not ok
        print(('ok   ' if ok else 'FAIL ') + '%s (%s): %s' % (
            name, 'baseline ' + BASE_REF if BASELINE else 'working tree', out or 'rc=%d' % rc))
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
