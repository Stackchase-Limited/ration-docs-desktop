#!/usr/bin/env python3
"""
#2434 - the application exits 0 after Qt initialises, with no window and nothing
printed, on FreeBSD under the Linuxulator.

CSocket decides whether this process is the primary instance by binding a UDP
socket to 127.<uid-1000>.1 (inetAddrFromUserId).  Linux puts the whole of
127.0.0.0/8 on lo, so that binds for any uid.  FreeBSD configures only 127.0.0.1
on lo0, and the Linuxulator uses the FreeBSD network stack - so every uid but
1000 fails the bind with EADDRNOTAVAIL, the process concludes it is a second
instance, hands its arguments to a primary that does not exist, and exits 0.

macOS has the same single-address loopback, so this host reproduces the
condition exactly - no stub, no simulation.  This extracts the real initSocket,
inetAddrFromUserId and addr_not_available out of csocket.cpp by brace matching,
compiles them with clang++ and binds for real.

  BASELINE=1 runs it against HEAD, where it must fail.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(HERE, '..', '..', 'desktop-apps')
REL = 'win-linux/extras/update-daemon/src/classes/csocket.cpp'
BASE_REF = os.environ.get('BASE_REF', 'HEAD')

if os.environ.get('BASELINE'):
    source = subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, REL)],
                            capture_output=True, text=True, check=True).stdout
else:
    source = open(os.path.join(REPO, REL), encoding='utf-8').read()


def resolve_win32(text):
    """Take the non-_WIN32 branch of every _WIN32 conditional.

    initSocket opens a brace inside `#ifdef _WIN32` and another inside its
    `#else`, closing only one - so brace matching has to see one branch at a
    time. Other conditionals are passed through untouched.
    """
    out = []
    stack = []  # None for a conditional we pass through, else True when emitting
    for line in text.split('\n'):
        st = line.strip()
        if re.match(r'#\s*if(n?)def\s+_WIN32\b', st) or \
           re.match(r'#\s*if\s+defined\s*\(\s*_WIN32\s*\)', st):
            negated = bool(re.match(r'#\s*ifndef\s+_WIN32\b', st))
            stack.append(negated)          # emit the `if` branch only when #ifndef
            continue
        if re.match(r'#\s*if', st):
            stack.append(None)
        elif re.match(r'#\s*else\b', st) and stack:
            if stack[-1] is not None:
                stack[-1] = not stack[-1]
                continue
        elif re.match(r'#\s*endif\b', st) and stack:
            if stack.pop() is not None:
                continue
        if all(f is not False for f in stack):
            out.append(line)
    return '\n'.join(out)


def block(text, name):
    """Extract a free function definition by brace matching, or None."""
    m = re.search(r'^static [\w \*]+\b%s\s*\(' % re.escape(name), text, re.M)
    if not m:
        return None
    start = m.start()
    open_brace = text.index('{', m.end())
    depth = 0
    for i in range(open_brace, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise SystemExit('unbalanced braces in %s' % name)


source = resolve_win32(source)

init_socket = block(source, 'initSocket')
if init_socket is None:
    raise SystemExit('initSocket not found - the extractor needs updating')
user_addr = block(source, 'inetAddrFromUserId')
if user_addr is None:
    raise SystemExit('inetAddrFromUserId not found - the extractor needs updating')
not_avail = block(source, 'addr_not_available') or ''

inaddr = re.search(r'^#define INADDR .*$', source, re.M)
if not inaddr:
    raise SystemExit('INADDR not found')

harness = r'''
#include <stdio.h>
#include <string.h>
#include <string>
#include <errno.h>
#include <unistd.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
typedef int SOCKET;
#define close_socket(a) close(a)
/* Linux-only flag; irrelevant to the bind semantics under test. */
#ifndef SOCK_CLOEXEC
# define SOCK_CLOEXEC 0
#endif
%(inaddr)s
typedef struct sockaddr_in SockAddr;

%(not_avail)s

%(user_addr)s

%(init_socket)s

static int failures = 0;
static void check(bool ok, const char *what) {
    printf("  %%-58s %%s\n", what, ok ? "ok" : "FAILED");
    if (!ok) failures++;
}

int main() {
    struct in_addr shown;
    shown.s_addr = (in_addr_t)inetAddrFromUserId();
    printf("uid=%%d, unique address = %%s\n", (int)getuid(), inet_ntoa(shown));

    /* The condition under test: this host has only 127.0.0.1 on loopback. */
    {
        SOCKET fd; SockAddr a; int r; std::string e;
        int probe = socket(AF_INET, SOCK_DGRAM, 0);
        SockAddr p; memset(&p, 0, sizeof p);
        p.sin_family = AF_INET; p.sin_addr.s_addr = inetAddrFromUserId(); p.sin_port = htons(13099);
        bool unique_is_loopback = (p.sin_addr.s_addr == inet_addr(INADDR));
        int pr = bind(probe, (struct sockaddr*)&p, sizeof p);
        close(probe);
        if (unique_is_loopback) {
            printf("  this uid maps to 127.0.0.1 - nothing to test here\n");
            return 77;
        }
        if (pr == 0) {
            printf("  this host binds the unique address, so it is not the #2434 host\n");
            return 77;
        }
        check(errno == EADDRNOTAVAIL, "the unique address fails with EADDRNOTAVAIL");
        (void)fd; (void)a; (void)r; (void)e;
    }

    /* 1. A first instance must become primary: bind succeeds. */
    SOCKET fd1 = -1; SockAddr a1; int r1 = -1; std::string e1;
    bool ok1 = initSocket(13099, fd1, a1, r1, e1, true);
    check(ok1, "initSocket returns true for the first instance");
    check(r1 == 0, "the first instance binds successfully (it is primary)");
    check(a1.sin_addr.s_addr == inet_addr(INADDR),
          "it fell back to 127.0.0.1, which exists on this host");

    /* 2. A second instance must NOT also become primary. The fallback must not
     *    turn EADDRINUSE into a second primary. */
    SOCKET fd2 = -1; SockAddr a2; int r2 = -1; std::string e2;
    bool ok2 = initSocket(13099, fd2, a2, r2, e2, true);
    check(ok2, "initSocket returns true for the second instance");
    check(r2 != 0, "the second instance does NOT bind (it is secondary)");
    check(errno == EADDRINUSE, "and it fails with EADDRINUSE, not EADDRNOTAVAIL");
    if (fd2 >= 0) close(fd2);
    if (fd1 >= 0) close(fd1);

    /* 3. use_unique_addr=false is unchanged. */
    SOCKET fd3 = -1; SockAddr a3; int r3 = -1; std::string e3;
    bool ok3 = initSocket(13098, fd3, a3, r3, e3, false);
    check(ok3 && r3 == 0, "use_unique_addr=false still binds 127.0.0.1");
    check(a3.sin_addr.s_addr == inet_addr(INADDR), "and uses 127.0.0.1");
    if (fd3 >= 0) close(fd3);

    printf("%%s\n", failures ? "FAILED" : "ok - a first instance starts and a second stays secondary");
    return failures ? 1 : 0;
}
''' % {'inaddr': inaddr.group(0), 'not_avail': not_avail,
       'user_addr': user_addr, 'init_socket': init_socket}

with tempfile.TemporaryDirectory() as d:
    src = os.path.join(d, 'harness.cpp')
    exe = os.path.join(d, 'harness')
    open(src, 'w').write(harness)
    c = subprocess.run(['clang++', '-std=c++11', '-Wall', '-o', exe, src],
                       capture_output=True, text=True)
    if c.returncode != 0:
        sys.stderr.write(c.stdout + c.stderr)
        raise SystemExit('harness did not compile')
    sys.exit(subprocess.run([exe]).returncode)
