#!/usr/bin/env python3
"""
#2476 - SIGSEGV on exit in CAscApplicationManager::OnDestroyWindow
(libascdocumentscore.so + 0x2fc2d2, `mov (%rdi),%rax` with rdi = 0), three times
on one machine with identical frames, always on the CloseApplication ->
CApplicationCEF::Close path.

The report reads it as a null `this`. It is not: `this` is dereferenced at the
top of the function (m_pInternal->m_nWindowCounter--), so a null `this` faults
there, not 98 bytes in. What runs at that depth, once the last window is gone,
is CefCookieManager::GetGlobalManager(nullptr)->FlushStore(nullptr) - and the
faulting instruction is the vtable load through the returned pointer. libcef
returns null from GetGlobalManager once its global request context is no longer
valid, which is exactly the state during shutdown. On our macOS build the same
shape is visible directly: `ldr x8, [x0]` straight after the GetGlobalManager
call, with no check.

This compiles the real OnDestroyWindow (applicationmanager.cpp) against stubs in
which GetGlobalManager returns null, as it does at shutdown, and runs it with the
window counter at 1. BASELINE=1 uses the parent of the fix, where the child must
die with SIGSEGV. A second run with a live cookie manager checks the store is
still flushed and the message loop still told to exit.
"""
import os
import shutil
import signal
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-sdk'))
CPP = 'ChromiumBasedEditors/lib/src/applicationmanager.cpp'
# Pinned to the parent of the commit that landed the fix, never HEAD.
BASE_REF = os.environ.get('BASE_REF', '6bdcae56^')
BASELINE = bool(os.environ.get('BASELINE'))


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, text=True, check=True).stdout
    return open(os.path.join(REPO, rel), encoding='utf-8').read()


def brace_match(text, start):
    ob = text.index('{', start)
    depth = 0
    for i in range(ob, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise SystemExit('unbalanced braces')


src = read(CPP)
at = src.find('void CAscApplicationManager::OnDestroyWindow()')
if at == -1:
    raise SystemExit('OnDestroyWindow not found - the extractor needs updating')
body = brace_match(src, at)
if 'FlushStore' not in body or 'ExitMessageLoop' not in body:
    raise SystemExit('extracted the wrong block')

PROGRAM = r'''
#include <cstdio>
#include <cstdlib>
// Minimal CefRefPtr / CefCookieManager: enough for the real function body.
template <class T> struct CefRefPtr {
	T* p;
	CefRefPtr(T* x = nullptr) : p(x) {}
	T* operator->() const { return p; }
	explicit operator bool() const { return p != nullptr; }
};
static int g_flushed = 0;
struct CefCookieManager {
	virtual bool FlushStore(void*) { g_flushed++; return true; }
	static bool s_live;
	static CefCookieManager* s_inst;
	// libcef: null once the global request context is gone (shutdown).
	static CefRefPtr<CefCookieManager> GetGlobalManager(void*) { return s_live ? s_inst : nullptr; }
};
bool CefCookieManager::s_live = false;
CefCookieManager* CefCookieManager::s_inst = new CefCookieManager();

static int g_exitLoop = 0;
struct CApplicationCEF { void ExitMessageLoop() { g_exitLoop++; } };
struct CAscApplicationManager_Private {
	int m_nWindowCounter = 1;
	bool m_bIsExitMessageLoop = false;
	CApplicationCEF* m_pApplication = new CApplicationCEF();
};
struct CAscApplicationManager {
	CAscApplicationManager_Private* m_pInternal = new CAscApplicationManager_Private();
	void OnDestroyWindow();
};

%s

int main(int argc, char** argv) {
	CefCookieManager::s_live = (argc > 1 && argv[1][0] == '1');
	CAscApplicationManager m;
	m.OnDestroyWindow();
	printf("returned: flushed=%%d exitLoop=%%d isExit=%%d\n", g_flushed, g_exitLoop, (int)m.m_pInternal->m_bIsExitMessageLoop);
	return 0;
}
''' % body


def main():
    work = tempfile.mkdtemp(prefix='rd2476-')
    try:
        cpp = os.path.join(work, 't.cpp')
        exe = os.path.join(work, 't')
        with open(cpp, 'w') as f:
            f.write(PROGRAM)
        subprocess.run(['c++', '-std=c++17', '-O1', '-w', cpp, '-o', exe], check=True)
        fails = 0

        r = subprocess.run([exe, '0'], capture_output=True, text=True)
        crashed = r.returncode < 0
        print('shutdown (GetGlobalManager returns null): %s' %
              ('killed by %s' % signal.Signals(-r.returncode).name if crashed else r.stdout.strip()))
        if crashed or 'exitLoop=1' not in r.stdout or 'isExit=1' not in r.stdout:
            print('  FAIL  must return and still leave the message loop')
            fails += 1
        else:
            print('  ok    returns, message loop told to exit')

        r = subprocess.run([exe, '1'], capture_output=True, text=True)
        print('normal close (live cookie manager): %s' % (r.stdout.strip() or 'rc=%d' % r.returncode))
        if r.returncode != 0 or 'flushed=1' not in r.stdout or 'exitLoop=1' not in r.stdout:
            print('  FAIL  cookie store must be flushed and the loop exited')
            fails += 1
        else:
            print('  ok    cookie store flushed, message loop told to exit')

        if BASELINE:
            print('BASELINE (%s): the shutdown case must FAIL' % BASE_REF)
        print('%s #2476' % ('FAIL' if fails else 'PASS'))
        return 1 if fails else 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
