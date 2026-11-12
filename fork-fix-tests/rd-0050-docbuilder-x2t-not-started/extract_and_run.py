#!/usr/bin/env python3
"""
RD-0050 (found in passing, UPSTREAM_TRIAGE.md "Latent problems"): docbuilder
took an x2t that could not be started - or that died on a signal - for a
successful conversion. On open that ran the editor on a missing Editor.bin and
the process aborted (SIGABRT, NSInvalidArgumentException from
CJSObjectJSC::call_func adding a nil JSValue); on save it reported success with
no output file.

Cause (core/DesktopEditor/doctrenderer/docbuilder_p.h, ConvertToInternalFormat
and SaveFile): the forked child did `execve(x2t); exit(EXIT_SUCCESS);`, so a
failed exec exited 0; the parent read the status only `if (WIFEXITED(status))`,
leaving nReturnCode at 0 for a crashed x2t; fork failure (-1) kept 0 too; on
Windows a failed CreateProcessW kept 0 as well. Fix: those cases now return
EXIT_FAILURE (the child uses _exit), and CV8RealTimeWorker::OpenFile
(docbuilder_p.cpp) stops when Editor.bin is missing or empty instead of handing
an empty buffer to NativeOpenFileData.

What runs: the REAL `#ifdef LINUX` launch block of both functions is lifted out
of docbuilder_p.h by #if/#endif matching (git show BASE_REF:... with
BASELINE=1), compiled with -DLINUX (and -D_MAC on macOS) into a function that
returns nReturnCode, and run against (a) a converter path that does not exist,
(b) a script that kills itself with SIGSEGV, (c) a script that exits 0 and
(d) one that exits 89. Passes when (a) and (b) are non-zero and (c)/(d) keep
their exit codes.

NOT claimed here: the Windows branch (not compiled; read only) and the
Editor.bin guard in docbuilder_p.cpp. Those were checked by running a docbuilder
linked against the rebuilt doctrenderer.framework: no x2t -> "open file error
(1)", exit 1 (baseline: SIGABRT); an x2t that exits 0 without output -> exit 1
(baseline: SIGABRT); with the real x2t, open + save docx still works.

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read docbuilder_p.h at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0050 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', 'fe4e8f5cfe^')
BASELINE = bool(os.environ.get('BASELINE'))
REL = 'DesktopEditor/doctrenderer/docbuilder_p.h'


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig', 'replace')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig', errors='replace').read()


def linux_block(text, func_start):
    """The body of the first `#ifdef LINUX` ... matching `#endif` after func_start."""
    a = text.find(func_start)
    if a < 0:
        sys.exit('%r not found - the extractor needs updating' % func_start)
    m = re.compile(r'^[ \t]*#ifdef LINUX[ \t]*$', re.M).search(text, a)
    if not m:
        sys.exit('#ifdef LINUX not found after %r' % func_start)
    depth = 0
    pos = m.start()
    for line in re.finditer(r'^[ \t]*#[ \t]*(if|ifdef|ifndef|endif)\b.*$', text[pos:], re.M):
        if line.group(1).startswith('if'):
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return text[m.end():pos + line.start()]
    sys.exit('unbalanced #if after %r' % func_start)


def main():
    src = read(REL)
    blocks = [('open (ConvertToInternalFormat)', linux_block(src, 'int ConvertToInternalFormat(')),
              ('save (SaveFile)', linux_block(src, 'int SaveFile(const int& type'))]
    drv = r'''
#include <string>
#include <cstdio>
#include <cstdlib>
#include <unistd.h>
#include <sys/wait.h>
static std::string U_TO_UTF8(const std::wstring& s) { return std::string(s.begin(), s.end()); }
'''
    for i, (_, body) in enumerate(blocks):
        drv += ('static int launch%d(const std::wstring& sConverterExe, const std::wstring& sTempFileForParams)\n'
                '{\n\tint nReturnCode = 0;\n%s\n\treturn nReturnCode;\n}\n' % (i, body))
    drv += r'''
int main(int argc, char** argv) {
    std::wstring params = L"/dev/null";
    for (int f = 0; f < 2; ++f) {
        for (int i = 1; i < argc; ++i) {
            std::string a(argv[i]);
            int rc = f == 0 ? launch0(std::wstring(a.begin(), a.end()), params)
                            : launch1(std::wstring(a.begin(), a.end()), params);
            printf("F%d A%d RC=%d\n", f, i, rc);
        }
    }
    return 0;
}
'''
    work = tempfile.mkdtemp(prefix='rd0050-')
    scripts = {}
    for name, body in (('crash', 'kill -SEGV $$'), ('ok', 'exit 0'), ('err89', 'exit 89')):
        p = os.path.join(work, name)
        open(p, 'w').write('#!/bin/sh\n%s\n' % body)
        os.chmod(p, 0o755)
        scripts[name] = p
    args = [os.path.join(work, 'no-such-x2t'), scripts['crash'], scripts['ok'], scripts['err89']]
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write(drv)
    exe = os.path.join(work, 'drv')
    defs = ['-DLINUX'] + (['-D_MAC'] if sys.platform == 'darwin' else [])
    r = subprocess.run(['c++', '-std=gnu++11', '-w', '-O0'] + defs + [p, '-o', exe], capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-2000:])
    r = subprocess.run([exe] + args, capture_output=True, text=True, timeout=60)
    got = {(int(f), int(a)): int(rc) for f, a, rc in re.findall(r'F(\d) A(\d) RC=(-?\d+)', r.stdout)}
    ok_all = True
    for f, (label, _) in enumerate(blocks):
        res = [got.get((f, i)) for i in (1, 2, 3, 4)]
        ok = res[0] not in (None, 0) and res[1] not in (None, 0) and res[2] == 0 and res[3] == 89
        ok_all &= ok
        print(('ok   ' if ok else 'FAIL ') + 'docbuilder x2t launch, %s (%s): missing x2t rc=%s, crashed x2t rc=%s, '
              'x2t exit 0 rc=%s, x2t exit 89 rc=%s' % (label, 'baseline ' + BASE_REF if BASELINE else 'working tree',
                                                       res[0], res[1], res[2], res[3]))
    sys.exit(0 if ok_all else 1)


if __name__ == '__main__':
    main()
