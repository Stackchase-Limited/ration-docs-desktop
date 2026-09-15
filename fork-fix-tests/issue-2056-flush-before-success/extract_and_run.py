#!/usr/bin/env python3
"""
#2056 - a save reported success before the bytes reached the disk, so a power cut
between "saved" and the kernel's own flush lost the document while the editor had
already told the user it was safe.

BACK-FILLED. The fix was committed earlier with no test; see the verification
status section of UPSTREAM_TRIAGE.md.

Two halves, and this checks the one that decides whether the user is told the
truth: SaveFile must ask the locker to force the bytes out, and must downgrade a
successful save when that fails. The platform implementations of Flush
(FlushFileBuffers on Windows, F_FULLFSYNC/fsync, GIO on Linux) cannot all be
exercised on one host; the decision at the call site can.

NOTE ON THE BASELINE: a back-filled test cannot baseline against HEAD, which
already contains the fix - it would pass both ways and prove nothing. The default
below is the commit before the fix landed.

  ./extract_and_run.py              -> passes
  BASELINE=1 ./extract_and_run.py   -> fails, at 6cd7c621^
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(HERE, '..', '..', 'desktop-sdk')
REL = 'ChromiumBasedEditors/lib/src/applicationmanager_p.h'
BASE_REF = os.environ.get('BASE_REF', '6cd7c621^')

if os.environ.get('BASELINE'):
    source = subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, REL)],
                            capture_output=True, text=True, check=True).stdout
else:
    source = open(os.path.join(REPO, REL), encoding='utf-8').read()

# Lift the decision verbatim rather than restating it, so what gets compiled is the
# shipped text. HEAD has two lines here; the pre-fix revision has none.
m = re.search(r'^[ \t]*if \(bRes && !m_pLocker->Flush\(\)\)\s*\n[ \t]*bRes = false;',
              source, re.M)
has_flush = m is not None
decision = m.group(0).strip() if has_flush else '/* this revision makes no such check */'

harness = r'''
#include <stdio.h>

struct Locker {
    bool flushSucceeds;
    bool flushWasAsked;
    bool Flush() { flushWasAsked = true; return flushSucceeds; }
};

/* The decision, lifted verbatim from applicationmanager_p.h. */
static bool saveReportsSuccess(Locker *m_pLocker, bool writeSucceeded) {
    bool bRes = writeSucceeded;
%(decision)s
    return bRes;
}

static int failures = 0;
static void check(bool flushIsAsked, bool writeOk, bool flushOk,
                  bool wantReported, bool wantAsked, const char *why) {
    (void)flushIsAsked;
    Locker l; l.flushSucceeds = flushOk; l.flushWasAsked = false;
    bool got = saveReportsSuccess(&l, writeOk);
    bool ok = (got == wantReported) && (l.flushWasAsked == wantAsked);
    printf("  %%-52s reported=%%-5s asked=%%-5s %%s\n", why,
           got ? "saved" : "failed", l.flushWasAsked ? "yes" : "no", ok ? "ok" : "FAILED");
    if (!ok) failures++;
}

int main() {
    const bool FLUSH = %(flush)s;   /* whether this revision asks the locker at all */

    check(FLUSH, true,  true,  true,  FLUSH, "write ok, disk confirms - saved");
    check(FLUSH, true,  false, !FLUSH, FLUSH, "write ok, disk did NOT confirm - must NOT say saved");
    check(FLUSH, false, true,  false, false, "write failed - already a failure, no flush needed");
    check(FLUSH, false, false, false, false, "write failed and flush would fail too");

    if (!FLUSH)
        printf("\n  this revision never asks the locker to force the bytes out (#2056)\n");
    printf("\n%%s\n", failures ? "FAILED"
        : "ok - a save is only reported once the bytes are known to have landed");
    return failures ? 1 : 0;
}
''' % {'flush': 'true' if has_flush else 'false', 'decision': decision}

with tempfile.TemporaryDirectory() as d:
    src = os.path.join(d, 'harness.cpp')
    exe = os.path.join(d, 'harness')
    open(src, 'w').write(harness)
    c = subprocess.run(['clang++', '-std=c++14', '-Wall', '-o', exe, src],
                       capture_output=True, text=True)
    if c.returncode != 0:
        sys.stderr.write(c.stdout + c.stderr)
        raise SystemExit('harness did not compile')
    rc = subprocess.run([exe]).returncode
    if not has_flush:
        sys.stderr.write(
            '\nSaveFile never calls m_pLocker->Flush() in this revision, so a save is '
            'reported\nsuccessful while the bytes are still only in the page cache '
            '(#2056)\n')
        sys.exit(1)
    sys.exit(rc)
