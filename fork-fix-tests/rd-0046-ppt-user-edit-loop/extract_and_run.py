#!/usr/bin/env python3
"""
RD-0046 (our corpus run, no upstream issue): a .ppt whose UserEditAtom chain
loops back kept x2t reading it until it was killed - Apache POI's
test-data/slideshow/57272_corrupted_usereditatom.ppt ran the release x2t past
60 s at 1.4 GB.

Cause: CPPTDocumentInfo::ReadFromStream (MsBinaryFile/PptFile/Reader/
PPTDocumentInfo.cpp) follows offsetLastEdit from each UserEditAtom to the
previous one until it is 0, building a CPPTUserInfo (and re-reading its persist
directory) for each. A chain that points back to an edit already read never
ends. Fix: the offsets read are remembered and the chain stops at the first
repeat.

What runs: the REAL CPPTDocumentInfo::ReadFromStream (brace-matched; git show
BASE_REF:... with BASELINE=1) with stand-in record/stream/user-info classes in
which each edit's "previous edit" offset comes from a table. The stand-in gives
up after 1000 user infos and reports "endless". Cases: a chain 300 -> 200 -> 300
(loop: two users, then stop), 300 -> 300 (self loop: one user), and the normal
300 -> 200 -> 100 -> 0 (three users, unchanged).

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read PPTDocumentInfo.cpp at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0046 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', 'f4b6ef229c^')
BASELINE = bool(os.environ.get('BASELINE'))
REL = 'MsBinaryFile/PptFile/Reader/PPTDocumentInfo.cpp'


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
#include <map>
#include <set>
#include <string>
#include <vector>
typedef unsigned int _UINT32;
namespace POLE { struct Stream { _UINT32 pos; }; }
static std::map<_UINT32, _UINT32> g_prev;     // edit offset -> offset of the previous edit
namespace PPT {
struct StreamUtils { static void StreamSeek(long p, POLE::Stream* s) { s->pos = (_UINT32)p; } };
struct SRecordHeader { bool ReadFromStream(POLE::Stream*) { return true; } };
struct CRecordUserEditAtom { _UINT32 m_nOffsetLastEdit; void ReadFromStream(SRecordHeader&, POLE::Stream* s) { m_nOffsetLastEdit = g_prev[s->pos]; } };
struct CRecordCurrentUserAtom { _UINT32 m_nOffsetToCurrentEdit; };
struct CCurrentUser { _UINT32 m_nOffsetToCurrentEdit; bool m_bIsEncrypt; void FromAtom(CRecordCurrentUserAtom* a) { m_nOffsetToCurrentEdit = a->m_nOffsetToCurrentEdit; m_bIsEncrypt = false; } };
struct CPPTDocumentInfo;
static int g_users = 0;
struct CPPTUserInfo { CPPTDocumentInfo* m_pDocumentInfo; bool m_bEncrypt, m_bMacroEnabled; std::wstring m_strPassword; CRecordUserEditAtom m_oUser; size_t m_lIndexThisUser;
  CPPTUserInfo() { if (++g_users > 1000) { printf("endless\n"); exit(0); } }
  bool ReadFromStream(CRecordUserEditAtom* a, POLE::Stream*) { m_oUser = *a; return true; } };
struct CPPTDocumentInfo { CCurrentUser m_oCurrentUser; POLE::Stream* m_pStream; std::vector<CPPTUserInfo*> m_arUsers; std::wstring m_strPassword; bool m_bMacroEnabled;
  void Clear() {} bool ReadFromStream(CRecordCurrentUserAtom* pCurrentUser, POLE::Stream* pStream); };
@@FUNC@@
}
using namespace PPT;
int main(int argc, char** argv) {
  std::string c = argv[1];
  if (c == "loop") { g_prev[300] = 200; g_prev[200] = 300; }
  else if (c == "self") { g_prev[300] = 300; }
  else { g_prev[300] = 200; g_prev[200] = 100; g_prev[100] = 0; }
  CPPTDocumentInfo d; d.m_bMacroEnabled = false; POLE::Stream s; CRecordCurrentUserAtom cu; cu.m_nOffsetToCurrentEdit = 300;
  bool ok = d.ReadFromStream(&cu, &s);
  printf("ok=%d users=%zu\n", (int)ok, d.m_arUsers.size()); return 0;
}
'''

CASES = [('loop', 'chain 300 -> 200 -> 300', 'ok=1 users=2'),
         ('self', 'edit pointing to itself', 'ok=1 users=1'),
         ('chain', 'normal chain 300 -> 200 -> 100 -> 0 (unchanged)', 'ok=1 users=3')]


def main():
    src = read(REL)
    code = func(src, 'bool CPPTDocumentInfo::ReadFromStream(CRecordCurrentUserAtom')
    work = tempfile.mkdtemp(prefix='rd0046-')
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write(DRIVER.replace('@@FUNC@@', code))
    exe = os.path.join(work, 'drv')
    r = subprocess.run(['c++', '-std=gnu++11', '-w', p, '-o', exe], capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-3000:])
    fails = 0
    for arg, name, want in CASES:
        r = subprocess.run([exe, arg], capture_output=True, text=True, timeout=60)
        out = r.stdout.strip()
        ok = r.returncode == 0 and out == want
        fails += not ok
        print(('ok   ' if ok else 'FAIL ') + '%s (%s): %s' % (
            name, 'baseline ' + BASE_REF if BASELINE else 'working tree', out or 'rc=%d' % r.returncode))
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
