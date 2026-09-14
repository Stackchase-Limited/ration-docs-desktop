#!/usr/bin/env python3
"""
#2105 - segmentation fault on a Wayland session.

main.cpp forces QT_QPA_PLATFORM=xcb on every non-Windows start. On a Wayland
session with no X display there is nothing for xcb to connect to, and the process
died with a segfault before Qt printed its own "could not load the Qt platform
plugin xcb".

Running natively on Wayland is a port, not a flag: the bundled Qt has no wayland
platform plugin - the reporter's log lists what is there - and the in-process GTK
file dialogs are X11-only (#2168). What is fixable is the crash: say so instead.

XWayland sets DISPLAY, so a Wayland session that has it is unaffected and still
takes the xcb path. Only the case that was already doomed changes.

This extracts the real Utils::isWaylandSession by brace matching and exercises the
guard against real QtCore, so qgetenv is the actual function.

BASELINE=1 runs against HEAD, where there is no guard at all - which is the defect.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(HERE, '..', '..', 'desktop-apps')
BASE_REF = os.environ.get('BASE_REF', 'HEAD')


def read(rel):
    if os.environ.get('BASELINE'):
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, text=True, check=True).stdout
    return open(os.path.join(REPO, rel), encoding='utf-8').read()


main_src = read('win-linux/src/main.cpp')
if 'isWaylandSession() && qgetenv("DISPLAY").isEmpty()' not in main_src:
    sys.stderr.write(
        'main.cpp has no Wayland guard - it still forces QT_QPA_PLATFORM=xcb with no '
        'X display to connect to, and segfaults (#2105)\n')
    sys.exit(1)

utils_src = read('win-linux/src/utils.cpp')
at = utils_src.find('auto isWaylandSession() -> bool {')
if at == -1:
    sys.stderr.write('isWaylandSession not found\n')
    sys.exit(2)
depth = 0
open_brace = utils_src.index('{', at)
for i in range(open_brace, len(utils_src)):
    if utils_src[i] == '{':
        depth += 1
    elif utils_src[i] == '}':
        depth -= 1
        if depth == 0:
            end = i
            break
fn = utils_src[at:end + 1].replace('auto isWaylandSession() -> bool',
                                   'static bool isWaylandSession()', 1)

harness = r'''
#include <QString>
#include <QByteArray>
#include <stdio.h>

%s

/* The guard as main.cpp spells it. */
static bool wouldRefuseToStart() {
    return isWaylandSession() && qgetenv("DISPLAY").isEmpty();
}

static int failures = 0;
static void scenario(const char *sessionType, const char *waylandDisplay,
                     const char *display, bool wantRefuse, const char *why) {
    qunsetenv("XDG_SESSION_TYPE"); qunsetenv("WAYLAND_DISPLAY"); qunsetenv("DISPLAY");
    if (sessionType)    qputenv("XDG_SESSION_TYPE", sessionType);
    if (waylandDisplay) qputenv("WAYLAND_DISPLAY", waylandDisplay);
    if (display)        qputenv("DISPLAY", display);

    bool got = wouldRefuseToStart();
    printf("  %%-46s refuses=%%-5s %%s\n", why, got ? "yes" : "no",
           got == wantRefuse ? "ok" : "FAILED");
    if (got != wantRefuse) failures++;
}

int main() {
    scenario("wayland", NULL,        NULL, true,
             "Wayland, no X display - the crash case");
    scenario(NULL,      "wayland-0", NULL, true,
             "Wayland by WAYLAND_DISPLAY, no X display");
    scenario("wayland", "wayland-0", ":0",  false,
             "Wayland with XWayland - unaffected");
    scenario("x11",     NULL,        ":0",  false,
             "plain X11 - unaffected");
    scenario("x11",     NULL,        NULL, false,
             "X11 with no DISPLAY - left alone, not our case");
    scenario(NULL,      NULL,        NULL, false,
             "nothing set - left alone");

    printf("\n%%s\n", failures ? "FAILED"
        : "ok - only a Wayland session with no X display is refused, and it is told why");
    return failures ? 1 : 0;
}
''' % fn

with tempfile.TemporaryDirectory() as d:
    src = os.path.join(d, 'harness.cpp')
    exe = os.path.join(d, 'harness')
    open(src, 'w').write(harness)
    Q = '/opt/homebrew/opt/qt@5'
    c = subprocess.run(['clang++', '-std=c++14', '-Wall', '-o', exe, src,
                        '-I' + Q + '/lib/QtCore.framework/Headers',
                        '-F' + Q + '/lib', '-framework', 'QtCore'],
                       capture_output=True, text=True)
    if c.returncode != 0:
        sys.stderr.write(c.stdout + c.stderr)
        raise SystemExit('harness did not compile')
    sys.exit(subprocess.run([exe]).returncode)
