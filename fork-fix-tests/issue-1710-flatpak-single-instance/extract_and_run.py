#!/usr/bin/env python3
"""
#1710 - Flatpak without the network permission: every file opened from the file
manager starts a new Desktop Editors instance instead of a tab in the running one.

Linux decides "am I the first instance?" in SingleApplication with CSocket(0, port,
false, true) (desktop-apps win-linux/extras/update-daemon/src/classes/csocket.cpp):
whoever binds the UDP port on 127.<uid>.1 is primary, the others send their
arguments to that port. A loopback address belongs to a network namespace, and
Flatpak with --unshare=network gives every `flatpak run` a namespace of its own, so
every launch binds successfully, believes it is primary and opens its own window.

The fix keeps the instance socket in a file-system folder every instance sees
($XDG_RUNTIME_DIR, under Flatpak $XDG_RUNTIME_DIR/app/$FLATPAK_ID), as an AF_UNIX
datagram socket guarded by an flock'd lock file; with no such folder it is UDP as
before.

This compiles the REAL csocket.cpp/csocket.h (working tree, or git show BASE_REF
with BASELINE=1) with a driver that uses CSocket exactly as SingleApplication does,
inside the rd-linux-verify:24.04 Docker image, and runs pairs of "instances" with
`unshare -n` (a fresh network namespace each, as Flatpak does) sharing only the
emulated per-app runtime folder.

Claimed: in separate network namespaces the second instance is secondary and its
file reaches the first; same namespace still works; a primary killed with -9 does
not block the next start; without XDG_RUNTIME_DIR the UDP path still works.
NOT claimed: a real Flatpak build or Flatpak's own mounts (the shared
$XDG_RUNTIME_DIR/app/$FLATPAK_ID folder is Flatpak's documented behaviour, emulated
here), the Qt application around it, or Windows (unchanged, #ifndef _WIN32).

  RD_REPO=<desktop-apps> (default ../../desktop-apps)
  BASELINE=1 [BASE_REF=<ref>]  - must fail
Needs docker and the rd-linux-verify:24.04 image (exit 77 when missing).
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.join(HERE, '..', '..', 'desktop-apps')
REL = 'win-linux/extras/update-daemon/src/classes/'
BASE_REF = os.environ.get('BASE_REF', 'eecac8e78^')
IMAGE = os.environ.get('RD_LINUX_IMAGE', 'rd-linux-verify:24.04')

DRIVER = r'''
// Uses CSocket the way platform_linux/singleapplication.cpp does.
#include "csocket.h"
#include <stdio.h>
#include <string>
#include <unistd.h>
#include <atomic>
int main(int argc, char **argv) {
    const int port = 13012;
    std::string name = argv[1];
    CSocket inst(0, port, false, true);              // SingleApplication::SingleApplication
    if (inst.isPrimaryInstance()) {
        printf("%s: primary\n", name.c_str()); fflush(stdout);
        std::atomic<int> got(0);
        inst.onMessageReceived([&](void *buf, size_t sz) {
            printf("%s: received %.*s\n", name.c_str(), (int)sz, (const char*)buf); fflush(stdout); got = 1; });
        int wait = argc > 2 ? atoi(argv[2]) : 40;
        for (int i = 0; i < wait && !got; i++) usleep(100000);
        return 0;
    }
    printf("%s: secondary\n", name.c_str()); fflush(stdout);
    std::string msg = "/home/u/" + name + ".docx";
    CSocket s(port, 0, false, true);                  // SingleApplication::sendMessage
    printf("%s: sent=%d\n", name.c_str(), (int)s.sendMessage((void*)msg.data(), msg.size()));
    return 0;
}
'''

SCRIPT = r'''
set -e
cd /tmp && g++ -std=c++14 -Wall -pthread -I/src -o drv /work/drv.cpp /src/csocket.cpp
mkdir -p /run/user/1000/app/org.onlyoffice.desktopeditors && chmod 700 /run/user/1000
NS='unshare -n sh -c'
lo='ip link set lo up 2>/dev/null;'
echo "## netns"
( export XDG_RUNTIME_DIR=/run/user/1000 FLATPAK_ID=org.onlyoffice.desktopeditors
  $NS "$lo exec ./drv a1" & sleep 0.5; $NS "$lo exec ./drv a2"; wait )
echo "## same"
( export XDG_RUNTIME_DIR=/run/user/1000 FLATPAK_ID=org.onlyoffice.desktopeditors
  ./drv b1 & sleep 0.5; ./drv b2; wait )
echo "## crash"
( export XDG_RUNTIME_DIR=/run/user/1000 FLATPAK_ID=org.onlyoffice.desktopeditors
  ./drv c0 600 & P=$!; sleep 0.5; kill -9 $P; wait $P 2>/dev/null || true
  $NS "$lo exec ./drv c1" & sleep 0.5; $NS "$lo exec ./drv c2"; wait )
echo "## udp"
( unset XDG_RUNTIME_DIR FLATPAK_ID
  ./drv d1 & sleep 0.5; ./drv d2; wait )
'''


def main():
    if not shutil.which('docker'):
        print('SKIP docker not found'); return 77
    if subprocess.run(['docker', 'image', 'inspect', IMAGE], capture_output=True).returncode != 0:
        print('SKIP image %s not found' % IMAGE); return 77
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, 'src'); work = os.path.join(d, 'work')
        os.makedirs(src); os.makedirs(work)
        for f in ('csocket.cpp', 'csocket.h'):
            if os.environ.get('BASELINE'):
                data = subprocess.run(['git', '-C', REPO, 'show', BASE_REF + ':' + REL + f],
                                      capture_output=True, check=True).stdout
            else:
                data = open(os.path.join(REPO, REL, f), 'rb').read()
            open(os.path.join(src, f), 'wb').write(data)
        open(os.path.join(work, 'drv.cpp'), 'w').write(DRIVER)
        open(os.path.join(work, 'run.sh'), 'w').write(SCRIPT)
        r = subprocess.run(['docker', 'run', '--rm', '--privileged', '-v', src + ':/src:ro',
                            '-v', work + ':/work:ro', IMAGE, 'sh', '/work/run.sh'],
                           capture_output=True, text=True, timeout=300)
    out = r.stdout
    if r.returncode != 0:
        sys.stdout.write(out + r.stderr)
        print('FAILED - the run did not complete'); return 1
    sections = {}
    cur = None
    for line in out.splitlines():
        if line.startswith('## '):
            cur = line[3:]; sections[cur] = []
        elif cur:
            sections[cur].append(line.strip())
    fails = 0

    def check(ok, what):
        nonlocal fails
        print('  %-72s %s' % (what, 'ok' if ok else 'FAILED'))
        fails += 0 if ok else 1

    for sec, first, second, what in (
            ('netns', 'a1', 'a2', 'separate network namespaces (Flatpak without network)'),
            ('same', 'b1', 'b2', 'same network namespace'),
            ('crash', 'c1', 'c2', 'after a primary was killed with -9'),
            ('udp', 'd1', 'd2', 'no XDG_RUNTIME_DIR (UDP as before)')):
        s = sections.get(sec, [])
        check(first + ': primary' in s and second + ': secondary' in s,
              what + ': the second start is secondary')
        check('%s: received /home/u/%s.docx' % (first, second) in s,
              what + ': its file reaches the first')
    if fails:
        print(out)
    print('FAILED' if fails else 'ok - a second start finds the first one, with or without a shared network')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
