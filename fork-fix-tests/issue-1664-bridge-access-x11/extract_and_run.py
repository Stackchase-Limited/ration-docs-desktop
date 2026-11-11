#!/usr/bin/env python3
"""
#1664 follow-up - the bridge gate broke the Linux build of client_scheme_wrapper.cpp.

bridge_access.h (the #1664 bridge-origin policy) declares
    enum Access { None = 0, Full = 1 };
and is included from cefwrapper/client_app.h. On Linux client_app.h first includes
<X11/Xlib.h>, whose X.h has `#define None 0L`, so the enumerator becomes `0L = 0`
and every TU that includes client_app.h before undefining None fails:
client_scheme_wrapper.cpp includes it on line 37 and only #undefs None on line 57
(11 errors: "expected identifier", "cannot initialize return object of type
'Access' with an rvalue of type 'long'"). cefapplication.cpp and
client_renderer_wrapper.cpp happened to be fine. Found with a syntax-only build
of desktop-sdk against CEF 109's Linux headers in the rd-linux-verify (Ubuntu
24.04) image; macOS never includes Xlib, so the mac build did not show it.

Now bridge_access.h #undefs None itself (as client_scheme_wrapper.cpp and
cefapplication.cpp already do).

The test compiles the REAL bridge_access.h with c++ -fsyntax-only after the exact
definition X11/X.h makes (`#define None 0L`) - the include order client_app.h
produces on Linux - and then once more without it.

  RD_REPO=<desktop-sdk checkout>   (default ../../desktop-sdk)
  BASELINE=1                       read bridge_access.h at BASE_REF; must FAIL
  BASE_REF                         default <fix commit>^ (re-pin after cherry-pick)

NOT claimed: no full Linux build or link was run; the syntax-only Linux build of
cefview, cefapplication, applicationmanager, client_renderer_wrapper,
client_scheme_wrapper, client_resource_handler_async, spellchecker, fileprinter,
keyboardchecker and additional/create is clean with the fix.
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-sdk'))
BASE_REF = os.environ.get('BASE_REF', '35814c5b^')
BASELINE = bool(os.environ.get('BASELINE'))
HDR = 'ChromiumBasedEditors/lib/src/bridge_access.h'


def read(rel):
    if BASELINE:
        r = subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)], capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit('git show %s:%s failed: %s' % (BASE_REF, rel, r.stderr.strip()))
        return r.stdout
    return open(os.path.join(REPO, rel), encoding='utf-8').read()


def main():
    cxx = shutil.which('c++') or shutil.which('clang++') or shutil.which('g++')
    tmp = tempfile.mkdtemp(prefix='bridge-x11-')
    rc = 0
    try:
        with open(os.path.join(tmp, 'bridge_access.h'), 'w') as f:
            f.write(read(HDR))
        print('%s bridge_access.h from %s' % ('BASELINE' if BASELINE else 'checkout', BASE_REF if BASELINE else REPO))
        for name, pre in (('after <X11/Xlib.h> (#define None 0L), as client_app.h includes it on Linux', '#define None 0L\n'),
                          ('on its own (macOS, Windows)', '')):
            src = os.path.join(tmp, 't.cpp')
            with open(src, 'w') as f:
                f.write(pre + '#include "bridge_access.h"\n'
                        'int main() { return NSBridgeAccess::Full == 1 ? 0 : 1; }\n')
            r = subprocess.run([cxx, '-std=c++17', '-fsyntax-only', '-w', src], capture_output=True, text=True)
            ok = r.returncode == 0
            print('%s compiles %s' % ('ok  ' if ok else 'FAIL', name))
            if not ok:
                print('\n'.join(l for l in r.stderr.splitlines() if 'error' in l)[:1500])
                rc = 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print('PASS' if rc == 0 else 'FAIL')
    return rc


if __name__ == '__main__':
    sys.exit(main())
